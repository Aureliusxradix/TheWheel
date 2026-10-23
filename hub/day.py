"""Day's own, round three (his calls 2026-10-24, "I like the rest"): shifts you take under your pen name, an
organiser's standing crew, thanks that count, an ask board answered through The Wheel, and a skillshare swap.

Who sees what, ZKP first: everyone sees counts (slots filled, crew size, how many want to learn a thing). The organiser
holding a listing sees the pen names that took its slots and the pen names on its crew, nothing more. An ask's thread
is seen by its two sides only. Pen names are the members' own nullifier-derived ids; no name, number or email.
"""
import hashlib
import re
from datetime import date, timedelta

ASK_KINDS = {"lift": "A lift", "hands": "Hands", "borrow": "Something to borrow", "other": "Something else"}
ASKS_A_DAY, MSGS_A_DAY, SWAP_EACH_SIDE = 3, 30, 10
WORKSHOP_AT = 4  # learners on one topic before a teacher is offered a draft workshop


def _line(x, n: int) -> str:
    return re.sub(r"\s+", " ", str(x or "")).strip()[:n]


def slot_key(slot: dict) -> str:
    """A slot's own key, from its date, start and task, so a slot keeps its people while other slots change."""
    return hashlib.sha256(f"{slot.get('date')}|{slot.get('start') or ''}|{slot.get('task') or ''}".encode()).hexdigest()[:12]


def slots_of(rec: dict) -> dict:
    return {slot_key(s): s for s in rec.get("slots") or []}


# ---------- shifts ----------
def fill(db, rec: dict) -> list[dict]:
    """Each slot in order, with how many have taken it."""
    taken = {}
    for r in db.execute("SELECT slot, COUNT(*) n FROM shift_claims WHERE listing_id=? GROUP BY slot", (rec["id"],)):
        taken[r["slot"]] = r["n"]
    return [{"key": slot_key(s), "taken": taken.get(slot_key(s), 0)} for s in rec.get("slots") or []]


def take(db, rec: dict, key: str, account: str, today: str) -> None:
    s = slots_of(rec).get(key)
    if s is None:
        raise LookupError("That shift has changed. Reload the page.")
    if s["date"] < today:
        raise ValueError("That shift has already happened.")
    n = db.execute("SELECT COUNT(*) n FROM shift_claims WHERE listing_id=? AND slot=?", (rec["id"], key)).fetchone()["n"]
    if s.get("needed") and n >= s["needed"]:
        raise ValueError("That shift is full. Another slot, or ask the organiser.")
    db.execute("INSERT OR IGNORE INTO shift_claims(listing_id, slot, account, day) VALUES(?,?,?,?)", (rec["id"], key, account, today))
    db.commit()


def leave(db, rec: dict, key: str, account: str) -> None:
    db.execute("DELETE FROM shift_claims WHERE listing_id=? AND slot=? AND account=? AND thanked=0", (rec["id"], key, account))
    db.commit()


def mine(db, account: str) -> dict:
    return {"slots": [{"listing": r["listing_id"], "key": r["slot"], "thanked": bool(r["thanked"])}
                      for r in db.execute("SELECT * FROM shift_claims WHERE account=?", (account,))],
            "crews": [r["organiser_id"] for r in db.execute("SELECT organiser_id FROM crews WHERE account=?", (account,))],
            "swap": [{"topic": r["topic"], "side": r["side"]} for r in db.execute("SELECT topic, side FROM swap WHERE account=?", (account,))]}


def who_took(db, rec: dict) -> list[dict]:
    """For the organiser holding the listing: each slot's pen names, and whether each was thanked."""
    rows = db.execute("SELECT slot, account, thanked FROM shift_claims WHERE listing_id=? ORDER BY day", (rec["id"],)).fetchall()
    out = []
    for s in rec.get("slots") or []:
        k = slot_key(s)
        out.append({"key": k, "date": s["date"], "start": s.get("start"), "end": s.get("end"), "task": s.get("task"),
                    "needed": s.get("needed"), "people": [{"pen": r["account"], "thanked": bool(r["thanked"])} for r in rows if r["slot"] == k]})
    return out


