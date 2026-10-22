"""The public moderation log and appeals (2026-10-22): lines by role, listings named only while on the list; a
turned-down listing appealed once, to fresh reviewers; a rank reset appealed to the stewards.

    /usr/bin/python3 -E -s -m unittest tests/test_modlog.py
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "tests" / "fixtures" / "gate-patterns.txt"
TMP = Path(tempfile.mkdtemp(prefix="wheel-modlog-"))
sys.path.insert(0, str(ROOT))
from hub import gate, rep, server, store  # noqa: E402

A, B, C = "a" * 16, "b" * 16, "c" * 16
LIVE = {"id": "1" * 16, "name": "Kava circle", "start_date": "2099-03-06", "modes": ["night"], "review": {"state": "approved"}}
DOWN = {"id": "2" * 16, "name": "Spam party", "start_date": "2099-03-06", "modes": ["night"], "review": {"state": "rejected"},
        "deposited_account": A}


class Base(unittest.TestCase):
    def setUp(self):
        store.DB = TMP / f"{self.id()}.db"
        server._local.__dict__.clear()
        server.GATE = gate.load(FIXTURE, builtin=False)
        self.db = server.db()
        for r in (LIVE, DOWN):
            store.put(self.db, json.loads(json.dumps(r)))


class Log(Base):
    def test_lines_by_role_with_names_only_while_listed(self):
        store.log(self.db, "checked", LIVE["id"])
        store.log(self.db, "turned_down", DOWN["id"])
        store.log(self.db, "fixed", LIVE["id"], by="Reviewer", fields=["price", "start_date", "start_time"])
        store.log(self.db, "kind_merged", a="breath work", c="breathwork")
        text = [e["text"] for e in server.log_entries(None)["entries"]]
        self.assertEqual(text, ["A Steward merged the kind “breath work” into “breathwork”.",
                                "A Reviewer fixed the price, the date, the start time on “Kava circle”.",
                                "Reviews turned down a listing.", "Reviews checked “Kava circle”."][::-1][::-1])
        self.assertNotIn("Spam party", json.dumps(server.log_entries(None)))
        self.assertNotIn(A, json.dumps([dict(r) for r in self.db.execute("SELECT * FROM modlog")]))  # no pen names kept

    def test_a_line_carrying_a_private_mark_is_left_out(self):
        store.log(self.db, "area_added", name="fakename")  # the fixture's private word
        store.log(self.db, "area_added", name="Orewa")
        self.assertEqual([e["text"] for e in server.log_entries(None)["entries"]], ["A Steward added the area Orewa."])

    def test_paging(self):
        for i in range(105):
            store.log(self.db, "area_added", name=f"Area {i}")
        first = server.log_entries(None)
        self.assertEqual((len(first["entries"]), first["more"]), (100, True))
        rest = server.log_entries(first["entries"][-1]["id"])
        self.assertEqual((len(rest["entries"]), rest["more"]), (5, False))


class Appeals(Base):
    def test_once_by_its_adder_then_fresh_reviewers(self):
        store.cast_review(self.db, DOWN["id"], B, "reject", rep.WEIGHT[2], "2026-10-20")
        rec = store.get(self.db, DOWN["id"])
        self.assertEqual(server.file_appeal(rec, C, "x"), "Only the member who added a listing can appeal it.")
        self.assertIsNone(server.file_appeal(rec, A, "It's real: call 021 555 1234"))
        rec = store.get(self.db, DOWN["id"])
        self.assertEqual((rec["review"]["state"], rec["round"], rec["appeal_note"]), ("pending", 1, "It's real: call [number]"))
        self.assertTrue(server.steps_aside(rec, B))  # reviewed it before: others look now
        self.assertFalse(server.steps_aside(rec, C))
        self.assertEqual(server.settle(rec)["certainty"]["reviews"], 0)
        rec["review"] = {"state": "rejected"}
        store.put(self.db, rec, "rejected")
        self.assertEqual(server.file_appeal(store.get(self.db, DOWN["id"]), A, None), "This listing has had its appeal.")
        self.assertEqual(server.file_appeal(store.get(self.db, LIVE["id"]), A, None), "Only the member who added a listing can appeal it.")

    def test_rank_appeal_restored(self):
        store.ensure_account(self.db, A)
        self.db.execute("UPDATE accounts SET reset_day='2026-10-21' WHERE account=?", (A,)); self.db.commit()
        store.appeal_rank(self.db, A, "a mistake", "2026-10-22")
        store.appeal_rank(self.db, A, "a mistake, again", "2026-10-22")  # one open appeal at a time
        ap = store.appeals(self.db)
        self.assertEqual([x["note"] for x in ap], ["a mistake, again"])
        store.close_appeal(self.db, ap[0]["id"], "restored")
        self.assertIsNone(self.db.execute("SELECT reset_day FROM accounts WHERE account=?", (A,)).fetchone()["reset_day"])
        self.assertEqual(store.appeals(self.db), [])


if __name__ == "__main__":
    unittest.main()
