#!/usr/bin/env python3
"""
Scrape property listings from DDproperty via free httpx+BS4.
Tracks new listings, price changes, and investment opportunities.

Outputs (under this repository's git-ignored data/ directory):
    - data/exported/property_listings.csv (latest)
    - data/exported/property_history.csv (appended)
    - Console alerts for price drops >10%

Usage:
    python3 scrape_property_listings.py --dry-run
    python3 scrape_property_listings.py --type condo_sale_bkk
    python3 scrape_property_listings.py --alert-drop-pct 10
"""

import argparse
import csv
import json
import os
import re
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from property.atomic_io import render_csv, write_text_atomic

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None

# Resolve the repository root without reading its environment file. Live
# collection loads dotenv only after the caller has explicitly skipped dry-run.
# This file lives at the repository root, so no parent walking is needed (the
# old monorepo ``parents[4]`` lookup raised IndexError in a standalone clone).
_root = Path(__file__).resolve().parent

try:
    import httpx
except ImportError:
    httpx = None

try:
    from bs4 import BeautifulSoup
except ImportError:
    BeautifulSoup = None

ROOT = _root
OUTPUT_DIR = ROOT / "data" / "exported"
# Pause between listing types so a full run does not burst 12 requests.
TYPE_DELAY_SECONDS = 2.0

HEADERS = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64; rv:128.0) Gecko/20100101 Firefox/128.0"}

# URLs that indicate garbage/CAPTCHA/consent pages
_GARBAGE_URL_PATTERNS = [
    'google.com', 'youtube.com', 'consent.google', 'policies.google',
    '/httpservice/retry/', '/search?q=', 'accounts.google',
    'duckduckgo.com', 'wikipedia.org',
]

# DDproperty search URL patterns — multiple regions + types
DDPROPERTY_SEARCH = {
    "condo_sale_bkk": "https://www.ddproperty.com/condo-for-sale/bangkok",
    "condo_rent_bkk": "https://www.ddproperty.com/condo-for-rent/bangkok",
    "house_sale_bkk": "https://www.ddproperty.com/house-for-sale/bangkok",
    "townhouse_bkk": "https://www.ddproperty.com/townhouse-for-sale/bangkok",
    "condo_sale_chiangmai": "https://www.ddproperty.com/condo-for-sale/chiang-mai",
    "condo_sale_pattaya": "https://www.ddproperty.com/condo-for-sale/pattaya",
    "condo_sale_phuket": "https://www.ddproperty.com/condo-for-sale/phuket",
    "house_sale_chiangmai": "https://www.ddproperty.com/house-for-sale/chiang-mai",
    "house_sale_pattaya": "https://www.ddproperty.com/house-for-sale/pattaya",
    "land_sale_bkk": "https://www.ddproperty.com/land-for-sale/bangkok",
    "condo_rent_chiangmai": "https://www.ddproperty.com/condo-for-rent/chiang-mai",
    "condo_rent_pattaya": "https://www.ddproperty.com/condo-for-rent/pattaya",
}

DEFAULT_TYPE = "condo_sale_bkk"


def _load_runtime_env() -> None:
    if load_dotenv is not None:
        load_dotenv(_root / ".env")


def _require_live_dependencies() -> None:
    if httpx is None or BeautifulSoup is None:
        raise RuntimeError("httpx and beautifulsoup4 are required for live property collection")


def _is_valid_url(url: str) -> bool:
    """Reject garbage/CAPTCHA/consent/internal URLs."""
    if not url or url.startswith('/'):
        return False
    return not any(pat in url for pat in _GARBAGE_URL_PATTERNS)


