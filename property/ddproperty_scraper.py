#!/usr/bin/env python3
"""
DDproperty scraper — uses httpx+BS4 engine.
Scrapes condo/house listings from ddproperty.com.

MCP Tool: get_property_listings
Data: title, price, area, bedrooms, location, URL
"""

import asyncio
import logging
import re
import sys
from pathlib import Path
from typing import List, Optional

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from adapters.outbound.engines.httpx_bs4 import HttpxBS4Scraper
from core.models import PropertyListing

logger = logging.getLogger(__name__)

SEARCH_URLS = {
    "condo_rent_bangkok": "https://www.ddproperty.com/condo-for-rent/bangkok",
    "condo_sale_bangkok": "https://www.ddproperty.com/condo-for-sale/bangkok",
    "house_rent_bangkok": "https://www.ddproperty.com/house-for-rent/bangkok",
    "land_sale": "https://www.ddproperty.com/land-for-sale",
}


class DDPropertyScraper(HttpxBS4Scraper):
    """Scrape property listings from DDproperty."""

    def __init__(self, **kwargs):
        super().__init__(
            name="ddproperty",
            rate_limit=kwargs.get("rate_limit", 3.0),
            max_retries=3,
            timeout=30.0,
        )

    def build_search_url(self, listing_type: str, page: int = 1) -> str:
        base = SEARCH_URLS.get(listing_type, SEARCH_URLS["condo_rent_bangkok"])
        return f"{base}?page={page}"

    def parse_listing_card(self, card) -> Optional[PropertyListing]:
        """Parse a single property listing card."""
        try:
            title_el = card.select_one("a[data-tracking='listing-title']") or card.select_one("h2 a")
            title = title_el.get_text(strip=True) if title_el else ""

            price_el = card.select_one("span[data-tracking='listing-price']") or card.select_one(".price")
            price_text = price_el.get_text(strip=True) if price_el else ""

            location_el = card.select_one("span[data-tracking='listing-location']") or card.select_one(".location")
            location = location_el.get_text(strip=True) if location_el else ""

            # Parse price from Thai text (e.g., "฿15,000/เดือน" or "฿5,000,000")
            price = None
            if price_text:
                nums = re.sub(r"[^\d]", "", price_text)
                if nums:
                    price = float(nums)

            # Parse bedrooms/bathrooms from features
            beds_el = card.select_one("span[data-feature='bedrooms']")
            bedrooms = int(beds_el.get_text(strip=True)) if beds_el else 0

            area_el = card.select_one("span[data-feature='area']")
            area_text = area_el.get_text(strip=True) if area_el else ""
            area_sqm = None
            if area_text:
                nums = re.sub(r"[^\d.]", "", area_text)
                if nums:
                    area_sqm = float(nums)

            link = ""
            if title_el and title_el.get("href"):
                href = title_el["href"]
                link = f"https://www.ddproperty.com{href}" if href.startswith("/") else href

            if not title:
                return None

            return PropertyListing(
                title=title,
                url=link,
                price=price,
                location=location,
                bedrooms=bedrooms,
                area_sqm=area_sqm,
                source="ddproperty",
                raw_data={"price_text": price_text, "area_text": area_text},
            )
        except Exception as e:
            logger.error(f"Error parsing listing: {e}")
            return None

    async def scrape_listing_type(self, listing_type: str, max_pages: int = 3):
        """Scrape all pages for a listing type."""
        logger.info(f"Scraping DDproperty: {listing_type}")

        for page in range(1, max_pages + 1):
            url = self.build_search_url(listing_type, page)
            soup = await self.fetch_and_parse(url)
            if not soup:
                break

            cards = soup.select("div[data-tracking='listing-card']") or soup.select("article.listing-card")
            if not cards:
                logger.info(f"  No more results on page {page}")
                break

            for card in cards:
                listing = self.parse_listing_card(card)
                if listing:
                    self.add_result(listing.__dict__)

            logger.info(f"  Page {page}: {len(cards)} listings found")

    async def run(self, listing_types: List[str] = None, max_pages: int = 3):
        """Run scraper for all listing types."""
        listing_types = listing_types or ["condo_rent_bangkok"]

        for lt in listing_types:
            await self.scrape_listing_type(lt, max_pages)

        self.print_stats()
        self.export_csv("ddproperty_listings.csv")
        self.export_json("ddproperty_listings.json")
        return self.results


async def main():
    scraper = DDPropertyScraper()
    results = await scraper.run()
    print(f"\nTotal properties scraped: {len(results)}")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