def thank(db, rec: dict, key: str, pen: str, today: str) -> None:
    s = slots_of(rec).get(key)
    if s is None:
        raise LookupError("That shift has changed. Reload the page.")
    if s["date"] > today:
        raise ValueError("Thanks open once the shift has happened.")
    r = db.execute("SELECT thanked FROM shift_claims WHERE listing_id=? AND slot=? AND account=?", (rec["id"], key, pen)).fetchone()
    if r is None:
        raise LookupError("That pen name took no place on this shift.")
    if not r["thanked"]:
        db.execute("UPDATE shift_claims SET thanked=1, thanked_day=? WHERE listing_id=? AND slot=? AND account=?", (today, rec["id"], key, pen))
        db.commit()


# ---------- crews ----------
def crew_set(db, organiser_id: str, account: str, on: bool, today: str) -> None:
    if on:
        db.execute("INSERT OR IGNORE INTO crews(organiser_id, account, day) VALUES(?,?,?)", (organiser_id, account, today))
    else:
        db.execute("DELETE FROM crews WHERE organiser_id=? AND account=?", (organiser_id, account))
    db.commit()


def crew_of(db, organiser_id: str) -> list[str]:
    return [r["account"] for r in db.execute("SELECT account FROM crews WHERE organiser_id=? ORDER BY day", (organiser_id,))]


# ---------- the ask board ----------
def clean_ask(b: dict, today: str) -> dict:
    kind = b.get("kind") if b.get("kind") in ASK_KINDS else "other"
    text = _line(b.get("text"), 280)
    by = str(b.get("by") or "")
    if len(text) < 8:
        raise ValueError("Say what you need in a sentence: what, when and where.")
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", by) or by < today:
        raise ValueError("Pick the day you need it by.")
    if by > (date.fromisoformat(today) + timedelta(days=60)).isoformat():
        raise ValueError("Asks run up to two months ahead.")
    return {"kind": kind, "text": text, "area": _line(b.get("area"), 80) or None, "by_day": by}


def asks_open(db, today: str, viewer: str | None) -> list[dict]:
    db.execute("DELETE FROM asks WHERE by_day < ?", ((date.fromisoformat(today) - timedelta(days=30)).isoformat(),))
    db.commit()
    out = []
    for r in db.execute("SELECT * FROM asks WHERE state='open' AND by_day >= ? AND listing_id IS NULL ORDER BY by_day", (today,)):
        a = {"id": r["id"], "kind": r["kind"], "text": r["text"], "area": r["area"], "by": r["by_day"], "day": r["day"],
             "mine": viewer is not None and r["account"] == viewer}
        if a["mine"]:
            a["threads"] = db.execute("SELECT COUNT(DISTINCT responder) n FROM ask_msgs WHERE ask_id=?", (r["id"],)).fetchone()["n"]
        elif viewer:
            a["answered"] = bool(db.execute("SELECT 1 FROM ask_msgs WHERE ask_id=? AND responder=?", (r["id"], viewer)).fetchone())
        out.append(a)
    return out


def threads(db, ask: dict, viewer: str) -> list[dict]:
    """The asker sees every responder's thread; a responder sees their own."""
    who = None if ask["account"] == viewer else viewer
    rows = db.execute("SELECT * FROM ask_msgs WHERE ask_id=?" + (" AND responder=?" if who else "") + " ORDER BY id",
                      (ask["id"], who) if who else (ask["id"],)).fetchall()
    by: dict[str, list] = {}
    for r in rows:
        by.setdefault(r["responder"], []).append({"from_asker": bool(r["from_asker"]), "text": r["text"], "at": r["at"]})
    return [{"with": pen, "messages": m} for pen, m in by.items()]


