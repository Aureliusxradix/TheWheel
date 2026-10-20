"""Listings from group chats: group links told from links to a person, announcements cleaned, links to members only.

    /usr/bin/python3 -E -s -m unittest tests/test_chats.py
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
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "tests" / "fixtures" / "gate-patterns.txt"
TMP = Path(tempfile.mkdtemp(prefix="wheel-chats-"))
sys.path.insert(0, str(ROOT))
from hub import chats, server, store  # noqa: E402

MSG = """[21/10/2026, 9:14 am] Jane Doe: Kava circle this Friday 7pm at the hall!
Text me on 021 123 4567 or +64 21 987 6543, or email jane@example.org. Thanks @Mike_R
Join: https://chat.whatsapp.com/AbCdEfGhIjKlMnOp or wa.me/64211234567
Koha $15, 2026-10-24, doors 19:30"""
REC = {"id": "c" * 16, "name": "Kava circle", "start_date": "2099-01-01", "modes": ["night"], "review": {"state": "approved"}}


class Links(unittest.TestCase):
    def test_groups_and_people(self):
        for url, want in (("https://signal.group/#CjQKIabc", ("group", "signal")),
                          ("https://chat.whatsapp.com/AbCdEfGhIjKlMnOp", ("group", "whatsapp")),
                          ("https://t.me/+AbCdEfGhIj", ("group", "telegram")), ("https://discord.gg/abc12", ("group", "discord")),
                          ("https://wa.me/64211234567", ("person", "whatsapp")), ("https://signal.me/#eu/abc", ("person", "signal")),
                          ("https://t.me/someone", ("person", "telegram")), ("https://example.org/event", None)):
            self.assertEqual(chats.classify(url), want, url)


class Clean(unittest.TestCase):
    def test_names_numbers_handles_and_chat_links_out(self):
        got = chats.scrub(MSG)
        for gone in ("Jane Doe", "021 123", "987 6543", "jane@example.org", "@Mike_R", "chat.whatsapp", "wa.me"):
            self.assertNotIn(gone, got)
        for kept in ("Kava circle this Friday 7pm", "Koha $15, 2026-10-24, doors 19:30"):
            self.assertIn(kept, got)
        self.assertEqual(chats.scrub(got), got)  # cleaning twice changes nothing

    def test_seen_as_a_chat_and_its_group_link_found(self):
        self.assertTrue(chats.is_chat(MSG))
        self.assertFalse(chats.is_chat("Sound bath at the hall, Saturday 2pm. https://example.org/sound"))
        self.assertEqual(chats.group_links(MSG), [("whatsapp", "https://chat.whatsapp.com/AbCdEfGhIjKlMnOp")])

    def test_reader_links_sorted(self):
        r = chats.sort_links({"website": "https://signal.group/#CjQKIabc", "tickets_url": "https://wa.me/6421"})
        self.assertEqual((r.get("website"), r.get("tickets_url"), r["chat_link"], r["chat_platform"]),
                         (None, None, "https://signal.group/#CjQKIabc", "signal"))


class Rules(unittest.TestCase):
    def test_a_group_link_needs_the_organisers_ok(self):
        with self.assertRaises(ValueError):
            server.clean(dict(REC), {"chat_link": "https://signal.group/#CjQKIabc"})
        got = server.clean(dict(REC), {"chat_platform": "whatsapp", "chat_link": "https://signal.group/#CjQKIabc", "chat_link_ok": True})
        self.assertEqual(got["chat_platform"], "signal")  # the link names its app

    def test_person_links_and_group_links_in_the_wrong_field_refused(self):
        for edits in ({"chat_link": "https://wa.me/6421", "chat_link_ok": True}, {"website": "https://chat.whatsapp.com/AbCdEfGhIjKlMnOp"},
                      {"website": "https://t.me/someone"}, {"chat_link": "https://example.org", "chat_link_ok": True}):
            with self.assertRaises(ValueError, msg=edits):
                server.clean(dict(REC), edits)

    def test_the_announcement_is_cleaned_when_edited(self):
        got = server.clean(dict(REC), {"chat_text": "Ring 021 555 1234 to come"})
        self.assertEqual(got["chat_text"], "Ring [number] to come")


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Served(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        store.DB = TMP / "served.db"
        db = store.connect()
        store.put(db, {**REC, "chat_platform": "whatsapp", "chat_link": "https://chat.whatsapp.com/AbCdEfGhIjKlMnOp",
                       "chat_link_ok": True, "chat_text": "Kava circle this Friday 7pm"})
        store.put(db, {**REC, "id": "d" * 16, "chat_platform": "whatsapp", "chat_link": "https://chat.whatsapp.com/AbCdEfGhIjKlMnOp",
                       "chat_link_ok": True, "chat_text": "Kava circle", "review": {"state": "pending"}})
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

    def get(self, path, token=None):
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}", headers={"Authorization": f"Bearer {token}"} if token else {})
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.read().decode()

    def test_visitors_learn_there_is_a_group_and_nothing_more(self):
        for path in ("/api/events", "/api/review"):
            for token in (None, "not-a-session"):  # a token the member service refuses counts as no sign-in
                body = self.get(path, token)
                self.assertNotIn("chat.whatsapp.com", body, path)
                self.assertNotIn("Kava circle this Friday", body, path)
                ev = json.loads(body)["events"][0]
                self.assertTrue(ev["chat_link_hidden"] and ev["chat_text_hidden"])
                self.assertEqual(ev["chat_platform"], "whatsapp")


if __name__ == "__main__":
    unittest.main()
