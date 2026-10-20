"""Flyers: cleaned of everything but pixels, served only while a listing uses them; links must be web addresses.

    /usr/bin/python3 -E -s -m unittest tests/test_flyer.py
"""
import io
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
TMP = Path(tempfile.mkdtemp(prefix="wheel-flyer-"))
os.environ["EVENTHUB_DB"] = str(TMP / "hub.db")
sys.path.insert(0, str(ROOT))
from PIL import Image  # noqa: E402

from hub import flyer, store  # noqa: E402


def photo_with_gps() -> bytes:
    im = Image.new("RGB", (2400, 1200), (40, 120, 60))
    exif = Image.Exif()
    exif[0x010F] = "PhoneMaker"                                       # Make
    gps = {1: "S", 2: (36.0, 50.0, 0.0), 3: "E", 4: (174.0, 45.0, 0.0)}  # a GPS fix
    exif[0x8825] = gps
    out = io.BytesIO()
    im.save(out, "JPEG", exif=exif.tobytes())
    return out.getvalue()


class Clean(unittest.TestCase):
    def test_control_the_photo_carries_gps(self):
        with Image.open(io.BytesIO(photo_with_gps())) as im:
            self.assertIn(0x8825, im.getexif())

    def test_cleaned_flyer_carries_nothing_but_pixels(self):
        data = flyer.clean(photo_with_gps())
        with Image.open(io.BytesIO(data)) as im:
            self.assertEqual(im.format, "WEBP")
            self.assertEqual(len(im.getexif()), 0)
            self.assertNotIn("exif", im.info)
            self.assertNotIn("icc_profile", im.info)
            self.assertLessEqual(max(im.size), flyer.MAX_SIDE)
        self.assertNotIn(b"PhoneMaker", data)


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Serve(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        store.DB = TMP / "hub.db"  # its own store, also when run beside other test files
        folder = TMP / "uploads" / "flyers"
        cls.used = flyer.keep(folder, flyer.clean(photo_with_gps()))
        cls.unused = flyer.keep(folder, flyer.clean(photo_with_gps()[:-2] + b"\xff\xd9"))
        db = store.connect()
        store.put(db, {"id": "a" * 16, "name": "Forest day", "start_date": "2099-01-01", "modes": ["day"], "tags": [],
                       "source": {"kind": "flyer", "flyer": cls.used}, "review": {"state": "pending"}})
        cls.port = free_port()
        env = {**os.environ, "WHEEL_GATE_PATTERNS": str(FIXTURE), "WHEEL_API_ONLY": "1", "WHEEL_DATA": str(TMP), "EVENTHUB_DB": str(store.DB),
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

    def get(self, path):
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{self.port}{path}", timeout=10) as r:
                return r.status, r.headers.get("Content-Type")
        except urllib.error.HTTPError as e:
            return e.code, None

    def test_a_used_flyer_is_served(self):
        self.assertEqual(self.get(f"/api/flyer/{self.used}"), (200, "image/webp"))

    def test_a_flyer_no_listing_uses_is_not(self):
        if self.unused != self.used:
            self.assertEqual(self.get(f"/api/flyer/{self.unused}")[0], 404)
        self.assertEqual(self.get("/api/flyer/../hub.db")[0], 404)


class Links(unittest.TestCase):
    def test_links_must_be_web_addresses(self):
        from hub import server
        base = {"modes": ["day"], "start_date": "2099-01-01"}
        self.assertEqual(server.clean(dict(base), {"website": "https://example.org/e"})["website"], "https://example.org/e")
        for bad in ("javascript:alert(1)", "example.org", "https://a b"):
            with self.assertRaises(ValueError):
                server.clean(dict(base), {"website": bad})


if __name__ == "__main__":
    unittest.main()
