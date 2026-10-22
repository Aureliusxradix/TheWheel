"""Supporters and profiles (his calls 2026-10-22): codes and months, the profile and its audiences, the look-alike
band, Monero orders matched by the watcher, and what the store refuses to keep.

    /usr/bin/python3 -E -s -m unittest tests/test_support.py
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
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "tests" / "fixtures" / "gate-patterns.txt"
TMP = Path(tempfile.mkdtemp(prefix="wheel-support-"))
sys.path.insert(0, str(ROOT))
from hub import store, support  # noqa: E402

A, B = "a" * 16, "b" * 16


def fresh(name):
    store.DB = TMP / f"{name}.db"
    db = store.connect()
    for acct in (A, B):
        store.ensure_account(db, acct)
    return db


class Codes(unittest.TestCase):
    def test_a_code_adds_months_once(self):
        db = fresh("codes")
        c = support.make_codes(db, 1, 1, "cash")[0]
        self.assertRegex(c, r"^WHEEL-[A-Z2-9]{4}-[A-Z2-9]{4}-[A-Z2-9]{4}$")
        got = support.redeem(db, A, c.lower().replace("-", " "))  # typed loosely still counts
        self.assertEqual(got, (support.add_months(date.today(), 1) - timedelta(days=1)).isoformat())
        self.assertIsNone(support.redeem(db, B, c))  # used
        self.assertTrue(support.active(db, A) and not support.active(db, B))
        self.assertEqual(support.count(db), 1)

    def test_months_stack_and_the_store_keeps_no_join(self):
        db = fresh("stack")
        c1, c2 = support.make_codes(db, 6, 2)
        first = support.redeem(db, A, c1)
        second = support.redeem(db, A, c2)
        self.assertEqual(second, (support.add_months(date.fromisoformat(first) + timedelta(days=1), 6) - timedelta(days=1)).isoformat())
        cols = {r["name"] for r in db.execute("PRAGMA table_info(codes)")}
        self.assertNotIn("account", cols)  # a used code keeps its day, never who used it
        self.assertNotIn(c1, json.dumps([dict(r) for r in db.execute("SELECT * FROM codes")]))  # fingerprints only

    def test_bad_months_refused(self):
        with self.assertRaises(ValueError):
            support.make_codes(fresh("bad"), 3, 1)


class Profiles(unittest.TestCase):
    def test_links_numbers_and_handles_stay_off(self):
        for bad in ("find me at insta.com/x", "call 021 555 1234", "@riverkai", "me@example.com", "https://x.nz"):
            with self.assertRaises(ValueError):
                support.clean_profile({"about": {"v": bad, "a": "all"}})
        p = support.clean_profile({"name": {"v": "Tidewalker", "a": "all"}, "about": {"v": "Sound and rope work.", "a": "bogus"}})
        self.assertEqual(p["about"]["a"], "me")  # an unknown audience falls to the narrowest

    def test_audiences_and_quiet_looks(self):
        p = support.clean_profile({"name": {"v": "T", "a": "all"}, "area": {"v": "Ponsonby", "a": "mem"},
                                   "about": {"v": "x", "a": "me"}, "status": {"v": "moon", "a": "all"},
                                   "mark": {"v": True, "a": "all"}, "look": {"colour": "bloom", "glyph": "tide"}})
        self.assertEqual(set(support.shown(p, "all", True, True)) - {"look"}, {"name", "status", "mark"})
        self.assertEqual(set(support.shown(p, "mem", True, True)) - {"look"}, {"name", "status", "mark", "area"})
        self.assertIn("about", support.shown(p, "me", True, True))
        lapsed = support.shown(p, "all", False, True)  # months ran out: the looks go quiet, the choice stays saved
        self.assertNotIn("status", lapsed)
        self.assertEqual(lapsed["look"], {"colour": "ink", "glyph": "ring"})
        self.assertNotIn("mark", support.shown(p, "all", True, False))  # below the floor, others see no mark
        self.assertIn("mark", support.shown(p, "me", True, False))

    def test_lookalike_bands(self):
        db = fresh("look")
        for i in range(6):
            store.ensure_account(db, f"{i:016x}")
            support.save_profile(db, f"{i:016x}", {"area": {"v": "Ponsonby", "a": "all"}})
        support.save_profile(db, A, {"area": {"v": "Ponsonby", "a": "all"}, "kinds": {"v": ["kava"], "a": "mem"}})
        got = support.lookalike(db, A)
        self.assertEqual(got, {"all": "5 to 19", "mem": "1 to 4"})


class Orders(unittest.TestCase):
    def test_unique_amounts_paid_once_then_gone(self):
        db = fresh("orders")
        o1 = support.open_order(db, 1, 5, 300.0)
        o2 = support.open_order(db, 1, 5, 300.0)
        self.assertNotEqual(o1["amount"], o2["amount"])
        self.assertEqual(o1["address"], support.XMR_ADDRESS)
        wl = {w["atomic"]: w["id"] for w in support.watch_list(db)}
        atomic = int(o1["amount"].replace(".", ""))
        self.assertGreaterEqual(atomic, int(5 / 300 * support.ATOMIC))
        self.assertEqual(support.watch_report(db, wl[atomic], 3), "seen")
        self.assertEqual(support.order_status(db, o1["token"])["state"], "seen")
        self.assertEqual(support.watch_report(db, wl[atomic], 10), "paid")
        st = support.order_status(db, o1["token"])
        self.assertRegex(st["code"], r"^WHEEL-")
        self.assertIsNone(support.order_status(db, o1["token"]))  # shown once, then the order is gone
        self.assertIsNotNone(support.redeem(db, A, st["code"]))
        self.assertEqual(store.fund_total(db)["raised"], o1["nzd"])  # a paid order counts toward The Wheel's own AI

    def test_order_limits(self):
        db = fresh("limits")
        for months, nzd in ((3, 5), (1, 1.5), (1, 5000)):
            with self.assertRaises(ValueError):
                support.open_order(db, months, nzd, 300.0)


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Served(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        db = fresh("served")
        support.save_profile(db, A, {"name": {"v": "Tidewalker", "a": "all"}, "area": {"v": "Ponsonby", "a": "mem"}})
        (TMP / "watch.token").write_text("w" * 40)
        cls.port = free_port()
        env = {**os.environ, "WHEEL_GATE_PATTERNS": str(FIXTURE), "WHEEL_API_ONLY": "1", "EVENTHUB_DB": str(store.DB),
               "WHEEL_ZK_URL": "http://127.0.0.1:9", "WHEEL_WATCH_TOKEN_FILE": str(TMP / "watch.token"), "WHEEL_XMR_NZD": "300"}
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

    def call(self, path, body=None, headers=None):
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}", method="POST" if body is not None else "GET",
                                     data=json.dumps(body).encode() if body is not None else None,
                                     headers={"content-type": "application/json", **(headers or {})})
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return r.status, json.load(r)
        except urllib.error.HTTPError as e:
            return e.code, json.load(e)

    def test_profile_as_everyone_sees_it(self):
        code, d = self.call(f"/api/p/{A}")
        self.assertEqual((code, d["viewer"], d["profile"].get("name"), "area" in d["profile"]), (200, "all", "Tidewalker", False))
        self.assertEqual(self.call(f"/api/p/{'c' * 16}")[0], 404)

    def test_monero_waits_for_the_watcher_then_runs(self):
        W = {"X-Wheel-Watch": "w" * 40}
        self.assertEqual(self.call("/api/support/order", {"months": 1, "nzd": 5})[0], 503)  # no watcher yet
        self.assertEqual(self.call("/api/support/watch", headers={"X-Wheel-Watch": "nope"})[0], 404)
        code, wl = self.call("/api/support/watch", headers=W)
        self.assertEqual((code, wl["orders"]), (200, []))
        self.assertTrue(self.call("/api/support")[1]["monero"])
        code, o = self.call("/api/support/order", {"months": 6, "nzd": 2})
        self.assertEqual(code, 200)
        oid = self.call("/api/support/watch", headers=W)[1]["orders"][0]["id"]
        self.assertEqual(self.call("/api/support/watch", {"id": oid, "confirmations": 12}, W)[1], {"state": "paid"})
        st = self.call(f"/api/support/order/{o['token']}")[1]
        self.assertRegex(st["code"], r"^WHEEL-")
        self.assertEqual(self.call(f"/api/support/order/{o['token']}")[0], 404)

    def test_member_routes_need_a_member(self):
        self.assertEqual(self.call("/api/profile")[0], 401)
        self.assertEqual(self.call("/api/support/redeem", {"code": "WHEEL-AAAA-AAAA-AAAA"})[0], 401)


if __name__ == "__main__":
    unittest.main()
