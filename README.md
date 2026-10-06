# Hitta din kommun

Rank Sweden's 290 municipalities (kommuner) by what matters to **you**. Move a
slider for each criterion and the map and list update with the best matches.

![Screenshot: map of Sweden coloured by match score, sliders and a ranked list](docs/screenshot.png)

The app has no built-in idea of what a "good" kommun is. Every criterion counts
only as much as your slider says, and you can see the raw number behind each
score.

## Criteria

| Criterion | Unit | Source | Status |
|---|---|---|---|
| Reported violent crime | per 1,000 inhabitants per year, average 2020–2022 | MSB, *Öppna jämförelser: trygghet och säkerhet 2023* (Brå crime statistics) | loaded |
| Reported theft | same | same | loaded |
| Reported vandalism | same | same | loaded |
| Average house price (småhus) | tkr | SCB, *Fastighetspriser och lagfarter* | **not loaded yet**, see below |

Reported crime is not the same as all crime. It is also skewed by tourism,
commuting and shopping centres in small municipalities. The app says this on
the page.

## How it works

```
raw downloads (not committed)          data/ (committed, plain CSV/JSON)           SQLite (rebuilt on deploy)
  .xlsx / .csv / .shp  ──convert_*──▶  kommuner.csv                ──load_data──▶  Kommun, Indicator, Value
                                       indicators.json
                                       values/<indicator>.csv
```

- `finder/sources.py`: parsers for each source format. They check headers and
  fail loudly instead of guessing.
- `finder/scoring.py`: min-max normalization plus a weighted mean. A kommun
  with a missing value is scored on the criteria it has and reports what's
  missing; it never gets a silent zero.
- `GET /api/rank?w_<indicator>=0..10`: JSON ranking used by the frontend.
- Frontend: plain JS with Leaflet (vendored in `finder/static/finder/vendor/`).
  The map uses a 5-step blue quantile scale.

## Run locally

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
python manage.py migrate
python manage.py load_data
python manage.py runserver
```

Tests and lint:

```bash
python manage.py test
ruff check . && ruff format --check .
```

## Adding or updating data

### Crime (Öppna jämförelser)

Download the yearly *Öppna jämförelser: trygghet och säkerhet* workbook, then:

```bash
python manage.py convert_crime raw/oppna-jamforelser-2023.xlsx
python manage.py load_data
```

Update `year`/`unit` in `data/indicators.json` if the period changes.

### House prices (SCB)

1. In [SCB Statistikdatabasen](https://www.statistikdatabasen.scb.se/), open
   *Boende, byggande och bebyggelse → Fastighetspriser och lagfarter*. Pick the
   table with the average purchase price (köpeskilling, medelvärde i tkr) for
   permanent small houses (permanenta småhus) by region.
2. Select **all kommuner**, **one year** and **one measure**, then export as CSV.
3. Convert it and load it:

   ```bash
   python manage.py convert_house_prices raw/scb-smahus.csv
   python manage.py load_data
   ```

4. Set `year` in `data/indicators.json` to the year you exported, then commit
   `data/values/house-price.csv`.

The converter accepts SCB's comma, semicolon or tab exports, either encoding,
and `..` for missing values. It rejects files with more than one value per
kommun.

### Map boundaries

`finder/static/finder/kommuner.geojson` and `data/kommuner.csv` were built from a
SWEREF 99 TM kommun shapefile:

```bash
python manage.py build_geo raw/Kommun_Sweref99TM.shp --tolerance 400
```

## Deploy (Render, free tier)

`render.yaml` defines one free web service in Frankfurt. `build.sh` installs
the dependencies, collects static files and rebuilds the SQLite database from
`data/`. The app only reads the database, so it needs no hosted database.

1. Push this repo to GitHub.
2. In Render: **New → Blueprint** and pick the repo.

On the free tier the service sleeps after 15 minutes without traffic, so the
first request after that takes about a minute.

## Ideas

- More criteria: commuting time, school results (Skolverket), municipal tax
  rate (SCB), distance to nature or the coast.
- Shareable links that keep the slider positions in the URL.
- A table view of all 290 kommuner.
