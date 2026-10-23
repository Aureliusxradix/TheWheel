"""Monero tickets paid straight to the organiser (his calls 2026-10-24): the sale, the quote, the buyer's proof, the
watcher's check_tx_key answers, the door, and what the store refuses to keep.

    /usr/bin/python3 -E -s -m unittest tests/test_tickets.py
"""
import json
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "tests" / "fixtures" / "gate-patterns.txt"
TMP = Path(tempfile.mkdtemp(prefix="wheel-tickets-"))
sys.path.insert(0, str(ROOT))
from hub import gate, organisers as org, server, store, tickets  # noqa: E402

GIG = {"id": "3" * 16, "name": "Basement gig", "start_date": "2099-03-06", "modes": ["night"], "review": {"state": "approved"},
       "website": "https://basementgigs.nz/next"}
ADDR = "8" + "A" * 94
TXID, TXKEY = "ab" * 32, "cd" * 32


class Tickets(unittest.TestCase):
    def setUp(self):
        store.DB = TMP / f"{self.id()}.db"
        server._local.__dict__.clear()
        server.GATE = gate.load(FIXTURE, builtin=False)
        self.db = server.db()
        store.put(self.db, json.loads(json.dumps(GIG)))
        key = org.new(self.db, "Basement Gigs", "https://basementgigs.nz")["key"]
        self.o = org.by_key(self.db, key)
        org.prove(self.db, self.o["id"], "page")
        org.claim(self.db, org.by_key(self.db, key), store.get(self.db, GIG["id"]))
        tickets.set_sale(self.db, GIG["id"], self.o["id"], ADDR, 20, 5, True)

    def test_the_sale_checks_its_fields(self):
        for bad in (("4abc", 20, 5), (ADDR, 0, 5), (ADDR, 20, 0)):
            with self.assertRaises(ValueError):
                tickets.set_sale(self.db, GIG["id"], self.o["id"], *bad, True)
        self.assertEqual(tickets.sale_public(self.db, GIG["id"], self.o["id"]), {"nzd": 20.0, "left": 5})
        self.assertIsNone(tickets.sale_public(self.db, GIG["id"], "someone-else"))  # only the holder's sale shows

    def test_quote_proof_check_door(self):
        q = tickets.quote(self.db, GIG["id"], 2, 400.0, self.o["id"])
        self.assertEqual((q["address"], q["amount"], q["nzd"]), (ADDR, "0.100000000000", 40.0))
        self.assertEqual(tickets.sale_public(self.db, GIG["id"], self.o["id"])["left"], 3)  # held while it is paid
        with self.assertRaises(ValueError):
            tickets.quote(self.db, GIG["id"], 4, 400.0, self.o["id"])
        st = tickets.prove(self.db, q["token"], TXID.upper(), TXKEY)
        self.assertEqual((st["state"], "codes" in st), ("checking", False))
        codes = tickets.codes_for(q["token"], 2)
        self.assertEqual(tickets.door(self.db, GIG["id"], codes[0])["state"], "unknown")  # unpaid yet
        check = tickets.watch_list(self.db)
        self.assertEqual(check, [{"id": check[0]["id"], "txid": TXID, "txkey": TXKEY, "address": ADDR}])
        self.assertEqual(tickets.watch_report(self.db, check[0]["id"], error="Failed to get transaction"), "checking")
        self.assertEqual(tickets.watch_report(self.db, check[0]["id"], 10 ** 11, 0, True), "issued")
        st = tickets.status(self.db, q["token"])
        self.assertEqual((st["state"], st["codes"]), ("issued", codes))
        self.assertEqual(tickets.door(self.db, GIG["id"], codes[0].lower().replace("-", " ")),
                         {"state": "confirming", "confirmations": 0, "need": 10})
        self.assertEqual(tickets.door(self.db, GIG["id"], codes[0])["state"], "used")
        self.assertEqual(tickets.watch_report(self.db, check[0]["id"], 10 ** 11, 12), "paid")
        self.assertEqual(tickets.door(self.db, GIG["id"], codes[1])["state"], "valid")
        self.assertEqual(tickets.door(self.db, "9" * 16, codes[1])["state"], "unknown")  # a code fits its own listing
        self.assertEqual(tickets.watch_list(self.db), [])
        kept = json.dumps([dict(r) for t in ("ticket_orders", "tickets") for r in self.db.execute(f"SELECT * FROM {t}")])
        for secret in [TXID, TXKEY, q["token"]] + codes:
            self.assertNotIn(secret, kept)
        self.assertEqual(tickets.counts(self.db, GIG["id"]), {"sold": 2, "used": 2, "held": 0})

    def test_one_payment_buys_once(self):
        a = tickets.quote(self.db, GIG["id"], 1, 400.0, self.o["id"])
        b = tickets.quote(self.db, GIG["id"], 1, 400.0, self.o["id"])
        tickets.prove(self.db, a["token"], TXID, TXKEY)
        with self.assertRaises(ValueError):
            tickets.prove(self.db, b["token"], TXID, TXKEY)

    def test_short_and_wrong_payments(self):
        a = tickets.quote(self.db, GIG["id"], 1, 400.0, self.o["id"])
        tickets.prove(self.db, a["token"], TXID, TXKEY)
        oid = tickets.watch_list(self.db)[0]["id"]
        self.assertEqual(tickets.watch_report(self.db, oid, 10 ** 10, 3), "short")
        self.assertEqual(tickets.status(self.db, a["token"])["received"], "0.010000000000")
        self.assertEqual(tickets.door(self.db, GIG["id"], tickets.codes_for(a["token"], 1)[0])["state"], "unknown")
        b = tickets.quote(self.db, GIG["id"], 1, 400.0, self.o["id"])
        tickets.prove(self.db, b["token"], "ef" * 32, TXKEY)
        oid = tickets.watch_list(self.db)[0]["id"]
        self.assertEqual(tickets.watch_report(self.db, oid, 0, 3), "bad")
        st = tickets.prove(self.db, b["token"], "ef" * 32, "12" * 32)  # a corrected proof, the same payment, checks again
        self.assertEqual(st["state"], "checking")

    def test_the_card_shows_the_sale_while_the_watcher_runs(self):
        server._watch_seen[0] = 0.0
        card = [e for e in server.listing({})["events"] if e["id"] == GIG["id"]][0]
        self.assertNotIn("xmr_tickets", card)
        server.WATCH_FILE = TMP / "watch.token"
        server.WATCH_FILE.write_text("w" * 40)
        server._watch_seen[0] = time.time()
        card = [e for e in server.listing({})["events"] if e["id"] == GIG["id"]][0]
        self.assertEqual(card["xmr_tickets"], {"nzd": 20.0, "left": 5})
        self.assertNotIn(ADDR, json.dumps(card))  # the address shows only on a quote


if __name__ == "__main__":
    unittest.main()
