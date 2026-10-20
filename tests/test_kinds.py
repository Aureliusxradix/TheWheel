"""Kinds kept tidy: suggestions, merges a steward makes, kinds shown merged, listings keeping their own words.

    /usr/bin/python3 -E -s -m unittest tests/test_kinds.py
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
TMP = Path(tempfile.mkdtemp(prefix="wheel-kinds-"))
sys.path.insert(0, str(ROOT))
from hub import kinds, store  # noqa: E402


class Suggest(unittest.TestCase):
    def test_three_kinds_of_twin(self):
        got = {(s["merge"], s["keep"]): s["why"] for s in kinds.suggest(
            {"breathwork": 2, "breath work": 1, "meditaton": 1, "meditation": 9, "dj": 2, "dj sets": 1, "yoga": 2}, set())}
        self.assertEqual(got[("breath work", "breathwork")], "same")
        self.assertEqual(got[("meditaton", "meditation")], "close")
        self.assertEqual(got[("dj sets", "dj")], "inside")
        self.assertNotIn("yoga", {k for pair in got for k in pair})

    def test_kept_apart_is_remembered(self):
        got = kinds.suggest({"dance": 7, "ecstatic dance": 7}, {("dance", "ecstatic dance")})
        self.assertEqual(got, [])

    def test_apply_keeps_order_and_drops_repeats(self):
        self.assertEqual(kinds.apply(["breath work", "yoga", "breathwork"], {"breath work": "breathwork"}), ["breathwork", "yoga"])


class Store(unittest.TestCase):
    def setUp(self):
        store.DB = TMP / f"s-{self.id()}.db"
        self.db = store.connect()

    def test_chains_are_followed_and_loops_refused(self):
        store.merge_tag(self.db, "dj sets", "dj")
        store.merge_tag(self.db, "dj", "djs")
        self.assertEqual(store.merges(self.db)["dj sets"], "djs")
        with self.assertRaises(ValueError):
            store.merge_tag(self.db, "djs", "dj sets")
        store.unmerge_tag(self.db, "dj")
        self.assertEqual(store.merges(self.db), {"dj sets": "dj"})


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Served(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        store.DB = TMP / "served.db"
        db = store.connect()
        store.put(db, {"id": "a" * 16, "name": "Breath night", "start_date": "2099-01-01", "modes": ["night"],
                       "tags": ["breath work", "sound bath"], "review": {"state": "approved"}})
        store.merge_tag(db, "breath work", "breathwork")
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

    def test_shown_merged_but_kept_whole(self):
        with urllib.request.urlopen(f"http://127.0.0.1:{self.port}/api/events", timeout=10) as r:
            d = json.load(r)
        self.assertEqual(d["events"][0]["tags"], ["breathwork", "sound bath"])
        self.assertIn(["breathwork", 1], d["tags"])
        self.assertEqual(store.get(store.connect(), "a" * 16)["tags"], ["breath work", "sound bath"])

    def test_only_stewards_reach_the_kinds_tools(self):
        for method, data in (("GET", None), ("POST", b'{"action":"merge","merge":"a","keep":"b"}')):
            req = urllib.request.Request(f"http://127.0.0.1:{self.port}/api/kinds", data=data, method=method,
                                         headers={"content-type": "application/json"})
            with self.assertRaises(urllib.error.HTTPError) as cm:
                urllib.request.urlopen(req, timeout=10)
            self.assertEqual(cm.exception.code, 401)


if __name__ == "__main__":
    unittest.main()
