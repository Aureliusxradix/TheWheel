"""Festivals (his ask 2026-10-23): their own kind, their own details kept short and plain, and spotted after reading.

    /usr/bin/python3 -E -s -m unittest tests/test_festival.py
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from hub import server  # noqa: E402

BASE = {"id": "f" * 16, "name": "Kerikeri Fest", "start_date": "2099-01-09", "end_date": "2099-01-11", "modes": ["day", "night"],
        "review": {"state": "pending"}}


class Festivals(unittest.TestCase):
    def test_kind_and_details_kept_short(self):
        rec = server.clean(dict(BASE), {"listing_kind": "festival", "modes": ["day", "night"], "festival": {
            "lineup": ["  Main   stage: Dub band ", "", "x" * 500], "tickets": [{"name": "Weekend pass", "price": "$180"}, {"name": ""}, "junk"],
            "camping": "On site", "ages": "", "bring": None, "access": "Ramps to the main stage"}})
        self.assertEqual(rec["listing_kind"], "festival")
        f = rec["festival"]
        self.assertEqual(f["lineup"][0], "Main stage: Dub band")
        self.assertEqual(len(f["lineup"][1]), 120)
        self.assertEqual(f["tickets"], [{"name": "Weekend pass", "price": "$180"}])
        self.assertEqual((f["camping"], f["ages"], f["bring"]), ("On site", None, None))

    def test_empty_details_leave_nothing(self):
        rec = server.clean(dict(BASE), {"modes": ["day"], "festival": {"lineup": [], "tickets": []}})
        self.assertNotIn("festival", rec)

    def test_spotted_by_name_or_kind_only(self):
        self.assertTrue(server.looks_like_festival({"name": "Forest Healing Festival"}))
        self.assertTrue(server.looks_like_festival({"name": "Gathering", "tags": ["festival"]}))
        self.assertFalse(server.looks_like_festival({"name": "The Art of Manifesting Workshop"}))
        self.assertFalse(server.looks_like_festival({"name": "Festive drinks"}))


if __name__ == "__main__":
    unittest.main()
