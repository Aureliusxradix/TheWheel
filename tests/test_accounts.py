"""Accounts as currency (his "Do A-F", 2026-10-22): New reviews settle nothing alone, the active count, the join work.

    /usr/bin/python3 -E -s -m unittest tests/test_accounts.py
"""
import hashlib
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
TMP = Path(tempfile.mkdtemp(prefix="wheel-accounts-"))
sys.path.insert(0, str(ROOT))
from hub import rep, store  # noqa: E402

NEW, REGULAR, REVIEWER = rep.WEIGHT[0], rep.WEIGHT[1], rep.WEIGHT[2]


class Settling(unittest.TestCase):
    def test_new_reviews_alone_stay_pending(self):
        for n in (1, 6, 40):
            c_for, _ = rep.certainty([NEW] * n, [])
            self.assertLessEqual(c_for, rep.NEW_CAP)
            self.assertEqual(rep.settled_state(c_for, 0), "pending")
        _, c_against = rep.certainty([], [NEW] * 10)
        self.assertEqual(rep.settled_state(0, c_against), "pending")  # the same either way: no turning a listing down alone

    def test_a_regular_or_above_settles_it(self):
        self.assertEqual(rep.settled_state(*rep.certainty([NEW] * 6 + [REGULAR], [])), "approved")
        self.assertEqual(rep.settled_state(*rep.certainty([REVIEWER], [])), "approved")
        self.assertEqual(rep.certainty([REGULAR, REGULAR], []), (0.64, 0.0))  # unchanged without New reviews

    def test_active_counts_regular_and_up(self):
        store.DB = TMP / "active.db"
        db = store.connect()
        for a in ("a" * 16, "b" * 16, "c" * 16):
            store.ensure_account(db, a)
        db.execute("UPDATE accounts SET steward=1 WHERE account=?", ("a" * 16,))
        db.execute("UPDATE accounts SET granted_tier=2 WHERE account=?", ("b" * 16,))
        db.commit()
        self.assertEqual(rep.active(db), 2)


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def solve(nonce, commitment, bits):
    n = 0
    while True:
        d = hashlib.sha256(f"{nonce}:{commitment}:{n}".encode()).digest()
        if int.from_bytes(d, "big") >> (256 - bits) == 0:
            return n
        n += 1


class Served(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        store.DB = TMP / "served.db"
        store.connect()
        cls.port = free_port()
        env = {**os.environ, "WHEEL_GATE_PATTERNS": str(FIXTURE), "WHEEL_API_ONLY": "1", "EVENTHUB_DB": str(store.DB),
               "WHEEL_ZK_URL": "http://127.0.0.1:9", "WHEEL_JOIN_WORK_BITS": "10"}
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

    def post(self, path, body):
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}", data=json.dumps(body).encode(), method="POST",
                                     headers={"content-type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return r.status, json.load(r)
        except urllib.error.HTTPError as e:
            return e.code, json.load(e)

    def test_join_needs_the_work_once(self):
        _, w = self.post("/api/zk/join-work", {})
        self.assertEqual(w["bits"], 10)
        c = "12345"
        self.assertEqual(self.post("/api/zk/join", {"commitment": c}), (400, {"ok": False, "why": "work"}))
        _, w = self.post("/api/zk/join-work", {})
        bad = solve(w["nonce"], "99999", 10)  # work done for another key
        self.assertEqual(self.post("/api/zk/join", {"commitment": c, "work": {"nonce": w["nonce"], "n": bad}})[0], 400)
        _, w = self.post("/api/zk/join-work", {})
        work = {"nonce": w["nonce"], "n": solve(w["nonce"], c, 10)}
        code, _ = self.post("/api/zk/join", {"commitment": c, "work": work})
        self.assertEqual(code, 503)  # past the hub's check, on to the member service (offline in this test)
        self.assertEqual(self.post("/api/zk/join", {"commitment": c, "work": work})[1], {"ok": False, "why": "work"})  # used

    def test_active_is_served(self):
        with urllib.request.urlopen(f"http://127.0.0.1:{self.port}/api/active", timeout=10) as r:
            self.assertEqual(json.load(r), {"active": 0})


if __name__ == "__main__":
    unittest.main()
