"""Dedicated DDproperty condo-rental adapter.

The English `/condo-for-rent/bangkok` path redirects to the nationwide sale
index. Collection uses the public Thai condo-rent search page and parses
`__NEXT_DATA__` listing cards. Markdown parsing remains for fixtures.
"""

from __future__ import annotations

import csv
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urldefrag, urlsplit, urlunsplit

import httpx
from bs4 import BeautifulSoup

try:
    from scripts import scrape_property_listings as source
except ImportError:  # domain repository checkout
    import scrape_property_listings as source


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT_DIR = ROOT / "data" / "exported"
SOURCE_URL = "https://www.ddproperty.com/เช่าคอนโด"
BANGKOK_MARKERS = ("กรุงเทพ", "bangkok")
FIELDNAMES = [
    "scraped_at",
    "title",
    "price",
    "location",
    "bedrooms",
    "bathrooms",
    "area_sqm",
    "url",
    "listing_type",
]


def _canonical_url(value: str) -> str:
    """Remove fragments and tracking query parameters for stable deduplication."""

    value = urldefrag((value or "").strip())[0]
    if not value:
        return ""
    parsed = urlsplit(value)
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path.rstrip("/"), "", ""))


def _price_value(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return source.parse_price(str(value))


def _fallback_price(text: str) -> float | None:
    """Parse only explicit rental-price hints, not years or listing IDs."""

    patterns = (
        r"(?:฿|THB)\s*([\d,.]+)",
        r"([\d,.]+)\s*(?:บาท|baht|ล้าน)",
        r"([\d,.]+)\s*(?:/\s*(?:month|mo|เดือน)|per\s*month)",
    )
    for pattern in patterns:
        price_hint = re.search(pattern, text, flags=re.IGNORECASE)
        if price_hint:
            price = source.parse_price(price_hint.group(0))
            return price if price > 0 else None
    return None


def _normalise_listing(listing: dict[str, Any], listing_type: str) -> dict[str, Any]:
    normalised = dict(listing)
    normalised["listing_type"] = listing_type
    normalised["url"] = _canonical_url(str(normalised.get("url") or SOURCE_URL))
    return normalised


def _dedupe_and_filter(
    listings: list[dict[str, Any]],
    listing_type: str,
    max_price: float | None,
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw_listing in listings:
        listing = _normalise_listing(raw_listing, listing_type)
        price = _price_value(listing.get("price"))
        if max_price and price is not None and price > max_price:
            continue
        key = listing["url"] or re.sub(r"\s+", " ", str(listing.get("title") or "")).strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        result.append(listing)
    return result


def _is_bangkok(text: str) -> bool:
    lowered = text.casefold()
    return any(marker.casefold() in lowered for marker in BANGKOK_MARKERS)


def _listing_price(listing_data: dict[str, Any], meta: dict[str, Any]) -> float | None:
    price = listing_data.get("price")
    if isinstance(price, dict) and price.get("value") not in (None, ""):
        return _price_value(price.get("value"))
    if isinstance(price, (int, float, str)) and str(price).strip():
        return _price_value(price)
    return _price_value(meta.get("price"))


def parse_next_data(
    html: str,
    listing_type: str = "condo_rent_bkk",
    max_price: float | None = 30000,
    bangkok_only: bool = True,
) -> list[dict[str, Any]]:
    """Parse priced rental cards from the public search-page `__NEXT_DATA__` blob."""

    if not html or "__NEXT_DATA__" not in html:
        return []
    soup = BeautifulSoup(html, "html.parser")
    node = soup.find("script", id="__NEXT_DATA__")
    if node is None or not node.string:
        return []
    try:
        payload = json.loads(node.string)
    except json.JSONDecodeError:
        return []
    raw_listings = (
        payload.get("props", {})
        .get("pageProps", {})
        .get("pageData", {})
        .get("data", {})
        .get("listingsData")
        or []
    )
    parsed: list[dict[str, Any]] = []
    for item in raw_listings:
        if not isinstance(item, dict):
            continue
        listing_data = item.get("listingData") or {}
        meta = (
            ((item.get("segment") or {}).get("parameters") or {}).get("metaData") or {}
        ).get("listingData") or {}
        if not isinstance(listing_data, dict) or not isinstance(meta, dict):
            continue
        type_code = str(listing_data.get("typeCode") or (listing_data.get("property") or {}).get("typeCode") or "")
        if type_code and type_code.upper() not in {"RENT", "N"}:
            continue
        location = " ".join(
            str(part or "")
            for part in (
                listing_data.get("shortAddress"),
                meta.get("regionName"),
                meta.get("districtName"),
                meta.get("areaName"),
            )
        ).strip()
        if bangkok_only and not _is_bangkok(location + " " + str(listing_data.get("localizedTitle") or "")):
            continue
        price = _listing_price(listing_data, meta)
        if price is None or price <= 0:
            continue
        url = str(listing_data.get("url") or "")
        parsed.append(
            {
                "title": str(listing_data.get("localizedTitle") or meta.get("listingTitle") or "").strip(),
                "price": price,
                "location": location or "Bangkok",
                "bedrooms": meta.get("bedroom"),
                "bathrooms": meta.get("bathroom"),
                "area_sqm": meta.get("floorArea"),
                "url": url,
            }
        )
    return _dedupe_and_filter(parsed, listing_type, max_price)


def fetch_search_html(url: str = SOURCE_URL) -> str:
    response = httpx.get(
        url,
        headers=source.HEADERS,
        timeout=30,
        follow_redirects=True,
    )
    response.raise_for_status()
    return response.text


class DDPropertyScraper:
    """Scrape Bangkok condo rentals from DDproperty with a bounded fallback."""

    def __init__(
        self,
        type: str = "condo",
        max_pages: int = 5,
        max_price: float | None = 30000,
        output_dir: str | Path | None = None,
        **_: Any,
    ) -> None:
        self.listing_type = "condo_rent_bkk" if type in {"condo", "condo_rent_bkk"} else type
        self.max_pages = max(1, int(max_pages or 1))
        self.max_price = float(max_price) if max_price not in (None, "") else None
        self.output_dir = Path(output_dir) if output_dir else DEFAULT_OUTPUT_DIR

    @staticmethod
    def parse_markdown(
        markdown: str,
        listing_type: str = "condo_rent_bkk",
        max_price: float | None = 30000,
    ) -> list[dict[str, Any]]:
        """Parse and filter source markdown without performing network I/O."""

        if not markdown or len(markdown.strip()) < 20:
            return []
        parsed = source.extract_listings(markdown, listing_type)
        return _dedupe_and_filter(parsed, listing_type, max_price)

    def _fallback_search(self) -> list[dict[str, Any]]:
        query = "site:ddproperty.com condo for rent Bangkok DDproperty"
        results = source.google_search(query, limit=self.max_pages * 10)
        listings: list[dict[str, Any]] = []
        for result in results:
            url = str(result.get("url") or "")
            if "ddproperty.com" not in url or "/property/" not in url:
                continue
            text = f"{result.get('title', '')} {result.get('snippet', '')}"
            price = _fallback_price(text)
            if price is None:
                continue
            listings.append(
                {
                    "title": source._clean_property_title(str(result.get("title") or ""), url),
                    "price": price,
                    "location": "Bangkok",
                    "bedrooms": None,
                    "bathrooms": None,
                    "area_sqm": None,
                    "url": url,
                }
            )
        return _dedupe_and_filter(listings, self.listing_type, self.max_price)

    def _collect(self) -> list[dict[str, Any]]:
        try:
            html = fetch_search_html(SOURCE_URL)
        except (httpx.HTTPError, OSError):
            html = ""
        listings = parse_next_data(html, self.listing_type, self.max_price, bangkok_only=True)
        if listings:
            return listings
        markdown = source.free_scrape_url(SOURCE_URL)
        listings = self.parse_markdown(markdown, self.listing_type, self.max_price)
        return listings or self._fallback_search()

    def _write_snapshot(self, listings: list[dict[str, Any]], scraped_at: str) -> Path:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        snapshot_path = self.output_dir / "ddproperty_condos.csv"
        with snapshot_path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=FIELDNAMES, extrasaction="ignore")
            writer.writeheader()
            for listing in listings:
                row = {field: listing.get(field, "") for field in FIELDNAMES}
                row["scraped_at"] = scraped_at
                writer.writerow(row)
        return snapshot_path

    async def run(self, **_: Any) -> list[dict[str, Any]]:
        listings = self._collect()
        scraped_at = datetime.now(timezone.utc).isoformat()
        snapshot_path = self._write_snapshot(listings, scraped_at)
        print(f"[ddproperty_condos] {len(listings)} listings -> {snapshot_path}")
        return [{"source": "ddproperty_condos", "count": len(listings), "output": str(snapshot_path)}]
