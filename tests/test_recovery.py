"""Recovery's own, round two (his calls 2026-10-24): places that stay, checked by members and claimable by organisers;
practitioners whose every field carries its own audience.

    /usr/bin/python3 -E -s -m unittest tests/test_recovery.py
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "tests" / "fixtures" / "gate-patterns.txt"
TMP = Path(tempfile.mkdtemp(prefix="wheel-rec-"))
sys.path.insert(0, str(ROOT))
from hub import gate, organisers as org, recovery, server, store  # noqa: E402

SAUNA = {"name": "Harbour Sauna", "kind": "sauna", "locality": "Devonport", "link": "https://harboursauna.nz",
         "hours": {"mon": "07:00-21:00", "sat": "07:00-12:00, 16:00–21:00"}, "care": ["women", "made-up"],
         "sessions": [{"when": "Tue 18:00-20:00", "what": "Women's session"}, {"when": "x", "what": ""}]}


class Places(unittest.TestCase):
    def test_clean(self):
        p = recovery.clean_place(SAUNA, server.CARE)
        self.assertEqual(p["hours"], {"mon": "07:00-21:00", "sat": "07:00-12:00, 16:00-21:00"})
        self.assertEqual((p["care"], len(p["sessions"])), (["women"], 1))
        for bad in ({**SAUNA, "hours": {"mon": "7am-9pm"}}, {**SAUNA, "locality": ""}, {**SAUNA, "booking": "ftp://x"}):
            with self.assertRaises(ValueError):
                recovery.clean_place(bad, server.CARE)

    def test_claimed_by_an_organiser_whose_page_it_links_to(self):
        store.DB = TMP / "places.db"
        server._local.__dict__.clear()
        server.GATE = gate.load(FIXTURE, builtin=False)
        db = server.db()
        rec = {"id": "5" * 16, **recovery.clean_place(SAUNA, server.CARE)}
        store.place_put(db, rec, "approved", "a" * 16, "2026-10-24")
        o = org.by_key(db, org.new(db, "Harbour Sauna", "https://harboursauna.nz")["key"])
        org.prove(db, o["id"], "page")
        o = org.get(db, o["id"])
        self.assertEqual(org.claim(db, o, {"id": rec["id"], "website": rec["link"], "tickets_url": None}), "claimed")
        self.assertTrue(org.holds(db, o, rec["id"]))
        held = server.claimed_map()
        self.assertEqual(server.place_out(store.place(db, rec["id"]), held)["claimed_by"]["name"], "Harbour Sauna")
        self.assertEqual([x["listings"] for x in server.proven_organisers()], [0], "a held place counts apart from listings")


class Practice(unittest.TestCase):
    def test_every_field_has_an_audience(self):
        pr = recovery.clean_practice({"listed": True, "modalities": {"v": "Massage, breathwork", "a": "all"},
                                      "signal": {"v": "quietwater.01"}, "phone": {"v": "021 555 1234", "a": "off"},
                                      "registration": {"v": "Massage NZ member", "a": "mem"}})
        self.assertEqual(pr["signal"], {"v": "quietwater.01", "a": "mem"}, "contact goes to members unless opened")
        self.assertEqual(recovery.practice_shown(pr, False), {"modalities": ["Massage", "breathwork"]})
        self.assertEqual(set(recovery.practice_shown(pr, True)), {"modalities", "signal", "registration"})
        self.assertNotIn("phone", recovery.practice_shown(pr, True), "held back from everyone")
        for bad in ({"signal": {"v": "not a handle!"}}, {"email": {"v": "nope"}}, {"booking": {"v": "javascript:x"}}):
            with self.assertRaises(ValueError):
                recovery.clean_practice(bad)

    def test_listed_only_when_proven_and_listed(self):
        store.DB = TMP / "practice.db"
        server._local.__dict__.clear()
        server.GATE = gate.load(FIXTURE, builtin=False)
        db = server.db()
        a = org.by_key(db, org.new(db, "Quiet Water Bodywork", "https://quietwater.nz")["key"])
        b = org.by_key(db, org.new(db, "Unproven Hands", "https://unproven.nz")["key"])
        for o in (a, b):
            db.execute("UPDATE organisers SET practice=? WHERE id=?",
                       (json.dumps(recovery.clean_practice({"listed": True, "area": {"v": "Matakana"}})), o["id"]))
        org.prove(db, a["id"], "steward")
        got = server.practitioners(False)
        self.assertEqual([(x["name"], x["area"], x["vouches"]) for x in got], [("Quiet Water Bodywork", "Matakana", 0)])


if __name__ == "__main__":
    unittest.main()
