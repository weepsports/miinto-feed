#!/usr/bin/env python3
"""
Nakładka na feed Miinto z Base.com.

- Pobiera oryginalny feed TSV z Base.
- Odzież: wykrywa packshot (zdjęcie produktu na białym tle, bez modela)
  i ustawia go jako image_link; pozostałe zdjęcia trafiają do
  additional_image_link w oryginalnej kolejności.
- Buty, torby i akcesoria (product_type zaczyna się od Shoes/Bags/Accessories):
  bez zmian - pierwsze zdjęcie zostaje pierwsze.
- Wszystkie inne kolumny (id, ceny, stany, grupy) przechodzą 1:1.

Użycie:
  python3 miinto_feed.py --src URL_FEEDU_BASE --out public/miinto.tsv

Wyniki analizy zdjęć są trzymane w cache (image_cache.json), więc każde
kolejne uruchomienie pobiera tylko nowe zdjęcia.
"""
import argparse
import csv
import hashlib
import io
import json
import os
import sys
import tempfile
import urllib.request
from concurrent.futures import ThreadPoolExecutor

from PIL import Image

KEEP_RE_PREFIXES = ("Shoes", "Bags", "Accessories")
WHITE_MIN = 0.35   # min. udział białych pikseli
SKIN_MAX = 0.06    # max. udział pikseli w kolorze skóry
MIN_ROWS_RATIO = 0.8  # bezpiecznik: nie publikuj, jeśli feed nagle się skurczył

csv.field_size_limit(sys.maxsize)


def fetch(url, timeout=60):
    req = urllib.request.Request(url, headers={"User-Agent": "miinto-feed-overlay/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def score_image(url):
    """Zwraca (udział białych, udział skóry) albo None, gdy zdjęcia nie da się pobrać."""
    try:
        data = fetch(url, timeout=20)
        im = Image.open(io.BytesIO(data)).convert("RGB").resize((64, 64))
    except Exception:
        return None
    white = skin = 0
    for r, g, b in im.getdata():
        if r > 238 and g > 238 and b > 238:
            white += 1
        mx, mn = max(r, g, b), min(r, g, b)
        # kolor skóry (z wykluczeniem czerwonych tkanin: g >= b, r-g < 110)
        if (r > 95 and g > 40 and b > 20 and mx - mn > 15 and 15 < r - g < 110
                and g >= b and r > b):
            skin += 1
    corners_white = all(min(im.getpixel(xy)) > 238 for xy in ((1, 1), (62, 1), (1, 62), (62, 62)))
    return [white / 4096, skin / 4096, corners_white]


def is_packshot(s):
    w, sk = s[0], s[1]
    corners = s[2] if len(s) > 2 else False
    # duże białe tło bez modela, albo ciemny produkt wypełniający kadr na białym tle
    return (w > WHITE_MIN and sk < SKIN_MAX) or (w > 0.25 and sk < 0.01 and corners)


def pick_packshot(urls, cache):
    """Pierwsze (w kolejności katalogu) zdjęcie wyglądające na packshot.
    Jeśli pierwsze zdjęcie już nim jest - zostaje (zwykle to przód produktu,
    a kolejne packshoty to tył/detal)."""
    for u in urls:
        s = cache.get(u)
        if s and is_packshot(s):
            return u
    return None


def split_imgs(row, ii, ai):
    imgs = [row[ii].strip()] if row[ii].strip() else []
    if ai is not None and row[ai].strip():
        imgs += [u.strip() for u in row[ai].split(",") if u.strip()]
    return imgs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--cache", default="image_cache.json")
    ap.add_argument("--workers", type=int, default=12)
    args = ap.parse_args()

    raw = fetch(args.src, timeout=180).decode("utf-8")

    # Base przebudowuje plik kilka razy na dobę - jeśli się nie zmienił, nic nie robimy
    src_hash = hashlib.sha1(raw.encode("utf-8")).hexdigest()
    state_file = args.cache + ".src_hash"
    if os.path.exists(args.out) and os.path.exists(state_file):
        with open(state_file, encoding="utf-8") as f:
            if f.read().strip() == src_hash:
                print("Feed z Base bez zmian - pomijam.")
                return

    rows = list(csv.reader(io.StringIO(raw), delimiter="\t"))
    if len(rows) < 2:
        sys.exit("Pusty feed z Base - nic nie publikuję.")
    head, body = rows[0], rows[1:]
    col = {h: i for i, h in enumerate(head)}
    gi, pi, ii = col["item_group_id"], col["product_type"], col["image_link"]
    ai = col.get("additional_image_link")

    # bezpiecznik na wypadek awarii po stronie Base
    if os.path.exists(args.out):
        with open(args.out, encoding="utf-8") as f:
            prev = sum(1 for _ in csv.reader(f, delimiter="\t")) - 1
        if prev > 0 and len(body) < prev * MIN_ROWS_RATIO:
            sys.exit(f"Feed ma {len(body)} wierszy, poprzednio {prev} - nie nadpisuję.")

    cache = {}
    if os.path.exists(args.cache):
        with open(args.cache, encoding="utf-8") as f:
            cache = json.load(f)

    # grupy odzieżowe i ich zdjęcia
    groups = {}
    for r in body:
        if r[pi].startswith(KEEP_RE_PREFIXES):
            continue
        groups.setdefault(r[gi], [])
        for u in split_imgs(r, ii, ai):
            if u not in groups[r[gi]]:
                groups[r[gi]].append(u)

    # cache z wersji v1 (bez narożników) przeliczamy na nowo
    todo = sorted({u for us in groups.values() for u in us
                   if u not in cache or len(cache[u]) < 3})
    with ThreadPoolExecutor(args.workers) as ex:
        for u, s in zip(todo, ex.map(score_image, todo)):
            if s is not None:
                cache[u] = s

    packshot = {g: pick_packshot(us, cache) for g, us in groups.items()}

    changed = 0
    for r in body:
        p = packshot.get(r[gi])
        if not p:
            continue
        imgs = split_imgs(r, ii, ai)
        if p in imgs and imgs[0] != p:
            imgs = [p] + [u for u in imgs if u != p]
            r[ii] = imgs[0]
            if ai is not None:
                r[ai] = ",".join(imgs[1:])
            changed += 1

    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(os.path.abspath(args.out)))
    with os.fdopen(fd, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, delimiter="\t", lineterminator="\n")
        w.writerow(head)
        w.writerows(body)
    os.replace(tmp, args.out)

    with open(args.cache, "w", encoding="utf-8") as f:
        json.dump(cache, f)
    with open(state_file, "w", encoding="utf-8") as f:
        f.write(src_hash)

    # lista modeli odzieży bez żadnego packshotu (do dosesji zdjęć / wyłączenia z Miinto)
    ti = col.get("title")
    titles = {r[gi]: (r[ti] if ti is not None else "") for r in body}
    with open(os.path.join(os.path.dirname(os.path.abspath(args.cache)), "bez_packshotu.csv"),
              "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["item_group_id", "title"])
        for g, p in sorted(packshot.items()):
            if not p:
                w.writerow([g, titles.get(g, "")])

    found = sum(1 for v in packshot.values() if v)
    print(f"Wiersze: {len(body)} | grupy odzieżowe: {len(groups)} | "
          f"z packshotem: {found} | wierszy z nową kolejnością: {changed}")


if __name__ == "__main__":
    main()
