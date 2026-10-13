# book-property-scraping — Product brief

**Slug:** `bookchaowalit/book-property-scraping`  
**Generated:** 2026-08-11 (bulk Book Dev closeout)  
**Status:** collection adapter present; scheduler still runs from `book-job-scraping`

## Purpose

Portfolio repository under Book Dev. This brief records ownership and the
current honest status so the nested tree is not an empty shell in the task
system.

## Runnable path

See `README.md` for install and run instructions when present.

## Current adapters

- `property/ddproperty_scraper.py` — Thai `/เช่าคอนโด` `__NEXT_DATA__` parser
- `scrape_property_listings.py` — broader listing helper

Tests live under `tests/`. The scheduler job stays disabled until httpx can
pass Cloudflare. Collection scheduling remains in `book-job-scraping`.

## Limits

- Not claimed as production-ready unless README and tests prove it.
- Mobile smoke / emulator acceptance is separate and toolchain-dependent.

## Source README excerpt

```
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
# Install whatever deps the script imports (often requests/httpx/bs4).
# Prefer reading the scraper module docstring/imports first — no 
```
