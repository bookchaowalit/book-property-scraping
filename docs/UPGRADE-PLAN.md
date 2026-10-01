# Upgrade plan — book-property-scraping

## Current state

Score: **6/10** (pass 1: 2 -> 5; pass 2: 5 -> 5.5; pass 3: 5.5 -> 6) — the CLI and scheduler
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

## Done in this pass (pass 3)
- `property/atomic_io.py`: `property_listings.csv`, `ddproperty_condos.csv`
  and the price history are written atomically; history "append" rewrites old
  + new so a killed run cannot leave a torn row (header of legacy files kept).
- `canonical_listing_url()` keys price history (was P2): lower-case host, no
  fragment/trailing slash/tracking params, sorted query; legacy rows with
  tracking params still match on read.
- `--alert-drop-pct` validated to (0, 100] in the CLI and scheduler wrapper;
  `--output-dir` must not be a file.
- User-Agent and search-engine fallbacks untouched (owner decisions P0/P1).
- `tests/test_property_persistence.py` (20 -> 38 tests incl. parametrised).
- Bug-pattern sweep (`tests/test_bug_pattern_sweep.py`, 4 tests): ddproperty
  `_price_value` rejects NaN/inf (NaN slipped past `max_price`); search
  fallback keeps only results whose host is a portal or its subdomain
  (`is_property_host`), not any URL that mentions one in its query string.
- Number edge cases: `parse_price` raised `ValueError` on separator-only
  text before "ล้าน" ("ราคาเริ่มต้น... ล้านบาท"), which aborted the whole
  listing type in `collect`; "1.234.567 บาท" parsed as 1.234 and "1,5 ล้าน"
  as 15,000,000. It now uses `_grouped_number` (decimal separator detection,
  finite only). `DDPropertyScraper(max_price="nan")` is rejected instead of
  silently disabling the price filter. Regression tests in
  `tests/test_property_parsers.py`.
