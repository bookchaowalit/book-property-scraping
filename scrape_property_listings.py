#!/usr/bin/env python3
"""
Scrape property listings from DDproperty via free httpx+BS4.
Tracks new listings, price changes, and investment opportunities.

Outputs:
    - domains/money/assets/book-real-estate/data/property_listings.csv (latest)
    - domains/money/assets/book-real-estate/data/property_history.csv (appended)
    - Console alerts for price drops >10%

Usage:
    python3 domains/product/engineering/book-dev/book-scraping/scripts/scrape_property_listings.py
    python3 domains/product/engineering/book-dev/book-scraping/scripts/scrape_property_listings.py --type condo --max-price 5000000
    python3 domains/product/engineering/book-dev/book-scraping/scripts/scrape_property_listings.py --area bangkok --bedrooms 1,2
    python3 domains/product/engineering/book-dev/book-scraping/scripts/scrape_property_listings.py --alert-drop-pct 10
"""

import argparse
import csv
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

try:
    from dotenv import load_dotenv
    # Load .env from project root (5 levels up from this script)
    _root = Path(__file__).resolve().parents[4]
    load_dotenv(_root / ".env")
except ImportError:
    pass  # dotenv not required, but .env won't be auto-loaded

try:
    import httpx
except ImportError:
    print("ERROR: httpx required. Install: pip install httpx")
    sys.exit(1)

try:
    from bs4 import BeautifulSoup
except ImportError:
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "beautifulsoup4", "-q"])
    from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[4]  # solo-empire/
OUTPUT_DIR = ROOT / "domains" / "book-real-estate" / "data"

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
DEFAULT_MAX_PAGES = 3


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
    except:
        pass
    return href


def _bing_search(query: str, limit: int = 20) -> list:
    """Fallback search via Bing when Brave is rate-limited."""
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

        # Price detection
        price_match = re.search(r'(฿[\d,]+|[\d,.]+\s*ล้าน)', line)
        if price_match and current_listing.get('title'):
            current_listing['price_raw'] = price_match.group(1)
            current_listing['price'] = parse_price(price_match.group(1))

        # Title/heading detection
        if line.startswith('#') or (len(line) > 20 and len(line) < 200 and not line.startswith('http')):
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

        # Bedroom/bathroom detection
        bed_match = re.search(r'(\d+)\s*(bed|ห้องนอน)', line, re.IGNORECASE)
        if bed_match:
            current_listing['bedrooms'] = bed_match.group(1)

        bath_match = re.search(r'(\d+)\s*(bath|ห้องน้ำ)', line, re.IGNORECASE)
        if bath_match:
            current_listing['bathrooms'] = bath_match.group(1)

        # Area detection
        area_match = re.search(r'([\d,.]+)\s*(sqm|sq\.?m|ตร\.?ม)', line, re.IGNORECASE)
        if area_match:
            current_listing['area_sqm'] = area_match.group(1)

        # URL detection
        url_match = re.search(r'https?://\S+ddproperty\S+', line)
        if url_match:
            current_listing['url'] = url_match.group(0)

    # Don't forget last listing
    if current_listing.get('title') and current_listing.get('price'):
        listings.append(current_listing)

    return listings