def _clean_property_title(raw_title: str, url: str = "") -> str:
    """Clean breadcrumb garbage from search result titles used as property titles.
    
    Examples: 'DDProperty › Condo for Sale › Bangkok › Luxury Condo Name'
    or 'ddproperty.com - Condo for Sale in Bangkok | Property Name'
    """
    if not raw_title:
        return ""
    # Strip breadcrumb separators: take everything after the last '›' or '»'
    for sep in ['\u203a', '\u00bb']:
        if sep in raw_title:
            parts = raw_title.split(sep)
            raw_title = parts[-1].strip()
            break
    # Strip 'site.com - ' prefix
    raw_title = re.sub(r'^[a-z0-9.-]+\.com\s*[-\u2013\u2014|]\s*', '', raw_title, flags=re.IGNORECASE)
    title = raw_title.strip()
    # If still too long or empty, try URL slug
    if (len(title) > 80 or not title) and url:
        slug = url.rstrip('/').split('/')[-1]
        if slug and not slug.startswith('?') and not slug.startswith('#') and slug != 'thailand':
            title = slug.replace('-', ' ').replace('_', ' ').title()
    return title[:100] if title else ""


def _brave_search(query: str, limit: int = 20) -> list:
    """Search via Brave Search (no API key needed, works from VPS IPs).
    Falls back to Bing if Brave is rate-limited."""
    _require_live_dependencies()
    import urllib.parse
    try:
        url = f"https://search.brave.com/search?q={query.replace(' ', '+')}"
        resp = httpx.get(url, headers={"User-Agent": "Mozilla/5.0 (X11; Linux x86_64; rv:128.0) Gecko/20100101 Firefox/128.0"}, timeout=15, follow_redirects=True)
        if resp.status_code == 429:
            return _bing_search(query, limit)
        if resp.status_code != 200:
            return _bing_search(query, limit)
        soup = BeautifulSoup(resp.text, 'html.parser')
        results = []
        for el in soup.find_all(attrs={'data-pos': True}):
            a_tag = el.find('a', class_='result-header') or el.find('a')
            if not a_tag:
                continue
            href = a_tag.get('href', '')
            if 'click_url=' in href:
                href = urllib.parse.unquote(href.split('click_url=')[1].split('&')[0])
            title = a_tag.get_text(strip=True)
            desc_el = el.find(class_='snippet-description') or el.find('p', class_='')
            desc = desc_el.get_text(strip=True)[:200] if desc_el else ""
            if title and href and href.startswith('http') and _is_valid_url(href):
                results.append({"title": title[:200], "url": href, "description": desc})
            if len(results) >= limit:
                break
        if results:
            print(f"  Brave search: {len(results)} results for '{query[:50]}'")
            return results
        return _bing_search(query, limit)
    except Exception as e:
        print(f"  Brave search failed: {e}")
        return _bing_search(query, limit)


def _decode_bing_redirect(href: str) -> str:
    """Decode Bing redirect URL to get actual destination URL."""
    import urllib.parse
    import base64
    if 'bing.com/ck/' not in href or 'u=' not in href:
        return href
    try:
        parsed = urllib.parse.urlparse(href)
        params = urllib.parse.parse_qs(parsed.query)
        if 'u' in params:
            u_val = params['u'][0]
            # Remove 'a1' prefix and decode base64
            if u_val.startswith('a1'):
                b64_part = u_val[2:]
                # Add padding if needed
                padded = b64_part + '=' * (4 - len(b64_part) % 4) if len(b64_part) % 4 else b64_part
                return base64.b64decode(padded).decode('utf-8', errors='ignore')
            return urllib.parse.unquote(u_val)
    except (ValueError, UnicodeDecodeError):
        pass
    return href


