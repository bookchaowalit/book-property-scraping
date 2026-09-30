# Upgrade plan — book-property-scraping

## Current state

Score: **5/10** (was 2/10) — tests and the runner now work from a standalone
clone and the markdown parser is fixture-tested, but live collection still
relies on a browser-like User-Agent and search-engine HTML fallbacks.

## Backlog

### P0
- Decide (owner) whether search-engine HTML scraping (Brave/Bing/Google) stays.
  If not, delete `_brave_search`/`_bing_search`/Google fallback and keep only
  DDproperty `__NEXT_DATA__` + optional Firecrawl API.

### P1
- Replace the spoofed Firefox `HEADERS` with an identifying UA
  (`book-property-scraping/1.0 (+repo URL)`) once confirmed DDproperty still
  serves it; add bounded retry/backoff on 429/5xx (see the `http.py` helper in
  book-restaurant-scraping for a tested pattern) and a robots.txt check.
- Implement `--max-pages` (pagination) or remove the flag.
- Unify `main()` and `PropertyListingScraper.run()` — they duplicate the
  search-fallback loop; extract one `collect_type()` function and test it with
  a mocked `free_scrape_url`.
- `detect_price_drops` keys history by title only; key by canonical URL when
  present so two units with the same title do not collide.

### P2
- Populate `location` in `extract_listings` (the fixture has a location line
  that is currently ignored).
- `save_listings` mutates input dicts (`scraped_at`); copy instead.

## Done in this pass
- Fixed `parents[4]` monorepo path lookup that raised `IndexError` in a
  standalone clone (both test modules failed to import); output now goes to
  `data/exported/`.
- Fixed `extract_listings` splitting one listing in two when a long
  price/room/area line followed the title.
- Fixed DDproperty search fallback reading `snippet` while search helpers
  return `description` (price hints were always missed).
- 2 s pause between listing types; bare `except` narrowed.
- Added `requirements.txt`, ruff/pytest config, CI, parser tests (5 -> 14);
  README rewritten to match behaviour; untracked committed `__pycache__`.
