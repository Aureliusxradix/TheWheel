"""Organiser accounts (his ruling 2026-10-23): their own key, proven by a code on their page or a steward's vouch,
claims by link, updates, and the public list showing who keeps a listing.

    /usr/bin/python3 -E -s -m unittest tests/test_organisers.py
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "tests" / "fixtures" / "gate-patterns.txt"
TMP = Path(tempfile.mkdtemp(prefix="wheel-org-"))
sys.path.insert(0, str(ROOT))
from hub import gate, organisers as org, server, store  # noqa: E402

OWN = {"id": "1" * 16, "name": "Kava circle", "start_date": "2099-03-06", "modes": ["night"], "review": {"state": "approved"},
       "website": "https://www.tekaranga.nz/events/kava"}
FB = {"id": "2" * 16, "name": "Open mic", "start_date": "2099-03-07", "modes": ["night"], "review": {"state": "pending"},
      "website": "https://www.facebook.com/somebodyelse/posts/1"}


class Links(unittest.TestCase):
    def test_own_site_whole_shared_site_by_path(self):
        self.assertTrue(org.links_to("https://tekaranga.nz", "https://www.tekaranga.nz/events/kava?x=1"))
        self.assertTrue(org.links_to("https://www.facebook.com/tekaranga", "https://m.facebook.com/tekaranga/events/9"))
        self.assertFalse(org.links_to("https://www.facebook.com/tekaranga", "https://www.facebook.com/somebodyelse/posts/1"))
        self.assertFalse(org.links_to("https://www.facebook.com/tekaranga", "https://www.facebook.com/tekarangafake"))
        self.assertFalse(org.links_to("https://tekaranga.nz", "https://tekaranga.nz.evil.com/x"))

    def test_names_and_pages(self):
        for bad in ("x", "Call 0215551234", "see https://x.nz", "@tekaranga"):
            with self.assertRaises(ValueError):
                org.clean_name(bad)
        with self.assertRaises(ValueError):
            org.clean_page("http://tekaranga.nz")
        self.assertEqual(org.clean_name("  Te   Karanga "), "Te Karanga")


class Accounts(unittest.TestCase):
    def setUp(self):
        store.DB = TMP / f"{self.id()}.db"
        server._local.__dict__.clear()
        server.GATE = gate.load(FIXTURE, builtin=False)
        self.db = server.db()
        for r in (OWN, FB):
            store.put(self.db, json.loads(json.dumps(r)))
        made = org.new(self.db, "Te Karanga", "https://tekaranga.nz")
        self.key, self.o = made["key"], org.by_key(self.db, made["key"])
        self.assertRegex(made["code"], r"^WHEEL-[A-Z2-9]{6}$")

    def test_key_kept_as_a_fingerprint(self):
        self.assertNotIn(self.key, json.dumps([dict(r) for r in self.db.execute("SELECT * FROM organisers")]))
        self.assertIsNone(org.by_key(self.db, "nope"))

    def test_proof_then_claims(self):
        with self.assertRaises(PermissionError):
            org.claim(self.db, self.o, store.get(self.db, OWN["id"]))
        self.assertTrue(org.page_shows(f"<p>our code {self.o['code'].lower()}</p>".encode(), self.o["code"]))
        org.prove(self.db, self.o["id"], "page")
        o = org.by_key(self.db, self.key)
        self.assertEqual(org.claim(self.db, o, store.get(self.db, OWN["id"])), "claimed")
        self.assertEqual(org.claim(self.db, o, store.get(self.db, FB["id"])), "waiting")  # links elsewhere: a steward decides
        self.assertTrue(org.holds(self.db, o, OWN["id"]) and not org.holds(self.db, o, FB["id"]))
        other = org.by_key(self.db, org.new(self.db, "Other crew", "https://other.nz")["key"])
        org.prove(self.db, other["id"], "steward")
        with self.assertRaises(PermissionError):
            org.claim(self.db, org.get(self.db, other["id"]), store.get(self.db, OWN["id"]))
        self.assertEqual(server.claimed_map(), {OWN["id"]: {"id": o["id"], "name": "Te Karanga"}})
        org.answer_claim(self.db, FB["id"], True)
        self.assertIn(FB["id"], server.claimed_map())

    def test_updates_straight_away_with_a_note(self):
        org.prove(self.db, self.o["id"], "page")
        rec = store.get(self.db, OWN["id"])
        with self.assertRaises(ValueError):
            server.org_update(rec, self.o, {"status": "sold out"})
        changed = server.org_update(rec, self.o, {"status": "cancelled", "start_time": "19:00", "name": "Renamed",
                                                  "note": "Rain: call 021 555 1234"})
        self.assertEqual(changed, ["start_time", "status", "org_note"])
        got = store.get(self.db, OWN["id"])
        self.assertEqual((got["status"], got["name"], got["org_note"]["text"]), ("cancelled", "Kava circle", "Rain: call [number]"))


if __name__ == "__main__":
    unittest.main()
