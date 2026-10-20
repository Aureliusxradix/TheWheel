"""The identity gate and the going-live rules of the API (threat profile F3, F4).

    /usr/bin/python3 -E -s -m unittest tests/test_gate.py

Uses a made-up word list (tests/fixtures/gate-patterns.txt); the real one is private and is kept out of this repository.
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
TMP = tempfile.mkdtemp(prefix="wheel-gate-")
os.environ["EVENTHUB_DB"] = str(Path(TMP) / "hub.db")
sys.path.insert(0, str(ROOT))
from hub import gate, store  # noqa: E402

SITE = "https://site.example"


def event(eid, name, **more):
    return {"id": eid, "name": name, "start_date": "2099-01-01", "modes": ["day"], "tags": ["kava"],
            "review": {"state": "pending"}, **more}


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def call(port, path, method="GET", origin=None):
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", method=method, headers={"Origin": origin} if origin else {})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, dict(r.headers), r.read()
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), e.read()


class GateRules(unittest.TestCase):
    def test_refuses_a_missing_or_short_list(self):
        with self.assertRaises(gate.GateMissing):
            gate.load(Path(TMP) / "nothing-here.txt")
        short = Path(TMP) / "short.txt"
        short.write_text("onlyone\n")
        with self.assertRaises(gate.GateMissing):
            gate.load(short)

    def test_hits_and_misses(self):
        rx = gate.load(FIXTURE)
        self.assertEqual(gate.hit(rx, "Hosted by Fakename Person"), "Fakename")
        self.assertEqual(gate.hit(rx, b"see /root/notes"), "/root/")
        self.assertIsNone(gate.hit(rx, json.dumps({"tags": [["kava", 3], ["sound bath", 1]]})))  # nested lists are not links

    def test_tree_selftest_bites(self):
        tree = Path(tempfile.mkdtemp(dir=TMP))
        (tree / "index.html").write_text("<p>The Wheel</p>")
        env = {**os.environ, "WHEEL_GATE_PATTERNS": str(FIXTURE)}
        run = lambda *a: subprocess.run([sys.executable, "-E", "-s", str(ROOT / "hub" / "gate.py"), *a], env=env, capture_output=True)
        self.assertEqual(run(str(tree)).returncode, 0)
        self.assertEqual(run("--selftest", str(tree)).returncode, 0)
        (tree / "app.js").write_text("// by fakename")
        self.assertEqual(run(str(tree)).returncode, 1)
        (tree / "app.js").unlink()
        (tree / "hub.db").write_bytes(b"x")
        self.assertEqual(run(str(tree)).returncode, 1)


class ApiOnly(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        store.DB = Path(TMP) / "hub.db"  # its own store, also when run beside other test files
        db = store.connect()
        store.put(db, event("a" * 16, "Kava circle", deposited_by="Someone Real", deposited_account="0123456789abcdef"))
        store.put(db, event("b" * 16, "Open mic with Fakename"))
        cls.port = free_port()
        env = {**os.environ, "WHEEL_GATE_PATTERNS": str(FIXTURE), "WHEEL_API_ONLY": "1", "WHEEL_ORIGINS": SITE,
               "WHEEL_ZK_URL": "http://127.0.0.1:9", "WHEEL_JOINS_PER_DAY": "2", "EVENTHUB_DB": str(store.DB)}
        cls.proc = subprocess.Popen([sys.executable, "-E", "-s", str(ROOT / "hub" / "server.py"), "--port", str(cls.port)],
                                    env=env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        for _ in range(50):
            try:
                socket.create_connection(("127.0.0.1", cls.port), 0.2).close()
                break
            except OSError:
                time.sleep(0.1)

    @classmethod
    def tearDownClass(cls):
        cls.proc.terminate()
        cls.err = cls.proc.communicate(timeout=10)[1].decode()

    def test_listing_with_a_private_mark_is_held(self):
        code, _, body = call(self.port, "/api/events")
        self.assertEqual(code, 200)
        names = [e["name"] for e in json.loads(body)["events"]]
        self.assertEqual(names, ["Kava circle"])

    def test_who_added_a_listing_never_leaves(self):
        for path in ("/api/events", "/api/review"):
            _, _, body = call(self.port, path)
            self.assertNotIn(b"deposited", body)
            self.assertNotIn(b"Someone Real", body)

    def test_cors_only_for_the_site(self):
        _, h, _ = call(self.port, "/api/events", origin=SITE)
        self.assertEqual(h.get("Access-Control-Allow-Origin"), SITE)
        _, h, _ = call(self.port, "/api/events", origin="https://elsewhere.example")
        self.assertNotIn("Access-Control-Allow-Origin", h)
        code, h, _ = call(self.port, "/api/submit", "OPTIONS", origin=SITE)
        self.assertEqual((code, h.get("Access-Control-Allow-Origin")), (204, SITE))
        code, _, _ = call(self.port, "/api/submit", "OPTIONS", origin="https://elsewhere.example")
        self.assertEqual(code, 404)

    def test_api_only_serves_no_pages(self):
        for path in ("/", "/app.js", "/__wait?ms=1", "/selftest.html"):
            self.assertEqual(call(self.port, path)[0], 404, path)

    def test_server_header_names_no_software(self):
        _, h, _ = call(self.port, "/api/areas")
        self.assertEqual(h.get("Server"), "TheWheel")

    def test_whole_site_join_cap(self):
        codes = []
        for _ in range(3):
            req = urllib.request.Request(f"http://127.0.0.1:{self.port}/api/zk/join", data=b'{"commitment": "5"}',
                                         method="POST", headers={"content-type": "application/json"})
            try:
                codes.append(urllib.request.urlopen(req, timeout=10).status)
            except urllib.error.HTTPError as e:
                codes.append(e.code)
        self.assertEqual(codes[2], 429)  # the first two reach the (absent) member service; the third is capped
        self.assertNotIn(429, codes[:2])

    def test_refuses_to_start_without_the_list(self):
        env = {**os.environ, "WHEEL_GATE_PATTERNS": str(Path(TMP) / "gone.txt")}
        r = subprocess.run([sys.executable, "-E", "-s", str(ROOT / "hub" / "server.py"), "--port", str(free_port())],
                           env=env, capture_output=True, timeout=20)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn(b"will not start", r.stderr)


if __name__ == "__main__":
    unittest.main()
