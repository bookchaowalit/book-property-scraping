# Upgrade plan — book-property-scraping

## Current state

Score: **5.5/10** (pass 1: 2 -> 5; pass 2: 5 -> 5.5) — the CLI and scheduler
paths share one tested collect/persist flow and price-drop alerts actually
work, but live collection still relies on a browser-like User-Agent and
search-engine HTML fallbacks.

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

### P2
- Real pagination (DDproperty page 2+) behind a hard page cap, once live
  behaviour can be checked; today one page per type is fetched.
- Canonicalise listing URLs (strip query/fragment) before keying history.

## Done in this pass (pass 1)
- Fixed `parents[4]` monorepo path lookup that raised `IndexError` in a
  standalone clone (both test modules failed to import); output now goes to
  `data/exported/`.
- Fixed `extract_listings` splitting one listing in two when a long
  price/room/area line followed the title.
- Fixed DDproperty search fallback reading `snippet` while search helpers
  return `description` (price hints were always missed).
- 2 s pause between listing types; bare `except` narrowed.
- `test_run_writes_dedicated_snapshot` made a live DDproperty request; it now
  mocks the page fetch, and `tests/conftest.py` blocks all sockets in tests.
- Added `requirements.txt`, ruff/pytest config, CI, parser tests (5 -> 14);
  README rewritten to match behaviour; untracked committed `__pycache__`.

## Done in this pass (pass 2)
- Fixed price-drop alerts never firing: history was appended before
  `detect_price_drops` read it, so the "old" price was always the current one.
  `persist()` now detects first, then writes.
- `main()` and `PropertyListingScraper.run()` share `collect()` /
  `collect_type()` / `_search_fallback_listings()` / `persist()`; the
  scheduler wrapper also gained `output_dir` and the dependency check.
- Price history keyed by listing URL (new `url` column; legacy headers kept,
  title fallback for old rows); `save_listings`/`detect_price_drops` no longer
  mutate inputs; `extract_listings` fills `location` from short label lines.
- `--max-pages` hidden and documented as ignored (one page per type).
- `tests/test_property_runner_flow.py` (14 -> 20 tests).
