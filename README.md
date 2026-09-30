# book-property-scraping

**Tier:** C / tool prototype (portfolio breadth, not interview flagship)  
**Owner path:** `bookchaowalit/book-apps/tools/book-property-scraping`

## Purpose

Property listing scrape prototypes (e.g. DDProperty-style modules).

## Entry points

- `scrape_property_listings.py, property/ddproperty_scraper.py`

## Stack

Python

## How to run (local)

```bash
# From this repository root
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python3 scrape_property_listings.py --dry-run              # plan only, no network or writes
python3 scrape_property_listings.py --type condo_sale_bkk  # live, writes data/exported/
```

Output goes to this repository's git-ignored `data/exported/`
(`property_listings.csv`, `property_history.csv`; the DDproperty adapter writes
`ddproperty_condos.csv`). `--max-pages` is recorded in the plan but the
generic runner currently fetches one page per listing type.

## Crawling behaviour (honest)

- Every request has a timeout (15-30 s); the generic runner waits 2 s between
  listing types.
- There is no retry/backoff or robots.txt check yet, and requests still send a
  browser-like `User-Agent`; see `docs/UPGRADE-PLAN.md`.
- When the direct page is empty, the runner falls back to scraping Brave/Bing
  (and Google) result pages, or Firecrawl when `FIRECRAWL_API_KEY` is set in
  the environment. Search-engine HTML scraping is against those engines' terms;
  treat it as prototype-only.

## Checks (offline)

```bash
pip install -r requirements.txt pytest ruff
ruff check .
python -m pytest -q
```

Tests replay `tests/fixtures/` and mocked search results only; CI
(`.github/workflows/ci.yml`) runs the same commands.

## Boundaries

- **Not** a lake-first data product. Durable market datasets live under `book-*-data` repos.
- **Not** coupled to Solo Empire monorepo runtime. Nested Git repo; commit only inside this tree.
- Never commit `.env`, cookies, session dumps, or scraped PII dumps to Git.

## Limitations (honest)

Listing sites often ban scraping. Research/prototype only. No claim of live MLS integration.

## Related

- Active collection product: `book-job-scraping` (Tier A tool)
- Lake products: `book-crypto-data`, `book-fx-data`, `book-stock-data`, …
- Solo Empire catalog: `repository-catalog/BOOK-DEV-BACKLOG-BD.md` (BD-012)
