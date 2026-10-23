"""Day's own, round three (his calls 2026-10-24): shifts taken under a pen name, thanks that count toward Regular and
never toward review weight, crews, the ask board's two-sided threads, and the skillshare swap's counts.

    /usr/bin/python3 -E -s -m unittest tests/test_day.py
"""
import json
import sys
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "tests" / "fixtures" / "gate-patterns.txt"
TMP = Path(tempfile.mkdtemp(prefix="wheel-day-"))
sys.path.insert(0, str(ROOT))
from hub import day, gate, rep, server, store  # noqa: E402

TODAY = date.today().isoformat()
PAST = (date.today() - timedelta(days=2)).isoformat()
SOON = (date.today() + timedelta(days=3)).isoformat()
A, B, C = "a" * 16, "b" * 16, "c" * 16
CALL = {"id": "6" * 16, "name": "Beach clean", "start_date": SOON, "modes": ["day"], "review": {"state": "approved"},
        "listing_kind": "volunteer", "slots": [{"date": SOON, "start": "09:00", "end": "12:00", "needed": 2, "task": "Pick up"},
                                                 {"date": PAST, "start": "09:00", "end": "12:00", "needed": 3, "task": "Sort"}]}


class Day(unittest.TestCase):
    def setUp(self):
        store.DB = TMP / f"{self.id()}.db"
        server._local.__dict__.clear()
        server.GATE = gate.load(FIXTURE, builtin=False)
        self.db = server.db()
        for acct in (A, B, C):
            store.ensure_account(self.db, acct)
        store.put(self.db, json.loads(json.dumps(CALL)))
        self.rec = store.get(self.db, CALL["id"])
        self.k_soon, self.k_past = [day.slot_key(s) for s in CALL["slots"]]

    def test_take_fill_and_leave(self):
        day.take(self.db, self.rec, self.k_soon, A, TODAY)
        day.take(self.db, self.rec, self.k_soon, B, TODAY)
        with self.assertRaises(ValueError):
            day.take(self.db, self.rec, self.k_soon, C, TODAY)  # full at 2
        with self.assertRaises(ValueError):
            day.take(self.db, self.rec, self.k_past, C, TODAY)  # already happened
        self.assertEqual(day.fill(self.db, self.rec), [{"key": self.k_soon, "taken": 2}, {"key": self.k_past, "taken": 0}])
        day.leave(self.db, self.rec, self.k_soon, B)
        self.assertEqual(day.fill(self.db, self.rec)[0]["taken"], 1)
        self.assertEqual(day.mine(self.db, A)["slots"], [{"listing": CALL["id"], "key": self.k_soon, "thanked": False}])

    def test_thanks_count_toward_regular_and_never_review_weight(self):
        self.db.execute("INSERT INTO shift_claims(listing_id, slot, account, day) VALUES(?,?,?,?)", (CALL["id"], self.k_past, A, PAST))
        self.db.commit()
        with self.assertRaises(ValueError):
            day.thank(self.db, self.rec, self.k_soon, A, TODAY)  # before the shift
        with self.assertRaises(LookupError):
            day.thank(self.db, self.rec, self.k_past, B, TODAY)  # B took no place
        day.thank(self.db, self.rec, self.k_past, A, TODAY)
        self.assertEqual((rep.points(self.db, A), rep.points(self.db, A, thanks=False)), (2, 0))
        day.leave(self.db, self.rec, self.k_past, A)  # a thanked shift stays
        self.assertTrue(day.who_took(self.db, self.rec)[1]["people"][0]["thanked"])

    def test_asks_and_threads(self):
        with self.assertRaises(ValueError):
            day.clean_ask({"text": "help", "by": SOON}, TODAY)
        a = day.clean_ask({"kind": "lift", "text": "A lift to the beach clean on Saturday", "by": SOON}, TODAY)
        self.db.execute("INSERT INTO asks(id, account, kind, text, area, by_day, day) VALUES(?,?,?,?,?,?,?)",
                        ("7" * 16, A, a["kind"], a["text"], a["area"], a["by_day"], TODAY))
        ask = dict(self.db.execute("SELECT * FROM asks").fetchone())
        with self.assertRaises(LookupError):
            day.send(self.db, ask, A, B, "Hello?", 1)  # the asker replies inside a thread someone started
        day.send(self.db, ask, B, None, "I can take you, leaving 8:30", 1)
        day.send(self.db, ask, C, None, "Me too", 2)
        day.send(self.db, ask, A, B, "Thank you!", 3)
        self.assertEqual(len(day.threads(self.db, ask, A)), 2, "the asker sees every thread")
        mine = day.threads(self.db, ask, C)
        self.assertEqual([t["with"] for t in mine], [C], "a responder sees their own thread only")
        board = day.asks_open(self.db, TODAY, B)
        self.assertEqual((board[0]["answered"], "threads" in board[0]), (True, False))

    def test_swap_counts(self):
        for acct in (A, B, C):
            day.swap_set(self.db, acct, "Sourdough ", "learn", True, TODAY)
        day.swap_set(self.db, A, "sourdough", "teach", True, TODAY)
        b = day.swap_board(self.db)[0]
        self.assertEqual((b["topic"], b["teach"], b["learn"], b["ready"]), ("sourdough", 1, 3, False))
        self.db.execute("INSERT INTO swap VALUES(?,?,?,?)", ("d" * 16, "sourdough", "learn", TODAY))
        self.assertTrue(day.swap_board(self.db)[0]["ready"])


if __name__ == "__main__":
    unittest.main()