def send(db, ask: dict, viewer: str, to: str | None, text: str, at: int) -> None:
    text = str(text or "").strip()[:600]
    if len(text) < 2:
        raise ValueError("Write a message first.")
    if ask["account"] == viewer:
        if not to or not db.execute("SELECT 1 FROM ask_msgs WHERE ask_id=? AND responder=?", (ask["id"], to)).fetchone():
            raise LookupError("Reply inside a thread someone started.")
        responder, from_asker = to, 1
    else:
        if ask["state"] != "open":
            raise ValueError("This ask has closed.")
        responder, from_asker = viewer, 0
    db.execute("INSERT INTO ask_msgs(ask_id, responder, from_asker, text, at) VALUES(?,?,?,?,?)", (ask["id"], responder, from_asker, text, at))
    db.commit()


# ---------- the skillshare swap ----------
def topic_of(x) -> str:
    return _line(x, 40).lower().strip(" .,!?")


def swap_set(db, account: str, topic: str, side: str, on: bool, today: str) -> None:
    t = topic_of(topic)
    if side not in ("teach", "learn") or len(t) < 2:
        raise ValueError("Name the skill in a word or two.")
    if on:
        n = db.execute("SELECT COUNT(*) n FROM swap WHERE account=? AND side=?", (account, side)).fetchone()["n"]
        if n >= SWAP_EACH_SIDE:
            raise ValueError(f"Up to {SWAP_EACH_SIDE} on each side. Drop one first.")
        db.execute("INSERT OR IGNORE INTO swap(account, topic, side, day) VALUES(?,?,?,?)", (account, t, side, today))
    else:
        db.execute("DELETE FROM swap WHERE account=? AND topic=? AND side=?", (account, t, side))
    db.commit()


def swap_board(db) -> list[dict]:
    """Every topic with its counts: who can teach, who wants to learn. Counts only."""
    out: dict[str, dict] = {}
    for r in db.execute("SELECT topic, side, COUNT(*) n FROM swap GROUP BY topic, side"):
        out.setdefault(r["topic"], {"topic": r["topic"], "teach": 0, "learn": 0})[r["side"]] = r["n"]
    rows = list(out.values())
    for x in rows:
        x["ready"] = x["teach"] >= 1 and x["learn"] >= WORKSHOP_AT
    return sorted(rows, key=lambda x: (-x["ready"], -x["learn"], x["topic"]))


# ---------- rides for a night (Night's way home, 2026-10-24): an ask tied to a listing, answered in the same threads ----------
def clean_ride(b: dict) -> dict:
    kind = b.get("kind") if b.get("kind") in ("offer", "need") else None
    way = b.get("dir") if b.get("dir") in ("to", "from", "both") else None
    if not kind or not way:
        raise ValueError("Say whether you offer a ride or need one, and which way.")
    seats = b.get("seats")
    seats = int(seats) if str(seats or "").isdigit() and 0 < int(seats) <= 8 else 1
    return {"kind": "ride_" + kind, "dir": way, "seats": seats, "area": _line(b.get("area"), 80) or None,
            "text": _line(b.get("text"), 200) or ("A ride on offer" if kind == "offer" else "Looking for a ride")}


def rides_for(db, listing_id: str, viewer: str | None) -> list[dict]:
    out = []
    for r in db.execute("SELECT * FROM asks WHERE listing_id=? AND state='open' ORDER BY day", (listing_id,)):
        x = {"id": r["id"], "kind": r["kind"][5:], "dir": r["dir"], "seats": r["seats"], "area": r["area"], "text": r["text"],
             "mine": viewer is not None and r["account"] == viewer}
        if x["mine"]:
            x["threads"] = db.execute("SELECT COUNT(DISTINCT responder) n FROM ask_msgs WHERE ask_id=?", (r["id"],)).fetchone()["n"]
        elif viewer:
            x["answered"] = bool(db.execute("SELECT 1 FROM ask_msgs WHERE ask_id=? AND responder=?", (r["id"], viewer)).fetchone())
        out.append(x)
    return out


def ride_counts(db) -> dict:
    out: dict[str, dict] = {}
    for r in db.execute("SELECT listing_id, kind, COUNT(*) n FROM asks WHERE listing_id IS NOT NULL AND state='open' GROUP BY listing_id, kind"):
        out.setdefault(r["listing_id"], {"offer": 0, "need": 0})[r["kind"][5:]] = r["n"]
    return out
