"""Repeating listings shown on their next date: the wording read, the unclear left alone, the server's answer.

    /usr/bin/python3 -E -s -m unittest tests/test_repeats.py
"""
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.request
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "tests" / "fixtures" / "gate-patterns.txt"
TMP = Path(tempfile.mkdtemp(prefix="wheel-repeats-"))
sys.path.insert(0, str(ROOT))
from hub import repeats, store  # noqa: E402

TODAY = "2026-12-01"  # a Tuesday


class Read(unittest.TestCase):
    def check(self, text, start, want):
        self.assertEqual(repeats.next_on(text, start, TODAY), want, text)

    def test_weekly(self):
        self.check("Every Monday Evening", "2026-10-19", "2026-12-07")
        self.check("Tuesdays", "2026-10-20", "2026-12-01")  # on today counts as next
        self.check("Weekly online from Tuesday 20 October 2026", "2026-10-20", "2026-12-01")

    def test_every_few_weeks(self):
        self.check("fortnightly on Fridays", "2026-10-23", "2026-12-04")
        self.check("every second Friday afternoon", "2026-10-23", "2026-12-04")
        self.check("Every six weeks", "2026-11-10", "2026-12-22")

    def test_monthly(self):
        self.check("Every second Sunday of the month", "2026-11-08", "2026-12-13")
        self.check("Monthly // Every Forth Sunday", "2026-10-25", "2026-12-27")
        self.check("every two months, on the last Sunday of the month", "2026-10-25", "2026-12-27")

    def test_unclear_wording_moves_nothing(self):
        for text, start in (("Open Monday–Friday, 10 am–5 pm", "2026-10-19"), ("Monthly", "2026-10-29"),
                            ("unknown", "2026-10-22"), ("Every Tuesday", "2026-10-19"),  # 19 Oct is a Monday
                            ("every two months, on the last Sunday of the month", "2026-11-01")):  # not the last
            self.check(text, start, None)

    def test_a_future_date_stays(self):
        self.check("Every Monday", "2027-01-04", "2027-01-04")

    def test_dates_ahead_for_picking_a_day(self):
        got = repeats.dates_ahead("fortnightly on Fridays", "2026-10-23", TODAY, days=30)
        self.assertEqual(got, ["2026-12-04", "2026-12-18"])
        self.assertEqual(len(repeats.dates_ahead("Every Monday Evening", "2026-10-19", TODAY)), 26)
        self.assertEqual(repeats.dates_ahead("Monthly", "2026-10-29", TODAY), [])


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Served(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        today = datetime.now(ZoneInfo("Pacific/Auckland")).date()
        cls.first = (today - timedelta(days=14)).isoformat()
        cls.want = today.isoformat()  # found fourteen days back, weekly: on again today
        store.DB = TMP / "served.db"
        db = store.connect()
        weekday = (today - timedelta(days=14)).strftime("%A")
        store.put(db, {"id": "a" * 16, "name": "Weekly class", "start_date": cls.first, "end_date": cls.first,
                       "recurrence": f"Every {weekday}", "modes": ["day"], "review": {"state": "approved"}})
        store.put(db, {"id": "b" * 16, "name": "Some class", "start_date": cls.first, "recurrence": "Monthly",
                       "modes": ["day"], "review": {"state": "approved"}})
        store.put(db, {"id": "c" * 16, "name": "Talk", "start_date": cls.first, "recurrence": "unknown",
                       "modes": ["day"], "review": {"state": "approved"}})
        store.put(db, {"id": "d" * 16, "name": "Weekly, waiting", "start_date": cls.first, "recurrence": f"Every {weekday}",
                       "modes": ["day"], "review": {"state": "pending"}})
        cls.port = free_port()
        env = {**os.environ, "WHEEL_GATE_PATTERNS": str(FIXTURE), "WHEEL_API_ONLY": "1", "EVENTHUB_DB": str(store.DB),
               "WHEEL_ZK_URL": "http://127.0.0.1:9"}
        cls.proc = subprocess.Popen([sys.executable, "-E", "-s", str(ROOT / "hub" / "server.py"), "--port", str(cls.port)],
                                    env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(50):
            try:
                socket.create_connection(("127.0.0.1", cls.port), 0.2).close()
                break
            except OSError:
                time.sleep(0.1)

    @classmethod
    def tearDownClass(cls):
        cls.proc.terminate()
        cls.proc.wait(timeout=10)

    def test_next_date_sent_and_found_date_kept(self):
        with urllib.request.urlopen(f"http://127.0.0.1:{self.port}/api/events", timeout=10) as r:
            got = {e["id"]: e for e in json.load(r)["events"]}
        weekly, monthly = got["a" * 16], got["b" * 16]
        self.assertEqual((weekly["start_date"], weekly["next_date"], weekly["next_end"]), (self.first, self.want, self.want))
        self.assertNotIn("next_date", monthly)
        self.assertEqual(weekly["repeats_on"][:2], [self.want, (date.fromisoformat(self.want) + timedelta(days=7)).isoformat()])
        self.assertNotIn("repeats_on", monthly)
        self.assertFalse(weekly["past"] or monthly["past"])
        self.assertNotIn("recurrence", got["c" * 16])  # "unknown" is no repeat: it goes to the archive like any other
        self.assertTrue(got["c" * 16]["past"])

    def test_review_queue_gives_the_same_date(self):
        with urllib.request.urlopen(f"http://127.0.0.1:{self.port}/api/review", timeout=10) as r:
            got = {e["id"]: e for e in json.load(r)["events"]}
        self.assertEqual((got["d" * 16]["next_date"], got["d" * 16]["past"]), (self.want, False))


if __name__ == "__main__":
    unittest.main()