def save_listings(listings: list, output_dir: Path):
    """Save listings to CSV."""
    output_dir.mkdir(parents=True, exist_ok=True)
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    listings_file = output_dir / "property_listings.csv"
    fieldnames = [
        "scraped_at", "title", "type", "url", "price_raw", "price",
        "bedrooms", "bathrooms", "area_sqm", "location", "description"
    ]

    with open(listings_file, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for listing in listings:
            listing["scraped_at"] = now
            writer.writerow({k: listing.get(k, "") for k in fieldnames})

    print(f"  Saved {len(listings)} listings to {listings_file}")


def append_history(listings: list, output_dir: Path):
    """Append to history for price tracking."""
    history_file = output_dir / "property_history.csv"
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    file_exists = history_file.exists()

    fieldnames = ["date", "title", "type", "price", "bedrooms", "area_sqm", "location"]
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
        })

    with open(history_file, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        if not file_exists:
            writer.writeheader()
        writer.writerows(rows)

    print(f"  Appended {len(rows)} rows to {history_file}")


def detect_price_drops(current: list, history_file: Path, threshold_pct: float) -> list:
    """Detect listings with significant price drops."""
    if not history_file.exists():
        return []

    # Load historical prices
    historical = {}
    with open(history_file, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            key = row.get("title", "")
            if key and row.get("price"):
                try:
                    historical[key] = float(row["price"])
                except (ValueError, TypeError):
                    pass

    drops = []
    for listing in current:
        title = listing.get("title", "")
        current_price = listing.get("price", 0)
        if title in historical and historical[title] > 0 and current_price > 0:
            old_price = historical[title]
            drop_pct = ((old_price - current_price) / old_price) * 100
            if drop_pct >= threshold_pct:
                listing["price_drop_pct"] = round(drop_pct, 1)
                listing["old_price"] = old_price
                drops.append(listing)

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


def main():
    parser = argparse.ArgumentParser(description="Scrape property listings via free httpx+BS4")
    parser.add_argument("--type", default=None, choices=list(DDPROPERTY_SEARCH.keys()),
                        help=f"Listing type (default: scrape ALL types)")
    parser.add_argument("--max-pages", type=int, default=DEFAULT_MAX_PAGES,
                        help=f"Max pages to scrape per type (default: {DEFAULT_MAX_PAGES})")
    parser.add_argument("--alert-drop-pct", type=float, default=10.0,
                        help="Alert on price drops >= this %% (default: 10)")
    parser.add_argument("--output-dir", default=str(OUTPUT_DIR),
                        help="Output directory")
    args = parser.parse_args()

    output_dir = Path(args.output_dir)

    # Determine which types to scrape
    if args.type:
        types_to_scrape = {args.type: DDPROPERTY_SEARCH[args.type]}
    else:
        types_to_scrape = DDPROPERTY_SEARCH

    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Property Listing Scraper")
    print(f"  Types: {len(types_to_scrape)} | Max pages: {args.max_pages}")

    all_listings = []

    for listing_type, url in types_to_scrape.items():
        print(f"\n  Scraping {listing_type}: {url}")
        try:
            markdown = free_scrape_url(url)

            if not markdown or len(markdown) < 200:
                print(f"    Direct scrape failed/empty, using Brave search...")
                search_query = f"ddproperty {listing_type.replace('_', ' ')} thailand"
                search_results = google_search(search_query, limit=20)
                listings = []
                for sr in search_results:
                    sr_url = sr.get("url", "")
                    # Only keep property site URLs
                    if 'ddproperty.com' in sr_url or 'propertyhub' in sr_url or 'dotproperty' in sr_url:
                        # Clean title from breadcrumb garbage
                        raw_title = sr.get("title", "")
                        clean_title = _clean_property_title(raw_title, sr_url)
                        if not clean_title:
                            continue
                        # Extract price from title + description
                        combined_text = f"{raw_title} {sr.get('description', '')}"
                        price_raw = ""
                        price = 0
                        price_match = re.search(r'(\u0e3f[\d,]+|[\d,.]+\s*\u0e25\u0e49\u0e32\u0e19)', combined_text)
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
            else:
                listings = extract_listings(markdown, listing_type)

            print(f"    Extracted {len(listings)} listings")
            all_listings.extend(listings)

        except Exception as e:
            print(f"    ERROR: {e}")
            continue

    print(f"\n  Total: {len(all_listings)} listings across {len(types_to_scrape)} categories")

    # Save
    if all_listings:
        save_listings(all_listings, output_dir)
        append_history(all_listings, output_dir)

        # Detect price drops
        history_file = output_dir / "property_history.csv"
        drops = detect_price_drops(all_listings, history_file, args.alert_drop_pct)
        print_summary(all_listings, drops)
    else:
        print("  No listings parsed (site structure may have changed)")

    print("\n  Done.")


class PropertyListingScraper:
    """Wrapper class for scheduler compatibility."""
    def __init__(self, type=None, max_pages=None, alert_drop_pct=10.0, **kwargs):
        self.listing_type = type
        self.max_pages = max_pages or 3
        self.alert_drop_pct = alert_drop_pct

    async def run(self, **kwargs):
        print(f"[PropertyListingScraper] type={self.listing_type} | max_pages={self.max_pages}")
        if self.listing_type and self.listing_type in DDPROPERTY_SEARCH:
            types_to_scrape = {self.listing_type: DDPROPERTY_SEARCH[self.listing_type]}
        else:
            types_to_scrape = DDPROPERTY_SEARCH
        all_listings = []
        for listing_type, url in types_to_scrape.items():
            try:
                markdown = free_scrape_url(url)
                if markdown and len(markdown) > 200:
                    listings = extract_listings(markdown, listing_type)
                else:
                    search_query = f"ddproperty {listing_type.replace('_', ' ')} thailand"
                    search_results = google_search(search_query, limit=20)
                    listings = []
                    for sr in search_results:
                        sr_url = sr.get('url', '')
                        if 'ddproperty.com' in sr_url or 'propertyhub' in sr_url or 'dotproperty' in sr_url:
                            raw_title = sr.get('title', '')
                            clean_title = _clean_property_title(raw_title, sr_url)
                            if clean_title:
                                combined_text = f"{raw_title} {sr.get('description', '')}"
                                price_raw = ''
                                price = 0
                                price_match = re.search(r'(\u0e3f[\d,]+|[\d,.]+\s*\u0e25\u0e49\u0e32\u0e19)', combined_text)
                                if price_match:
                                    price_raw = price_match.group(1)
                                    price = parse_price(price_raw)
                                listings.append({'title': clean_title, 'type': listing_type, 'url': sr_url,
                                                 'description': sr.get('description', ''), 'price_raw': price_raw,
                                                 'price': price, 'bedrooms': '', 'bathrooms': '', 'area_sqm': '',
                                                 'location': listing_type.split('_')[-1].title()})
                all_listings.extend(listings)
            except Exception as e:
                print(f"  Error scraping {listing_type}: {e}")
        if all_listings:
            output_dir = OUTPUT_DIR
            save_listings(all_listings, output_dir)
            append_history(all_listings, output_dir)
            history_file = output_dir / 'property_history.csv'
            detect_price_drops(all_listings, history_file, self.alert_drop_pct)
            print_summary(all_listings)
        return [{"source": "property_listings", "count": len(all_listings)}]


if __name__ == "__main__":
    main()
