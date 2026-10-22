"""Duplicates (his ask 2026-10-23): copies collapse in the list, look-alikes pair up for Review, a merge carries the
missing links across and leaves rep untouched, and kept-apart pairs stay apart.

    /usr/bin/python3 -E -s -m unittest tests/test_dupes.py
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "tests" / "fixtures" / "gate-patterns.txt"
TMP = Path(tempfile.mkdtemp(prefix="wheel-dupes-"))
sys.path.insert(0, str(ROOT))
from hub import gate, rep, server, store  # noqa: E402

D = "2099-10-23"
A = {"id": "a" * 16, "name": "Make Give Live", "start_date": D, "modes": ["day"], "review": {"state": "approved"}}
B = {"id": "b" * 16, "name": "Make  give live!", "start_date": D, "modes": ["day"], "review": {"state": "pending"},
     "website": "https://hub.example/mgl", "deposited_account": "f" * 16}
C = {"id": "c" * 16, "name": "Make Give Live group", "start_date": D, "modes": ["day"], "review": {"state": "pending"}}
E = {"id": "e" * 16, "name": "Make Give Live", "start_date": "2099-11-06", "modes": ["day"], "review": {"state": "approved"}}


class Dupes(unittest.TestCase):
    def setUp(self):
        store.DB = TMP / f"{self.id()}.db"
        server._local.__dict__.clear()
        server.GATE = gate.load(FIXTURE, builtin=False)
        self.db = server.db()
        for r in (A, B, C, E):
            store.put(self.db, json.loads(json.dumps(r)))

    def test_copies_collapse_to_the_checked_one(self):
        shown = [r["id"] for r in server.collapse_copies(store.events(self.db, ("approved", "pending")))]
        self.assertIn(A["id"], shown)
        self.assertNotIn(B["id"], shown)  # same name, same day
        self.assertIn(C["id"], shown)  # a different name stays
        self.assertIn(E["id"], shown)  # another date stays

    def test_pairs_then_merge_carries_links_and_leaves_rep(self):
        pairs = server.duplicate_pairs()
        exact = [p for p in pairs if p["exact"]]
        self.assertEqual({x["id"] for x in exact[0]["listings"]}, {A["id"], B["id"]})
        self.assertTrue(any({x["id"] for x in p["listings"]} == {A["id"], C["id"]} for p in pairs))  # look-alike
        server.merge_copy(store.get(self.db, A["id"]), store.get(self.db, B["id"]))
        self.assertEqual(store.get(self.db, A["id"])["website"], "https://hub.example/mgl")
        self.assertEqual(store.get(self.db, B["id"])["review"]["state"], "merged")
        store.ensure_account(self.db, "f" * 16)
        self.assertEqual(rep.points(self.db, "f" * 16), 0)  # a merged copy costs its adder nothing
        self.assertFalse(any(B["id"] in {x["id"] for x in p["listings"]} for p in server.duplicate_pairs()))

    def test_kept_apart_stays_apart(self):
        store.keep_dups_apart(self.db, C["id"], A["id"], "2099-10-01")
        self.assertFalse(any({x["id"] for x in p["listings"]} == {A["id"], C["id"]} for p in server.duplicate_pairs()))
        store.keep_dups_apart(self.db, A["id"], B["id"], "2099-10-01")
        shown = [r["id"] for r in server.collapse_copies(store.events(self.db, ("approved", "pending")))]
        self.assertIn(B["id"], shown)  # a person said these two differ, so both show


if __name__ == "__main__":
    unittest.main()
