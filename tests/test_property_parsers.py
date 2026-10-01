"""Offline parser tests for the generic property listing runner."""

import base64
import csv
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import scrape_property_listings as source
from property.ddproperty_scraper import DDPropertyScraper


class ParsePriceTests(unittest.TestCase):
    def test_thai_and_symbol_formats(self):
        self.assertEqual(source.parse_price("฿5,000,000"), 5_000_000)
        self.assertEqual(source.parse_price("5.5 ล้านบาท"), 5_500_000)
        self.assertEqual(source.parse_price("฿25,000/month"), 25_000)
        self.assertEqual(source.parse_price(""), 0.0)
        self.assertEqual(source.parse_price("contact agent"), 0.0)

    def test_separator_only_text_does_not_crash(self):
        # "... ล้านบาท" used to raise ValueError and drop the whole listing type.
        self.assertEqual(source.parse_price("ราคาเริ่มต้น... ล้านบาท"), 0.0)
        self.assertEqual(source.parse_price("ราคา . ล้าน"), 0.0)

    def test_grouping_and_decimal_separators(self):
        self.assertEqual(source.parse_price("1.234.567 บาท"), 1_234_567)
        self.assertEqual(source.parse_price("1,5 ล้าน"), 1_500_000)
        self.assertEqual(source.parse_price("๕.๕ ล้าน"), 5_500_000)
        self.assertEqual(source.parse_price("25,000 - 30,000 บาท"), 25_000)

    def test_non_finite_max_price_is_rejected(self):
        for bound in ("nan", "inf"):
            with self.assertRaises(ValueError):
                DDPropertyScraper(max_price=bound)


class ExtractListingsTests(unittest.TestCase):
    def test_long_detail_line_does_not_split_a_listing(self):
        markdown = "\n".join(
            [
                "# Rhythm Sukhumvit 42 high floor",
                "฿5,500,000 · 2 beds · 2 baths · 65 sqm · Phra Khanong",
                "https://www.ddproperty.com/en/property/rhythm-42-111",
                "# Life Asoke corner unit with view",
                "3.2 ล้าน 1 ห้องนอน 35 ตร.ม",
            ]
        )
        listings = source.extract_listings(markdown, "condo_sale_bkk")
        self.assertEqual([item["title"] for item in listings], [
            "Rhythm Sukhumvit 42 high floor",
            "Life Asoke corner unit with view",
        ])
        first, second = listings
        self.assertEqual(first["price"], 5_500_000)
        self.assertEqual(first["bedrooms"], "2")
        self.assertEqual(first["bathrooms"], "2")
        self.assertEqual(first["area_sqm"], "65")
        self.assertEqual(first["url"], "https://www.ddproperty.com/en/property/rhythm-42-111")
        self.assertEqual(second["price"], 3_200_000)
        self.assertEqual(second["bedrooms"], "1")

    def test_listing_without_price_is_dropped_and_leading_noise_ignored(self):
        markdown = "฿99 stray price before any title\n# Title only no price\n2 beds"
        self.assertEqual(source.extract_listings(markdown, "condo_sale_bkk"), [])


class HelperTests(unittest.TestCase):
    def test_clean_property_title_strips_breadcrumbs(self):
        self.assertEqual(
            source._clean_property_title("DDProperty › Condo for Sale › Bangkok › Noble Ploenchit"),
            "Noble Ploenchit",
        )
        self.assertEqual(
            source._clean_property_title("ddproperty.com - Park 24"),
            "Park 24",
        )

    def test_decode_bing_redirect(self):
        target = "https://www.ddproperty.com/en/property/x-1"
        encoded = base64.b64encode(target.encode()).decode().rstrip("=")
        href = f"https://www.bing.com/ck/a?!&&p=abc&u=a1{encoded}&ntb=1"
        self.assertEqual(source._decode_bing_redirect(href), target)
        self.assertEqual(source._decode_bing_redirect("https://example.com/x"), "https://example.com/x")

    def test_invalid_urls_rejected(self):
        self.assertFalse(source._is_valid_url("/relative"))
        self.assertFalse(source._is_valid_url("https://consent.google.com/x"))
        self.assertTrue(source._is_valid_url("https://www.ddproperty.com/x"))

    def test_price_drop_detection(self):
        with tempfile.TemporaryDirectory() as directory:
            history = Path(directory) / "property_history.csv"
            with history.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=["date", "title", "price"])
                writer.writeheader()
                writer.writerow({"date": "2026-09-01", "title": "Unit A", "price": "5000000"})
                writer.writerow({"date": "2026-09-01", "title": "Unit B", "price": "not-a-number"})
            current = [{"title": "Unit A", "price": 4_000_000}, {"title": "Unit B", "price": 1}]
            drops = source.detect_price_drops(current, history, 10)
        self.assertEqual(len(drops), 1)
        self.assertEqual(drops[0]["price_drop_pct"], 20.0)

    def test_output_paths_stay_inside_the_repository(self):
        self.assertEqual(source.ROOT, ROOT)
        self.assertEqual(source.OUTPUT_DIR, ROOT / "data" / "exported")


class FallbackSearchTests(unittest.TestCase):
    def test_fallback_reads_price_from_search_description(self):
        results = [
            {
                "title": "Condo for rent Asok",
                "url": "https://www.ddproperty.com/en/property/asok-1",
                "description": "1 bed ฿18,000/month near BTS",
            },
            {"title": "Off-site", "url": "https://example.com/property/2", "description": "฿1"},
        ]
        with patch.object(source, "google_search", return_value=results):
            listings = DDPropertyScraper(max_price=30000)._fallback_search()
        self.assertEqual(len(listings), 1)
        self.assertEqual(listings[0]["price"], 18000)


if __name__ == "__main__":
    unittest.main()