def _bing_search(query: str, limit: int = 20) -> list:
    """Fallback search via Bing when Brave is rate-limited."""
    _require_live_dependencies()
    try:
        url = f"https://www.bing.com/search?q={query.replace(' ', '+')}"
        resp = httpx.get(url, headers={"User-Agent": "Mozilla/5.0 (X11; Linux x86_64; rv:128.0) Gecko/20100101 Firefox/128.0"}, timeout=15, follow_redirects=True)
        if resp.status_code != 200:
            return []
        soup = BeautifulSoup(resp.text, 'html.parser')
        results = []
        for li in soup.find_all('li', class_='b_algo'):
            a_tag = li.find('h2')
            if not a_tag:
                continue
            a_link = a_tag.find('a', href=True)
            if not a_link:
                continue
            href = _decode_bing_redirect(a_link['href'])
            title = a_link.get_text(strip=True)
            desc_el = li.find('p')
            desc = desc_el.get_text(strip=True)[:200] if desc_el else ""
            if title and href and href.startswith('http') and _is_valid_url(href):
                results.append({"title": title[:200], "url": href, "description": desc})
            if len(results) >= limit:
                break
        if results:
            print(f"  Bing search: {len(results)} results for '{query[:50]}'")
        return results
    except Exception as e:
        print(f"  Bing search failed: {e}")
        return []


def free_scrape_url(url: str) -> str:
    """Scrape a URL with free httpx+BS4 and return markdown-like content."""
    _require_live_dependencies()
    try:
        resp = httpx.get(url, headers=HEADERS, timeout=30, follow_redirects=True)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, 'html.parser')
        for tag in soup.find_all(['script', 'style', 'nav', 'footer', 'aside', 'header']):
            tag.decompose()
        main = soup.find('main') or soup.find('article') or soup.find(id=re.compile(r'content|main', re.I)) or soup.body
        if not main:
            return resp.text[:10000]
        for heading in main.find_all(['h1', 'h2', 'h3', 'h4', 'h5', 'h6']):
            level = int(heading.name[1])
            heading.string = f"\n{'#' * level} {heading.get_text(strip=True)}\n"
        for bold in main.find_all(['strong', 'b']):
            bold.string = f"**{bold.get_text(strip=True)}**"
        for link in main.find_all('a', href=True):
            link.string = f"[{link.get_text(strip=True)}]({link['href']})"
        text = main.get_text(separator='\n', strip=True)
        return text[:15000]
    except Exception as e:
        print(f"[WARN] Scrape error for {url}: {e}")
        return ""


def _firecrawl_search(query: str, limit: int = 20) -> list:
    """Fallback search via Firecrawl API when Google fails."""
    _require_live_dependencies()
    api_key = os.environ.get("FIRECRAWL_API_KEY", "")
    if not api_key:
        return []
    try:
        resp = httpx.post(
            "https://api.firecrawl.dev/v1/search",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={"query": query, "limit": limit},
            timeout=30,
        )
        if resp.status_code != 200:
            print(f"  Firecrawl fallback returned {resp.status_code}")
            return []
        data = resp.json()
        results = []
        for item in data.get("data", []):
            title = item.get("title", "") or item.get("metadata", {}).get("title", "")
            url = item.get("url", "") or item.get("metadata", {}).get("sourceURL", "")
            desc = item.get("description", "") or item.get("markdown", "")[:200]
            if title and url:
                results.append({"title": title[:200], "url": url, "description": desc})
            if len(results) >= limit:
                break
        if results:
            print(f"  Firecrawl fallback: {len(results)} results for '{query[:50]}'")
        return results
    except Exception as e:
        print(f"  Firecrawl fallback failed: {e}")
        return []


def google_search(query: str, limit: int = 20) -> list:
    """Search via Brave (primary) with Firecrawl fallback.
    Google is unreliable from server IPs, so Brave is the primary search engine."""
    # Try Brave first (reliable, no API key)
    results = _brave_search(query, limit)
    if results:
        return results
    # Fallback to Firecrawl
    results = _firecrawl_search(query, limit)
    if results:
        return results
    # Last resort: try Google directly
    results = []
    try:
        google_url = f"https://www.google.com/search?q={query.replace(' ', '+')}&num={limit}&hl=en"
        resp = httpx.get(google_url, headers=HEADERS, timeout=15, follow_redirects=True)
        if resp.status_code != 200:
            return []
        soup = BeautifulSoup(resp.text, 'html.parser')
        for a_tag in soup.find_all('a', href=True):
            href = a_tag['href']
            m = re.search(r'/url\?q=(https?://[^&]+)', href)
            if m:
                url = m.group(1)
            else:
                url = href
            if not _is_valid_url(url):
                continue
            title = a_tag.get_text(strip=True)
            if title and len(title) > 3:
                results.append({
                    "url": url,
                    "title": title[:200],
                    "description": "",
                })
            if len(results) >= limit:
                break
    except Exception as e:
        print(f"  Warning: Google search failed for '{query}': {e}")
    return results


