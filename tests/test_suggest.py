"""Suggested fixes: a member below the Reviewer tier sends a fix, a Reviewer or Steward uses it or drops it.

    /usr/bin/python3 -E -s -m unittest tests/test_suggest.py
"""
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "tests" / "fixtures" / "gate-patterns.txt"
TMP = Path(tempfile.mkdtemp(prefix="wheel-suggest-"))
sys.path.insert(0, str(ROOT))
from hub import gate, server, store  # noqa: E402

REC = {"id": "a" * 16, "name": "Sound bath", "start_date": "2099-01-01", "modes": ["recovery"], "tags": ["sound bath"],
       "price": "$20", "review": {"state": "pending"}}


class Changes(unittest.TestCase):
    def test_only_what_changed_as_it_would_read(self):
        got = server.changes(dict(REC), {"name": "Sound bath", "price": "", "website": " https://example.org/x ",
                                         "tags": ["Sound Bath", "Rest"], "modes": ["recovery"]})
        self.assertEqual(got, {"price": None, "tags": ["sound bath", "rest"], "website": "https://example.org/x"})

    def test_nothing_changed_is_empty_and_the_listing_untouched(self):
        rec = dict(REC)
        self.assertEqual(server.changes(rec, {"name": "Sound bath", "modes": ["recovery"]}), {})
        self.assertEqual(rec, REC)

    def test_a_bad_link_is_refused(self):
        with self.assertRaises(ValueError):
            server.changes(dict(REC), {"website": "javascript:alert(1)"})


class Stored(unittest.TestCase):
    def setUp(self):
        store.DB = TMP / f"s-{self.id()}.db"
        self.db = store.connect()

    def test_one_per_member_per_listing_and_dropped(self):
        store.suggest(self.db, REC["id"], "pen1", {"price": "$25"}, "2026-10-21")
        store.suggest(self.db, REC["id"], "pen1", {"price": "$30"}, "2026-10-21")  # sending again replaces it
        store.suggest(self.db, REC["id"], "pen2", {"name": "Gong bath"}, "2026-10-21")
        got = store.suggestions_for(self.db, REC["id"])
        self.assertEqual([(s["account"], s["fields"]) for s in got], [("pen1", {"price": "$30"}), ("pen2", {"name": "Gong bath"})])
        store.drop_suggestion(self.db, got[0]["id"])
        self.assertIsNone(store.suggestion(self.db, got[0]["id"]))

    def test_shown_without_pen_names_and_a_marked_one_held_alone(self):
        server.GATE = gate.load(FIXTURE, builtin=False)
        store.suggest(self.db, REC["id"], "pen1", {"price": "$25"}, "2026-10-21")
        store.suggest(self.db, REC["id"], "pen2", {"organiser": "fakename"}, "2026-10-21")
        shown = server.shown_suggestions(store.suggestions_for(self.db, REC["id"]))
        self.assertEqual([s["fields"] for s in shown], [{"price": "$25"}])
        self.assertNotIn("account", shown[0])


if __name__ == "__main__":
    unittest.main()
