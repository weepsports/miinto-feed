# Nakładka na feed Miinto (ubierzsie.com)

Pobiera feed Miinto z Base.com i zmienia **tylko kolejność zdjęć**:

- **odzież** – pierwszy packshot (zdjęcie produktu na białym tle, bez modela) trafia do `image_link`,
  reszta zdjęć do `additional_image_link` w kolejności z katalogu; jeśli 1. zdjęcie już jest packshotem – bez zmian;
- **buty, torby, akcesoria** (`product_type` zaczyna się od Shoes / Bags / Accessories) – bez zmian;
- id, item_group_id, ceny, stany i pozostałe kolumny – 1:1 jak w Base.

Katalog w Base pozostaje nietknięty.

## Uruchomienie na GitHubie (2× na godzinę, przed oknami pobierania Miinto)

1. Nowe repozytorium na GitHubie (publiczne – wymagane dla darmowego GitHub Pages), wrzucić te pliki.
2. Settings → Secrets and variables → Actions → New secret: `BASE_FEED_URL` = adres feedu Miinto z Base.
3. Settings → Pages → Deploy from branch → `main` / folder `/docs`.
4. Actions → „Miinto feed” → Run workflow (pierwszy przebieg analizuje wszystkie zdjęcia, ok. 15–30 min; kolejne tylko nowe).
5. Adres dla Miinto: `https://<konto>.github.io/<repozytorium>/miinto.tsv`

## Uruchomienie na własnym serwerze

    pip install pillow
    python3 miinto_feed.py --src "<adres feedu z Base>" --out /var/www/feed/miinto.tsv --cache image_cache.json

i dodać do crona co godzinę.

## Bezpieczniki

- jeśli Base zwróci pusty feed albo o ponad 20% mniej wierszy niż poprzednio – stary plik zostaje bez zmian;
- plik zapisywany atomowo (Miinto nigdy nie pobierze połowy pliku).
