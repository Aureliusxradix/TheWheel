"""The reader on the server: a pasted link reaches the public internet only, and pasted text is never a file path.

    /usr/bin/python3 -E -s -m unittest tests/test_netguard.py
"""
import os
import subprocess
import sys
import threading
import unittest
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from reader import core  # noqa: E402  (installs the guard)


class Page(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"a private page")

    def log_message(self, *a):
        pass


class Guard(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = ThreadingHTTPServer(("127.0.0.1", 0), Page)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.url = f"http://127.0.0.1:{cls.srv.server_address[1]}/"

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()

    def test_private_address_refused(self):
        with self.assertRaises(Exception) as cm:
            core._fetch(self.url)
        self.assertIn("not on the public internet", str(cm.exception))

    def test_control_same_page_reachable_without_the_guard(self):
        code = f"import sys; sys.path.insert(0, {str(ROOT)!r}); from reader import core; print(core._fetch({self.url!r})[0].decode())"
        r = subprocess.run([sys.executable, "-E", "-s", "-c", code], capture_output=True, text=True,
                           env={**os.environ, "WHEEL_ALLOW_PRIVATE_FETCH": "1"}, timeout=30)
        self.assertEqual(r.stdout.strip(), "a private page")

    def test_pasted_path_is_text_on_the_server(self):
        d = core.Deposit("/etc/hostname", datetime.now(timezone.utc), allow_path=False)
        self.assertIsNone(d.path)
        self.assertIsNotNone(core.Deposit("/etc/hostname", datetime.now(timezone.utc)).path)  # the local tool still reads files


if __name__ == "__main__":
    unittest.main()