def parse_price(price_str: str) -> float:
    """Extract numeric price from Thai format (e.g., '฿5,000,000' or '5 ล้านบาท')."""
    if not price_str:
        return 0.0

    # Remove currency symbols and whitespace
    clean = re.sub(r'[฿$,€\s]', '', price_str)

    # Handle ล้าน (million)
    if 'ล้าน' in price_str:
        match = re.search(r'([\d,.]+)\s*ล้าน', price_str)
        if match:
            return float(match.group(1).replace(',', '')) * 1_000_000

    # Handle plain numbers
    match = re.search(r'[\d,]+\.?\d*', clean)
    if match:
        return float(match.group().replace(',', ''))

    return 0.0


def extract_listings(markdown: str, listing_type: str) -> list:
    """Extract property listings from markdown content."""
    listings = []

    # Split by listing patterns (DDproperty uses various separators)
    lines = markdown.split('\n')
    current_listing = {}

    for line in lines:
        line = line.strip()
        if not line:
            continue

        price_match = re.search(r'(฿[\d,]+|[\d,.]+\s*ล้าน)', line)
        bed_match = re.search(r'(\d+)\s*(bed|ห้องนอน)', line, re.IGNORECASE)
        bath_match = re.search(r'(\d+)\s*(bath|ห้องน้ำ)', line, re.IGNORECASE)
        area_match = re.search(r'([\d,.]+)\s*(sqm|sq\.?m|ตร\.?ม)', line, re.IGNORECASE)
        is_detail = bool(price_match or bed_match or bath_match or area_match)

        # Title/heading detection. A long un-headed line only starts a new
        # listing when it is not a price/room/area detail line, otherwise
        # "฿5,500,000 · 2 beds · 65 sqm" would split one listing in two.
        is_heading = line.startswith('#')
        is_long_text = 20 < len(line) < 200 and not line.startswith('http') and not is_detail
        if is_heading or is_long_text:
            if current_listing.get('title') and current_listing.get('price'):
                listings.append(current_listing)
            current_listing = {
                'title': line.lstrip('#').strip(),
                'type': listing_type,
                'url': '',
                'price_raw': '',
                'price': 0,
                'bedrooms': '',
                'bathrooms': '',
                'area_sqm': '',
                'location': '',
                'description': '',
            }

        if not current_listing.get('title'):
            continue

        if price_match and not current_listing.get('price'):
            current_listing['price_raw'] = price_match.group(1)
            current_listing['price'] = parse_price(price_match.group(1))
        if bed_match:
            current_listing['bedrooms'] = bed_match.group(1)
        if bath_match:
            current_listing['bathrooms'] = bath_match.group(1)
        if area_match:
            current_listing['area_sqm'] = area_match.group(1)

        # URL detection
        url_match = re.search(r'https?://\S+ddproperty\S+', line)
        if url_match:
            current_listing['url'] = url_match.group(0)
        elif (
            not is_detail
            and not is_heading
            and not line.startswith('http')
            and len(line) <= 20
            and not current_listing.get('location')
        ):
            # A short plain line inside a card is the area/district label.
            current_listing['location'] = line

    # Don't forget last listing
    if current_listing.get('title') and current_listing.get('price'):
        listings.append(current_listing)

    return listings


