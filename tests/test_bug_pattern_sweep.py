"""Regression tests for recurring cross-repo bug patterns."""

import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import scrape_property_listings as source  # noqa: E402
from property.ddproperty_scraper import _price_value, parse_next_data  # noqa: E402


def _next_data_html(price) -> str:
    payload = {
        "props": {"pageProps": {"pageData": {"data": {"listingsData": [
            {
                "listingData": {
                    "localizedTitle": "คอนโดอโศก",
                    "price": price,
                    "shortAddress": "กรุงเทพ อโศก",
                    "typeCode": "RENT",
                    "url": "https://www.ddproperty.com/property/example",
                },
                "segment": {"parameters": {"metaData": {"listingData": {}}}},
            }
        ]}}}}
    }
    return f'<script id="__NEXT_DATA__" type="application/json">{json.dumps(payload, ensure_ascii=False)}</script>'


class NonFinitePriceTests(unittest.TestCase):
    def test_price_value_rejects_nan_and_inf(self):
        for raw in ("nan", "NaN", "inf", "-inf", float("nan"), float("inf")):
            self.assertIsNone(_price_value(raw), raw)
        self.assertEqual(_price_value("25000"), 25000.0)

    def test_nan_price_does_not_pass_max_price_filter(self):
        self.assertEqual(parse_next_data(_next_data_html("NaN"), max_price=30000), [])
        self.assertEqual(parse_next_data(_next_data_html(float("nan")), max_price=30000), [])
        self.assertEqual(len(parse_next_data(_next_data_html(20000), max_price=30000)), 1)


class PropertyHostTests(unittest.TestCase):
    def test_exact_host_or_subdomain_only(self):
        self.assertTrue(source.is_property_host("https://www.ddproperty.com/en/property/x"))
        self.assertTrue(source.is_property_host("https://propertyhub.in.th/listings/1"))
        self.assertTrue(source.is_property_host("https://www.dotproperty.co.th/condo/1"))
        self.assertFalse(source.is_property_host("https://evil.example/?ref=ddproperty.com"))
        self.assertFalse(source.is_property_host("https://ddproperty.com.evil.example/x"))
        self.assertFalse(source.is_property_host("https://notpropertyhub.example/x"))
        self.assertFalse(source.is_property_host("not a url"))

    def test_search_fallback_skips_urls_that_only_mention_a_portal(self):
        results = [
            {"url": "https://spam.example/redirect?to=ddproperty.com", "title": "Condo ฿20,000 rent"},
            {"url": "https://www.ddproperty.com/property/1", "title": "Condo ฿20,000 rent"},
        ]
        with patch.object(source, "google_search", return_value=results):
            listings = source._search_fallback_listings("condo_rent")
        self.assertEqual([item["url"] for item in listings], ["https://www.ddproperty.com/property/1"])


if __name__ == "__main__":
    unittest.main()
