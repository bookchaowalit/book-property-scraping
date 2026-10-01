"""Offline tests for the shared collect/persist flow of the generic runner."""

import asyncio
import csv
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import scrape_property_listings as source  # noqa: E402

FIXTURE = Path(__file__).parent / "fixtures" / "ddproperty_condo_rent.md"


class ExtractLocationTests(unittest.TestCase):
    def test_short_label_line_becomes_location(self):
        listings = source.extract_listings(FIXTURE.read_text(encoding="utf-8"), "condo_rent_bkk")
        self.assertEqual([item["location"] for item in listings], ["Bangkok", "Bangkok"])


class CollectTests(unittest.TestCase):
    def test_direct_page_then_search_fallback_and_error_isolation(self):
        markdown = FIXTURE.read_text(encoding="utf-8")
        pages = {"u1": markdown, "u2": "", "u3": RuntimeError("boom")}

        def fake_fetch(url):
            value = pages[url]
            if isinstance(value, Exception):
                raise value
            return value

        search = [{"title": "Unit X", "url": "https://www.ddproperty.com/en/property/x-1", "description": "฿9,000"}]
        sleeps = []
        with patch.object(source, "free_scrape_url", side_effect=fake_fetch), \
                patch.object(source, "google_search", return_value=search) as google:
            rows = source.collect({"condo_rent_bkk": "u1", "house_sale_pattaya": "u2", "land_sale_bkk": "u3"},
                                  sleep=sleeps.append)
        self.assertEqual(sleeps, [source.TYPE_DELAY_SECONDS] * 2)
        self.assertEqual(google.call_count, 1)
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[-1]["type"], "house_sale_pattaya")
        self.assertEqual(rows[-1]["price"], 9000.0)
        self.assertEqual(rows[-1]["location"], "Pattaya")


class PersistTests(unittest.TestCase):
    def test_drop_is_detected_against_prior_run_not_current(self):
        unit = {"title": "Same title", "url": "https://www.ddproperty.com/p/1", "type": "t", "price": 5_000_000}
        other = {"title": "Same title", "url": "https://www.ddproperty.com/p/2", "type": "t", "price": 3_000_000}
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory)
            self.assertEqual(source.persist([unit, other], out, 10), [])
            cheaper = {**unit, "price": 4_000_000}
            drops = source.persist([cheaper, other], out, 10)
            # Keyed by URL: the same-title unit at 3M is not compared with 5M.
            self.assertEqual([(d["url"], d["price_drop_pct"]) for d in drops], [(unit["url"], 20.0)])
            self.assertNotIn("price_drop_pct", cheaper)  # inputs are not mutated
            with (out / "property_history.csv").open(newline="", encoding="utf-8") as handle:
                history = list(csv.DictReader(handle))
            self.assertEqual(len(history), 4)
            self.assertEqual(history[0]["url"], unit["url"])

    def test_legacy_history_without_url_column_still_matches_by_title(self):
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory)
            history = out / "property_history.csv"
            with history.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=["date", "title", "type", "price"])
                writer.writeheader()
                writer.writerow({"date": "2026-09-01", "title": "Unit A", "type": "t", "price": "1000000"})
            listing = {"title": "Unit A", "url": "https://www.ddproperty.com/p/a", "price": 800_000}
            drops = source.persist([listing], out, 10)
            self.assertEqual(drops[0]["price_drop_pct"], 20.0)
            with history.open(newline="", encoding="utf-8") as handle:
                header = next(csv.reader(handle))
            self.assertEqual(header, ["date", "title", "type", "price"])

    def test_save_listings_does_not_mutate_input(self):
        listing = {"title": "A", "price": 1}
        with tempfile.TemporaryDirectory() as directory:
            source.save_listings([listing], Path(directory))
        self.assertNotIn("scraped_at", listing)


class SchedulerWrapperTests(unittest.TestCase):
    def test_wrapper_uses_shared_flow_and_ignores_max_pages(self):
        with tempfile.TemporaryDirectory() as directory:
            scraper = source.PropertyListingScraper(type="condo_rent_bkk", max_pages=5, output_dir=directory)
            with patch.object(source, "free_scrape_url", return_value=FIXTURE.read_text(encoding="utf-8")):
                result = asyncio.run(scraper.run())
            self.assertEqual(result, [{"source": "property_listings", "count": 2}])
            self.assertTrue((Path(directory) / "property_listings.csv").exists())


if __name__ == "__main__":
    unittest.main()
