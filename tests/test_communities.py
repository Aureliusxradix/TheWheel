"""Communities on the board (his picks 2026-10-23): added directly and checked like a listing, and proven organisers listed.

    /usr/bin/python3 -E -s -m unittest tests/test_communities.py
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "tests" / "fixtures" / "gate-patterns.txt"
TMP = Path(tempfile.mkdtemp(prefix="wheel-comm-"))
sys.path.insert(0, str(ROOT))
from hub import gate, organisers, server, store  # noqa: E402

GOOD = {"name": "  Orewa   kava circle ", "about": "We sit, share kava and talk story.", "where": "Orewa Hall",
        "when": "Every Friday evening", "link": "https://orewakava.nz", "tags": ["Kava", " "], "modes": ["night", "nope"]}


class Communities(unittest.TestCase):
    def setUp(self):
        store.DB = TMP / f"{self.id()}.db"
        server._local.__dict__.clear()
        server.GATE = gate.load(FIXTURE, builtin=False)
        self.db = server.db()

    def test_cleaned_and_checked(self):
        rec = server.clean_community(GOOD)
        self.assertEqual((rec["name"], rec["tags"], rec["modes"]), ("Orewa kava circle", ["kava"], ["night"]))
        for bad, why in [({**GOOD, "when": ""}, "when"), ({**GOOD, "modes": []}, "mode"),
                         ({**GOOD, "link": "https://chat.whatsapp.com/AbCdEfGhIjKl"}, "chat"), ({**GOOD, "name": "x"}, "name")]:
            with self.assertRaises(ValueError, msg=why):
                server.clean_community(bad)

    def test_only_checked_ones_show_and_no_pen_name_leaves(self):
        rec = {"id": "c" * 16, **server.clean_community(GOOD)}
        store.community_put(self.db, rec, "pending", "a" * 16, "2026-10-23")
        self.assertEqual(store.communities(self.db, "approved"), [])
        store.community_put(self.db, rec, "approved")
        shown = [server.community_public(c) for c in store.communities(self.db, "approved")]
        self.assertEqual(shown[0]["name"], "Orewa kava circle")
        self.assertNotIn("a" * 16, json.dumps(shown))
        self.assertEqual(store.community(self.db, "c" * 16)["_account"], "a" * 16)  # the adder kept for review only

    def test_proven_organisers_listed(self):
        a = organisers.new(self.db, "Te Karanga", "https://tekaranga.nz")
        organisers.new(self.db, "Not yet proven", "https://other.nz")
        organisers.prove(self.db, a["id"], "page")
        self.assertEqual([o["name"] for o in server.proven_organisers()], ["Te Karanga"])


if __name__ == "__main__":
    unittest.main()
