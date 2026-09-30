import io
import json
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scrape_property_listings import main


class PropertyRunnerDryRunTests(unittest.TestCase):
    def test_dry_run_does_not_collect_or_write(self):
        output = io.StringIO()
        with redirect_stdout(output):
            self.assertEqual(main(["--dry-run", "--type", "condo_sale_bkk"]), 0)
        report = json.loads(output.getvalue())
        self.assertEqual(report["status"], "dry-run")
        self.assertEqual(report["types"], ["condo_sale_bkk"])
        self.assertEqual(report["network"], "not-used")


if __name__ == "__main__":
    unittest.main()