def save_listings(listings: list, output_dir: Path):
    """Save listings to CSV atomically (input dicts are not modified)."""
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    listings_file = output_dir / "property_listings.csv"
    fieldnames = [
        "scraped_at", "title", "type", "url", "price_raw", "price",
        "bedrooms", "bathrooms", "area_sqm", "location", "description"
    ]

    rows = []
    for listing in listings:
        row = {k: listing.get(k, "") for k in fieldnames}
        row["scraped_at"] = now
        rows.append(row)
    write_text_atomic(listings_file, render_csv(rows, fieldnames))

    print(f"  Saved {len(listings)} listings to {listings_file}")


HISTORY_FIELDS = ["date", "title", "type", "price", "bedrooms", "area_sqm", "location", "url"]


def append_history(listings: list, output_dir: Path):
    """Append to history for price tracking.

    New files carry a ``url`` column so price drops can be keyed by listing
    URL. An existing file keeps its original header so old rows stay aligned.
    """
    history_file = output_dir / "property_history.csv"
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    fieldnames = HISTORY_FIELDS
    file_exists = history_file.exists() and history_file.stat().st_size > 0
    if file_exists:
        with open(history_file, "r", newline="", encoding="utf-8") as f:
            header = next(csv.reader(f), None)
        if header:
            fieldnames = header

    rows = []
    for listing in listings:
        rows.append({
            "date": now,
            "title": listing.get("title", ""),
            "type": listing.get("type", ""),
            "price": listing.get("price", 0),
            "bedrooms": listing.get("bedrooms", ""),
            "area_sqm": listing.get("area_sqm", ""),
            "location": listing.get("location", ""),
            "url": canonical_listing_url(listing.get("url", "")),
        })

    # Rewrite old + new atomically: a killed run can never leave a torn row.
    existing = history_file.read_text(encoding="utf-8") if file_exists else ""
    if existing and not existing.endswith("\n"):
        existing += "\r\n"
    write_text_atomic(history_file, existing + render_csv(rows, fieldnames, header=not file_exists))

    print(f"  Appended {len(rows)} rows to {history_file}")


TRACKING_PARAMS = frozenset({"fbclid", "gclid", "dclid", "msclkid", "yclid", "ref", "ref_src", "igshid", "mc_cid", "mc_eid"})


def canonical_listing_url(url: str) -> str:
    """Stable key for one listing URL.

    Lower-cases scheme and host, drops the fragment, a trailing slash and
    tracking parameters (``utm_*``, ``fbclid``, ``gclid``...), and sorts the
    remaining query so the same listing seen via different links keeps one
    price history. Non-HTTP(S) or unparseable values are returned stripped.
    """
    value = (url or "").strip()
    try:
        parts = urlsplit(value)
    except ValueError:
        return value
    if parts.scheme.lower() not in ("http", "https") or not parts.netloc:
        return value
    query = sorted(
        (key, val)
        for key, val in parse_qsl(parts.query, keep_blank_values=True)
        if not key.lower().startswith("utm_") and key.lower() not in TRACKING_PARAMS
    )
    path = parts.path.rstrip("/") or "/"
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), path, urlencode(query), ""))


def _history_key(row: dict):
    url = canonical_listing_url(row.get("url") or "")
    if url:
        return ("url", url)
    title = (row.get("title") or "").strip()
    return ("title", title) if title else None


