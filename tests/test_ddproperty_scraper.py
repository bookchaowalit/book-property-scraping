import asyncio
import csv
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from property.ddproperty_scraper import DDPropertyScraper, _fallback_price, parse_next_data


FIXTURE = Path(__file__).parent / "fixtures" / "ddproperty_condo_rent.md"
NEXT_DATA_FIXTURE = Path(__file__).parent / "fixtures" / "ddproperty_next_data.html"


class DDPropertyScraperTests(unittest.TestCase):
    def test_fallback_price_ignores_year_without_price_hint(self):
        self.assertIsNone(_fallback_price("Condos for Rent in Bangkok, Aug 2026"))
        self.assertEqual(_fallback_price("Condo rent ฿25,000 per month"), 25000)

    def test_parse_markdown_filters_by_max_price(self):
        listings = DDPropertyScraper.parse_markdown(FIXTURE.read_text(encoding="utf-8"))

        self.assertEqual(len(listings), 1)
        self.assertEqual(listings[0]["price"], 25000)
        self.assertIn("phrom-phong", listings[0]["url"])
        self.assertEqual(listings[0]["listing_type"], "condo_rent_bkk")

    def test_run_writes_dedicated_snapshot(self):
        markdown = FIXTURE.read_text(encoding="utf-8")
        with tempfile.TemporaryDirectory() as temp_dir:
            scraper = DDPropertyScraper(output_dir=temp_dir)
            with patch("property.ddproperty_scraper.source.free_scrape_url", return_value=markdown):
                result = asyncio.run(scraper.run())

            self.assertEqual(result[0]["source"], "ddproperty_condos")
            self.assertEqual(result[0]["count"], 1)
            snapshot = Path(temp_dir) / "ddproperty_condos.csv"
            self.assertTrue(snapshot.exists())
            with snapshot.open(newline="", encoding="utf-8") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["price"], "25000.0")

    def test_parse_next_data_keeps_bangkok_rent_under_max_price(self):
        listings = parse_next_data(
            NEXT_DATA_FIXTURE.read_text(encoding="utf-8"),
            max_price=30000,
            bangkok_only=True,
        )

        self.assertEqual(len(listings), 1)
        self.assertEqual(listings[0]["price"], 20000)
        self.assertIn("กรุงเทพ", listings[0]["location"])
        self.assertIn("q-asoke", listings[0]["url"])


if __name__ == "__main__":
    unittest.main()

