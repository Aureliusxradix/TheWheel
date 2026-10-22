"""Getting events to people (2026-10-22): share links with a preview, calendar files and feeds, and reports that send
a checked listing back to review.

    /usr/bin/python3 -E -s -m unittest tests/test_share.py
"""
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "tests" / "fixtures" / "gate-patterns.txt"
TMP = Path(tempfile.mkdtemp(prefix="wheel-share-"))
sys.path.insert(0, str(ROOT))
from hub import gate, rep, server, share, store  # noqa: E402

NIGHT = {"id": "1" * 16, "name": "Kava, poetry; and a long night of verse with friends from all over Tāmaki Makaurau",
         "start_date": "2099-03-06", "start_time": "21:30", "end_time": "01:00", "location_name": "The Hall",
         "location_locality": "Orewa", "price": "Koha", "modes": ["night"], "status": "confirmed",
         "review": {"state": "approved"}, "chat_platform": "signal", "chat_link": "https://signal.group/#abc",
         "chat_link_ok": True, "deposited_account": "f" * 16}
RETREAT = {"id": "2" * 16, "name": "Rest weekend", "start_date": "2099-07-03", "end_date": "2099-07-05",
           "modes": ["recovery"], "review": {"state": "approved"}}
WAITING = {"id": "3" * 16, "name": "Beach clean", "start_date": "2099-01-10", "modes": ["day"], "review": {"state": "pending"}}


def unfold(ics: str) -> list[str]:
    return ics.replace("\r\n ", "").split("\r\n")


class Calendar(unittest.TestCase):
    def test_times_are_auckland_written_in_utc_and_past_midnight_ends_next_day(self):
        lines = unfold(share.calendar([(NIGHT, NIGHT["start_date"], "https://x/l/1")], "t").decode())
        self.assertIn("DTSTART:20990306T083000Z", lines)  # 21:30 NZDT (+13) is 08:30 UTC
        self.assertIn("DTEND:20990306T120000Z", lines)  # 01:00 the next morning
        self.assertIn("SUMMARY:Kava\\, poetry\\; and a long night of verse with friends from all over Tāmaki Makaurau", lines)

    def test_all_day_spans_end_the_day_after(self):
        lines = unfold(share.calendar([(RETREAT, RETREAT["start_date"], "u")], "t").decode())
        self.assertIn("DTSTART;VALUE=DATE:20990703", lines)
        self.assertIn("DTEND;VALUE=DATE:20990706", lines)

    def test_lines_fold_at_75_bytes_without_splitting_a_letter(self):
        raw = share.calendar([(NIGHT, NIGHT["start_date"], "u")], "t")
        for ln in raw.split(b"\r\n"):
            self.assertLessEqual(len(ln), 75)
            ln.decode()  # each piece is whole UTF-8

    def test_a_repeating_listing_carries_each_date_ahead(self):
        self.assertEqual(share.dates_for_feed({**RETREAT, "repeats_on": ["2099-07-03", "2099-07-10"]}), ["2099-07-03", "2099-07-10"])
        self.assertEqual(share.dates_for_feed({**RETREAT, "next_date": "2099-07-10"}), ["2099-07-10"])