def detect_price_drops(current: list, history_file: Path, threshold_pct: float) -> list:
    """Detect listings whose price fell by at least ``threshold_pct``.

    History is keyed by listing URL when known, so two units with the same
    title do not collide; rows without a URL fall back to the title. Call this
    *before* appending the current run to history, otherwise the latest
    history price is the current price and no drop is ever found.
    """
    if not history_file.exists():
        return []

    historical = {}
    with open(history_file, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            key = _history_key(row)
            if key and row.get("price"):
                try:
                    historical[key] = float(row["price"])
                except (ValueError, TypeError):
                    pass

    drops = []
    for listing in current:
        current_price = listing.get("price", 0)
        key = _history_key(listing)
        old_price = historical.get(key) if key else None
        if old_price is None and key and key[0] == "url":
            # Rows written before the url column existed are keyed by title.
            old_price = historical.get(("title", (listing.get("title") or "").strip()))
        if old_price and old_price > 0 and current_price > 0:
            drop_pct = ((old_price - current_price) / old_price) * 100
            if drop_pct >= threshold_pct:
                drops.append({**listing, "price_drop_pct": round(drop_pct, 1), "old_price": old_price})

    return drops


def print_summary(listings: list, drops: list = None):
    """Print listing summary."""
    if not listings:
        print("  No listings found")
        return

    print(f"\n  Found {len(listings)} listings:")
    for listing in listings[:10]:
        price = listing.get("price", 0)
        price_str = f"฿{price:,.0f}" if price >= 1000 else listing.get("price_raw", "N/A")
        beds = f"{listing.get('bedrooms', '?')} bed" if listing.get('bedrooms') else ""
        area = f"{listing.get('area_sqm', '?')} sqm" if listing.get('area_sqm') else ""
        print(f"    {price_str:>15} | {beds:>8} | {area:>10} | {listing.get('title', '')[:40]}")

    if drops:
        print(f"\n  PRICE DROPS ({len(drops)}):")
        for drop in drops:
            print(f"    -{drop['price_drop_pct']}% | {drop.get('title', '')[:40]} | ฿{drop.get('old_price', 0):,.0f} → ฿{drop.get('price', 0):,.0f}")


PROPERTY_HOSTS = ("ddproperty.com", "propertyhub.in.th", "dotproperty.co.th")


def is_property_host(url: str) -> bool:
    """True when ``url``'s host is a known portal or one of its subdomains.

    A substring test accepted lookalike hosts and any URL that merely
    mentioned a portal in its path or query string.
    """
    try:
        host = (urlsplit(url).hostname or "").lower().rstrip(".")
    except ValueError:
        return False
    return any(host == h or host.endswith("." + h) for h in PROPERTY_HOSTS)


PRICE_HINT = re.compile(r'(\u0e3f[\d,]+|[\d,.]+\s*\u0e25\u0e49\u0e32\u0e19)')


def _search_fallback_listings(listing_type: str) -> list:
    """Build listings from search results when the direct page is empty."""
    search_query = f"ddproperty {listing_type.replace('_', ' ')} thailand"
    listings = []
    for sr in google_search(search_query, limit=20):
        sr_url = sr.get("url", "")
        if not is_property_host(sr_url):
            continue
        raw_title = sr.get("title", "")
        clean_title = _clean_property_title(raw_title, sr_url)
        if not clean_title:
            continue
        price_raw = ""
        price = 0
        price_match = PRICE_HINT.search(f"{raw_title} {sr.get('description', '')}")
        if price_match:
            price_raw = price_match.group(1)
            price = parse_price(price_raw)
        listings.append({
            "title": clean_title,
            "type": listing_type,
            "url": sr_url,
            "description": sr.get("description", ""),
            "price_raw": price_raw,
            "price": price,
            "bedrooms": "",
            "bathrooms": "",
            "area_sqm": "",
            "location": listing_type.split('_')[-1].title(),
        })
    return listings


def collect_type(listing_type: str, url: str) -> list:
    """Fetch one listing-type page, falling back to search when it is empty."""
    markdown = free_scrape_url(url)
    if markdown and len(markdown) >= 200:
        return extract_listings(markdown, listing_type)
    print("    Direct scrape failed/empty, using search fallback...")
    return _search_fallback_listings(listing_type)


def collect(types_to_scrape: dict, sleep=time.sleep) -> list:
    """Collect every listing type with a pause between types; one failing
    type is reported and skipped."""
    all_listings = []
    for index, (listing_type, url) in enumerate(types_to_scrape.items()):
        if index:
            sleep(TYPE_DELAY_SECONDS)
        print(f"\n  Scraping {listing_type}: {url}")
        try:
            listings = collect_type(listing_type, url)
        except Exception as e:
            print(f"    ERROR: {type(e).__name__}: {e}")
            continue
        print(f"    Extracted {len(listings)} listings")
        all_listings.extend(listings)
    return all_listings


def validate_drop_pct(value) -> float:
    """``--alert-drop-pct`` must be a finite percentage in (0, 100]."""
    pct = float(value)
    if not 0 < pct <= 100:
        raise ValueError("alert_drop_pct must be greater than 0 and at most 100")
    return pct


def persist(all_listings: list, output_dir: Path, alert_drop_pct: float) -> list:
    """Detect drops against prior history, then write snapshot and history."""
    alert_drop_pct = validate_drop_pct(alert_drop_pct)
    history_file = output_dir / "property_history.csv"
    drops = detect_price_drops(all_listings, history_file, alert_drop_pct)
    save_listings(all_listings, output_dir)
    append_history(all_listings, output_dir)
    print_summary(all_listings, drops)
    return drops


def _types_for(listing_type) -> dict:
    if listing_type and listing_type in DDPROPERTY_SEARCH:
        return {listing_type: DDPROPERTY_SEARCH[listing_type]}
    return dict(DDPROPERTY_SEARCH)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Scrape property listings via free httpx+BS4")
    parser.add_argument("--type", default=None, choices=list(DDPROPERTY_SEARCH.keys()),
                        help="Listing type (default: scrape ALL types)")
    # Accepted for backward compatibility only: one page per type is fetched.
    parser.add_argument("--max-pages", type=int, default=None, help=argparse.SUPPRESS)
    parser.add_argument("--alert-drop-pct", type=float, default=10.0,
                        help="Alert on price drops >= this %% (default: 10)")
    parser.add_argument("--output-dir", default=str(OUTPUT_DIR),
                        help="Output directory")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print the bounded plan without collection or writes")
    args = parser.parse_args(argv)
    try:
        validate_drop_pct(args.alert_drop_pct)
    except ValueError:
        parser.error("--alert-drop-pct must be greater than 0 and at most 100")

    output_dir = Path(args.output_dir)
    if output_dir.exists() and not output_dir.is_dir():
        parser.error(f"--output-dir is not a directory: {output_dir}")
    types_to_scrape = _types_for(args.type)

    if args.dry_run:
        print(json.dumps({
            "status": "dry-run",
            "types": list(types_to_scrape),
            "pages_per_type": 1,
            "network": "not-used",
            "writes": "not-used",
        }, ensure_ascii=False, indent=2))
        return 0

    _load_runtime_env()
    _require_live_dependencies()

    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Property Listing Scraper")
    print(f"  Types: {len(types_to_scrape)} | Pages per type: 1")

    all_listings = collect(types_to_scrape)
    print(f"\n  Total: {len(all_listings)} listings across {len(types_to_scrape)} categories")

    if all_listings:
        persist(all_listings, output_dir, args.alert_drop_pct)
    else:
        print("  No listings parsed (site structure may have changed)")

    print("\n  Done.")
    return 0


class PropertyListingScraper:
    """Wrapper class for scheduler compatibility.

    ``max_pages`` is accepted for scheduler compatibility and ignored: the
    runner fetches one page per listing type.
    """

    def __init__(self, type=None, max_pages=None, alert_drop_pct=10.0, output_dir=None, **kwargs):
        self.listing_type = type
        self.alert_drop_pct = validate_drop_pct(alert_drop_pct)
        self.output_dir = Path(output_dir) if output_dir else OUTPUT_DIR

    async def run(self, **kwargs):
        _load_runtime_env()
        _require_live_dependencies()
        print(f"[PropertyListingScraper] type={self.listing_type or 'all'}")
        all_listings = collect(_types_for(self.listing_type))
        if all_listings:
            persist(all_listings, self.output_dir, self.alert_drop_pct)
        return [{"source": "property_listings", "count": len(all_listings)}]


if __name__ == "__main__":
    raise SystemExit(main())
