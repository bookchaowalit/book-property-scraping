"""Atomic snapshot/history writes, canonical history keys and CLI bounds."""

import asyncio
import csv
import io
import sys
from contextlib import redirect_stderr
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import scrape_property_listings as source  # noqa: E402
from property.atomic_io import write_text_atomic  # noqa: E402

LISTING = {"title": "Condo A", "type": "condo_rent_bkk", "price": 20000.0,
           "url": "https://WWW.ddproperty.com/listing/a-1/?utm_source=x&fbclid=y#photos"}


def _rows(path: Path) -> list[dict]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("https://WWW.ddproperty.com/listing/a-1/?utm_source=x&fbclid=y#photos",
         "https://www.ddproperty.com/listing/a-1"),
        ("https://site.example/p?b=2&a=1&gclid=z", "https://site.example/p?a=1&b=2"),
        ("https://site.example/", "https://site.example/"),
        ("  not a url  ", "not a url"),
        ("", ""),
        ("mailto:agent@example.com", "mailto:agent@example.com"),
    ],
)
def test_canonical_listing_url(raw, expected):
    assert source.canonical_listing_url(raw) == expected


def test_history_stores_canonical_url_and_drops_match_tracking_variants(tmp_path):
    source.append_history([LISTING], tmp_path)
    history = tmp_path / "property_history.csv"
    assert _rows(history)[0]["url"] == "https://www.ddproperty.com/listing/a-1"
    cheaper = {**LISTING, "price": 15000.0, "url": "https://www.ddproperty.com/listing/a-1?utm_medium=mail"}
    drops = source.detect_price_drops([cheaper], history, 10.0)
    assert [d["old_price"] for d in drops] == [20000.0]


def test_legacy_history_rows_with_tracking_params_still_match(tmp_path):
    history = tmp_path / "property_history.csv"
    history.write_text(
        "date,title,type,price,bedrooms,area_sqm,location,url\r\n"
        "2026-09-01,Condo A,condo_rent_bkk,20000,,,,https://www.ddproperty.com/listing/a-1/?utm_source=old\r\n",
        encoding="utf-8",
    )
    drops = source.detect_price_drops([{**LISTING, "price": 17000.0}], history, 10.0)
    assert len(drops) == 1


def test_history_append_keeps_single_header_and_repairs_torn_newline(tmp_path):
    history = tmp_path / "property_history.csv"
    history.write_text(",".join(source.HISTORY_FIELDS), encoding="utf-8")
    source.append_history([LISTING], tmp_path)
    source.append_history([{**LISTING, "title": "Condo B"}], tmp_path)
    assert [row["title"] for row in _rows(history)] == ["Condo A", "Condo B"]


def test_failed_snapshot_write_keeps_previous_file(tmp_path):
    source.save_listings([LISTING], tmp_path)
    snapshot = tmp_path / "property_listings.csv"
    before = snapshot.read_text(encoding="utf-8")
    with patch("property.atomic_io.os.replace", side_effect=OSError("disk full")):
        with pytest.raises(OSError):
            source.save_listings([{**LISTING, "title": "New"}], tmp_path)
    assert snapshot.read_text(encoding="utf-8") == before
    assert sorted(p.name for p in tmp_path.iterdir()) == ["property_listings.csv"]


def test_write_text_atomic_creates_parent(tmp_path):
    target = tmp_path / "a" / "b.txt"
    write_text_atomic(target, "ok")
    assert target.read_text(encoding="utf-8") == "ok"


@pytest.mark.parametrize("value", ["0", "-5", "101", "nan"])
def test_cli_rejects_bad_drop_pct(value):
    with redirect_stderr(io.StringIO()):
        with pytest.raises(SystemExit) as ctx:
            source.main(["--dry-run", "--alert-drop-pct", value])
    assert ctx.value.code == 2


def test_cli_rejects_output_dir_that_is_a_file(tmp_path):
    blocker = tmp_path / "f"
    blocker.write_text("x", encoding="utf-8")
    with redirect_stderr(io.StringIO()):
        with pytest.raises(SystemExit) as ctx:
            source.main(["--dry-run", "--output-dir", str(blocker)])
    assert ctx.value.code == 2


def test_scheduler_wrapper_rejects_bad_drop_pct():
    with pytest.raises(ValueError):
        source.PropertyListingScraper(alert_drop_pct=0)


def test_ddproperty_snapshot_is_written_atomically(tmp_path):
    from property.ddproperty_scraper import DDPropertyScraper

    scraper = DDPropertyScraper(output_dir=tmp_path)
    with patch.object(DDPropertyScraper, "_collect", return_value=[{"title": "X", "price": 1, "url": "u"}]):
        result = asyncio.run(scraper.run())
    path = Path(result[0]["output"])
    assert _rows(path)[0]["title"] == "X"
    assert sorted(p.name for p in tmp_path.iterdir()) == [path.name]