class Served(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        store.DB = TMP / "served.db"
        db = store.connect()
        for rec in (NIGHT, RETREAT, WAITING):
            store.put(db, json.loads(json.dumps(rec)))
        cls.port = free_port()
        env = {**os.environ, "WHEEL_GATE_PATTERNS": str(FIXTURE), "WHEEL_API_ONLY": "1", "EVENTHUB_DB": str(store.DB),
               "WHEEL_ZK_URL": "http://127.0.0.1:9", "WHEEL_SITE": "https://site.example/thewheel/"}
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

    def get(self, path):
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{self.port}{path}", timeout=10) as r:
                return r.status, r.headers, r.read().decode()
        except urllib.error.HTTPError as e:
            return e.code, e.headers, e.read().decode()

    def test_share_page_previews_and_sends_people_on(self):
        code, _, body = self.get(f"/l/{NIGHT['id']}")
        self.assertEqual(code, 200)
        self.assertIn('property="og:title" content="Kava, poetry; and a long night', body)
        self.assertIn(f'url=https://site.example/thewheel/#l/{NIGHT["id"]}', body)
        self.assertNotIn("signal.group", body)  # a group's link is for signed-in members
        self.assertNotIn("f" * 16, body)  # nor who added it
        self.assertNotIn("noindex", body)
        self.assertIn("noindex", self.get(f"/l/{WAITING['id']}")[2])  # waiting for review: kept out of search
        self.assertEqual(self.get(f"/l/{'9' * 16}")[0], 404)

    def test_calendar_file_and_feeds(self):
        code, h, body = self.get(f"/api/ics/{NIGHT['id']}.ics")
        self.assertEqual((code, h["Content-Type"].split(";")[0]), (200, "text/calendar"))
        self.assertIn("attachment", h["Content-Disposition"])
        self.assertIn(f"URL:http://127.0.0.1:{self.port}/l/{NIGHT['id']}", unfold(body))
        _, _, feed = self.get("/api/feed.ics?mode=recovery")
        self.assertIn("Rest weekend", feed)
        self.assertNotIn("Kava", feed)
        _, _, everything = self.get("/api/feed.ics")
        self.assertNotIn("Beach clean", everything)  # feeds carry checked listings only
        code, h, rss = self.get("/api/feed.xml?mode=night")
        self.assertEqual((code, h["Content-Type"].split(";")[0]), (200, "application/rss+xml"))
        self.assertIn("<title>The Wheel · Night</title>", rss)
        self.assertNotIn("signal.group", rss)

    def test_the_list_says_when_it_was_made(self):
        with urllib.request.urlopen(f"http://127.0.0.1:{self.port}/api/events", timeout=10) as r:
            self.assertIn("at", json.load(r))

    def test_reporting_needs_a_member(self):
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}/api/report/{NIGHT['id']}", method="POST",
                                     data=b'{"reason": "over"}', headers={"content-type": "application/json"})
        with self.assertRaises(urllib.error.HTTPError) as e:
            urllib.request.urlopen(req, timeout=10)
        self.assertEqual(e.exception.code, 401)


class Reports(unittest.TestCase):
    def setUp(self):
        store.DB = TMP / f"r-{self.id()}.db"
        server._local.__dict__.clear()  # a fresh connection to this test's store
        server.GATE = gate.load(FIXTURE, builtin=False)
        self.db = server.db()
        store.put(self.db, json.loads(json.dumps(NIGHT)))

    def report(self, acct, tier, reason="over", note=None):
        return server.file_report(store.get(self.db, NIGHT["id"]), acct, tier, reason, note, "2026-10-22")

    def test_two_new_members_leave_it_three_send_it_back(self):
        self.assertFalse(self.report("a" * 16, 0))
        self.assertFalse(self.report("b" * 16, 0))
        self.assertFalse(self.report("b" * 16, 0))  # reporting again replaces the first
        self.assertTrue(self.report("c" * 16, 0, "wrong", "Call 021 555 1234 for the real date"))
        rec = store.get(self.db, NIGHT["id"])
        self.assertEqual((rec["review"]["state"], rec["round"], rec["reopened"]), ("pending", 1, True))
        notes = [r["note"] for r in server.reported(rec) if r["note"]]
        self.assertEqual(notes, ["Call [number] for the real date"])  # numbers out before reviewers read it

    def test_one_regular_sends_it_back_and_old_reviews_stop_counting(self):
        store.cast_review(self.db, NIGHT["id"], "d" * 16, "approve", rep.WEIGHT[2], "2026-10-20")
        self.assertTrue(self.report("e" * 16, 1))
        rec = server.settle(store.get(self.db, NIGHT["id"]))
        self.assertEqual((rec["review"]["state"], rec["certainty"]["reviews"]), ("pending", 0))  # a fresh round
        store.cast_review(self.db, NIGHT["id"], "d" * 16, "reject", rep.WEIGHT[2], "2026-10-22", rec["round"])
        self.assertEqual(server.settle(rec)["review"]["state"], "rejected")

    def test_a_waiting_listing_keeps_waiting(self):
        store.put(self.db, json.loads(json.dumps(WAITING)))
        rec = store.get(self.db, WAITING["id"])
        self.assertFalse(server.file_report(rec, "e" * 16, 3, "unsafe", None, "2026-10-22"))
        self.assertEqual(len(store.reports_for(self.db, WAITING["id"])), 1)
        store.close_reports(self.db, WAITING["id"])
        self.assertEqual(store.reports_for(self.db, WAITING["id"]), [])


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


if __name__ == "__main__":
    unittest.main()
