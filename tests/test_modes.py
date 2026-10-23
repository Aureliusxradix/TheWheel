"""Each mode's own, round one (his calls 2026-10-24): doors and last entry, care, the solo meeting point, retreat details.

    /usr/bin/python3 -E -s -m unittest tests/test_modes.py
"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from hub import server  # noqa: E402


def rec(**kw):
    return {"id": "4" * 16, "name": "Late set", "start_date": "2099-03-06", "modes": ["night", "recovery"], **kw}


class Fields(unittest.TestCase):
    def test_night_fields(self):
        r = server.clean(rec(), {"doors": "19:00", "last_entry": "23:30", "care": ["water", "checking", "made-up"],
                                  "solo_meet": "By the front bar at 20:30, or text 021 555 1234"})
        self.assertEqual((r["doors"], r["last_entry"], r["care"]), ("19:00", "23:30", ["water", "checking"]))
        self.assertNotIn("555", r["solo_meet"])
        with self.assertRaises(ValueError):
            server.clean(rec(), {"doors": "7pm"})
        r = server.clean(r, {"care": [], "doors": ""})
        self.assertNotIn("care", r)
        self.assertNotIn("doors", r)

    def test_retreat(self):
        r = server.clean(rec(), {"retreat": {"asks": ["silence", "substancefree", "nope"], "sleep": "Cabins", "food": "",
                                             "intake": "https://example.org/intake"}})
        self.assertEqual(r["retreat"], {"asks": ["silence", "substancefree"], "intake": "https://example.org/intake",
                                        "sleep": "Cabins", "food": None, "bring": None})
        with self.assertRaises(ValueError):
            server.clean(rec(), {"retreat": {"intake": "javascript:alert(1)"}})
        self.assertNotIn("retreat", server.clean(rec(), {"retreat": {"asks": [], "sleep": " "}}))

    def test_organisers_keep_them_right(self):
        for f in ("doors", "last_entry", "solo_meet", "care", "retreat"):
            self.assertIn(f, server.ORG_FIELDS)


if __name__ == "__main__":
    unittest.main()
