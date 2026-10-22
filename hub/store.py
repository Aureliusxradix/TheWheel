"""The hub's store: SQLite, one file (data/hub.db).

Events are kept whole as JSON (schema/event.schema.json) with the columns the
lists need pulled out beside them. Areas are tags with a centre and a reach;
an event carries an area when its coordinates fall inside the reach, worked
out when the list is read, never stored.
"""

import json
import math
import os
import re
import sqlite3
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
DB = Path(os.environ.get("EVENTHUB_DB") or ROOT / "data" / "hub.db")
UA = "TheWheel/0.1 (community events hub; low volume; +https://aureliusxradix.com/thewheel/)"
_lock = threading.Lock()
_last_geocode = [0.0]


def connect() -> sqlite3.Connection:
    DB.parent.mkdir(exist_ok=True)
    db = sqlite3.connect(DB, check_same_thread=False)
    db.row_factory = sqlite3.Row
    db.executescript("""
    CREATE TABLE IF NOT EXISTS events (
      id TEXT PRIMARY KEY, state TEXT NOT NULL, start_date TEXT NOT NULL,
      body TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
    CREATE INDEX IF NOT EXISTS events_state_date ON events(state, start_date);
    CREATE TABLE IF NOT EXISTS areas (
      id INTEGER PRIMARY KEY, name TEXT NOT NULL, lat REAL NOT NULL, lng REAL NOT NULL,
      reach_km REAL NOT NULL, created_by TEXT, created_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS geocache (q TEXT PRIMARY KEY, lat REAL, lng REAL, label TEXT, at TEXT);
    CREATE TABLE IF NOT EXISTS accounts (account TEXT PRIMARY KEY, first_day TEXT NOT NULL, steward INTEGER NOT NULL DEFAULT 0,
      reset_day TEXT);
    CREATE TABLE IF NOT EXISTS reviews (listing_id TEXT NOT NULL, account TEXT NOT NULL, verdict TEXT NOT NULL,
      weight REAL NOT NULL, day TEXT NOT NULL, PRIMARY KEY (listing_id, account));
    CREATE TABLE IF NOT EXISTS deposit_counts (account TEXT NOT NULL, day TEXT NOT NULL, n INTEGER NOT NULL,
      PRIMARY KEY (account, day));
    CREATE TABLE IF NOT EXISTS tag_merges (alias TEXT PRIMARY KEY, canonical TEXT NOT NULL, day TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS tag_kept (a TEXT NOT NULL, b TEXT NOT NULL, day TEXT NOT NULL, PRIMARY KEY (a, b));
    CREATE TABLE IF NOT EXISTS codes (hash TEXT PRIMARY KEY, months INTEGER NOT NULL, made_day TEXT NOT NULL,
      used_day TEXT, note TEXT);
    CREATE TABLE IF NOT EXISTS profiles (account TEXT PRIMARY KEY, data TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS orders (id TEXT PRIMARY KEY, months INTEGER NOT NULL, atomic INTEGER NOT NULL UNIQUE,
      nzd REAL NOT NULL, created INTEGER NOT NULL, state TEXT NOT NULL, conf INTEGER NOT NULL DEFAULT 0, code TEXT);
    CREATE TABLE IF NOT EXISTS suggestions (id INTEGER PRIMARY KEY, listing_id TEXT NOT NULL, account TEXT NOT NULL,
      fields TEXT NOT NULL, day TEXT NOT NULL, UNIQUE (listing_id, account));
    CREATE TABLE IF NOT EXISTS reports (listing_id TEXT NOT NULL, account TEXT NOT NULL, reason TEXT NOT NULL, note TEXT,
      weight REAL NOT NULL, day TEXT NOT NULL, open INTEGER NOT NULL DEFAULT 1, PRIMARY KEY (listing_id, account));
    """)
    cols = {r["name"] for r in db.execute("PRAGMA table_info(events)")}
    for col in ("deposited_account TEXT", "deposit_day TEXT"):  # pen names, day only: no clock times
        if col.split()[0] not in cols:
            db.execute(f"ALTER TABLE events ADD COLUMN {col}")
    if "granted_tier" not in {r["name"] for r in db.execute("PRAGMA table_info(accounts)")}:
        db.execute("ALTER TABLE accounts ADD COLUMN granted_tier INTEGER")  # a tier a steward gives by hand
    if "supporter_until" not in {r["name"] for r in db.execute("PRAGMA table_info(accounts)")}:
        db.execute("ALTER TABLE accounts ADD COLUMN supporter_until TEXT")  # the last day of supporter months
    if "round" not in {r["name"] for r in db.execute("PRAGMA table_info(reviews)")}:
        db.execute("ALTER TABLE reviews ADD COLUMN round INTEGER NOT NULL DEFAULT 0")  # a reopened listing starts a new round
    db.commit()
    return db


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def put(db, rec: dict, state: str | None = None):
    state = state or rec.get("review", {}).get("state", "pending")
    rec.setdefault("review", {})["state"] = state
    with _lock:
        db.execute(
            "INSERT INTO events(id,state,start_date,body,created_at,updated_at,deposited_account,deposit_day) VALUES(?,?,?,?,?,?,?,?) "
            "ON CONFLICT(id) DO UPDATE SET state=excluded.state,start_date=excluded.start_date,body=excluded.body,updated_at=excluded.updated_at",
            (rec["id"], state, rec["start_date"], json.dumps(rec, ensure_ascii=False), now(), now(),
             rec.get("deposited_account"), rec.get("deposit_day")))
        db.commit()


def ensure_account(db, account: str):
    with _lock:
        db.execute("INSERT OR IGNORE INTO accounts(account, first_day) VALUES(?, date('now','localtime'))", (account,))
        db.commit()


def count_deposit(db, account: str, day: str) -> int:
    with _lock:
        db.execute("INSERT INTO deposit_counts VALUES(?,?,1) ON CONFLICT(account,day) DO UPDATE SET n=n+1", (account, day))
        db.commit()
    return db.execute("SELECT n FROM deposit_counts WHERE account=? AND day=?", (account, day)).fetchone()["n"]


def cast_review(db, listing_id: str, account: str, verdict: str, weight: float, day: str, rnd: int = 0):
    with _lock:
        db.execute("INSERT INTO reviews(listing_id,account,verdict,weight,day,round) VALUES(?,?,?,?,?,?) "
                   "ON CONFLICT(listing_id,account) DO UPDATE SET "
                   "verdict=excluded.verdict, weight=excluded.weight, day=excluded.day, round=excluded.round",
                   (listing_id, account, verdict, weight, day, rnd))
        db.commit()


def report(db, listing_id: str, account: str, reason: str, note: str | None, weight: float, day: str):
    """One open report per member per listing; reporting again replaces it."""
    with _lock:
        db.execute("INSERT INTO reports(listing_id,account,reason,note,weight,day,open) VALUES(?,?,?,?,?,?,1) "
                   "ON CONFLICT(listing_id,account) DO UPDATE SET reason=excluded.reason, note=excluded.note, "
                   "weight=excluded.weight, day=excluded.day, open=1",
                   (listing_id, account, reason, note, weight, day))
        db.commit()


def reports_for(db, listing_id: str) -> list[dict]:
    """Open reports: what the reviewers of a reported listing read."""
    return [dict(r) for r in db.execute("SELECT account, reason, note, weight FROM reports WHERE listing_id=? AND open=1 "
                                         "ORDER BY day", (listing_id,))]


def close_reports(db, listing_id: str):
    """The listing settled again: its reports are answered."""
    with _lock:
        db.execute("UPDATE reports SET open=0 WHERE listing_id=? AND open=1", (listing_id,))
        db.commit()


def suggest(db, listing_id: str, account: str, fields: dict, day: str):
    """A fix from a member below the Reviewer tier, waiting for a Reviewer or Steward: one per member per listing."""
    with _lock:
        db.execute("INSERT INTO suggestions(listing_id,account,fields,day) VALUES(?,?,?,?) ON CONFLICT(listing_id,account) "
                   "DO UPDATE SET fields=excluded.fields, day=excluded.day",
                   (listing_id, account, json.dumps(fields, ensure_ascii=False), day))
        db.commit()


def suggestions_for(db, listing_id: str) -> list[dict]:
    return [{**dict(r), "fields": json.loads(r["fields"])}
            for r in db.execute("SELECT * FROM suggestions WHERE listing_id=? ORDER BY id", (listing_id,))]


def suggestion(db, sid: int) -> dict | None:
    r = db.execute("SELECT * FROM suggestions WHERE id=?", (sid,)).fetchone()
    return {**dict(r), "fields": json.loads(r["fields"])} if r else None


def drop_suggestion(db, sid: int):
    with _lock:
        db.execute("DELETE FROM suggestions WHERE id=?", (sid,))
        db.commit()


def reviews_for(db, listing_id: str) -> list[dict]:
    return [dict(r) for r in db.execute("SELECT account, verdict, weight, round FROM reviews WHERE listing_id=?", (listing_id,))]


def get(db, eid: str) -> dict | None:
    row = db.execute("SELECT body FROM events WHERE id=?", (eid,)).fetchone()
    return json.loads(row["body"]) if row else None


def merges(db) -> dict[str, str]:
    """alias -> the kind kept, chains followed (a -> b -> c reads a -> c)."""
    m = {r["alias"]: r["canonical"] for r in db.execute("SELECT alias, canonical FROM tag_merges")}
    def end(t, seen=()):
        return end(m[t], seen + (t,)) if t in m and t not in seen else t
    return {a: end(a) for a in m}


def merge_tag(db, alias: str, canonical: str):
    if merges(db).get(canonical, canonical) == alias or alias == canonical:
        raise ValueError("Those two are already one kind.")
    with _lock:
        db.execute("INSERT INTO tag_merges VALUES(?,?,date('now','localtime')) ON CONFLICT(alias) DO UPDATE SET canonical=excluded.canonical",
                   (alias, canonical))
        db.commit()


def unmerge_tag(db, alias: str):
    with _lock:
        db.execute("DELETE FROM tag_merges WHERE alias=?", (alias,))
        db.commit()


def keep_apart(db, a: str, b: str):
    a, b = sorted((a, b))
    with _lock:
        db.execute("INSERT OR IGNORE INTO tag_kept VALUES(?,?,date('now','localtime'))", (a, b))
        db.commit()


def kept_apart(db) -> set[tuple[str, str]]:
    return {(r["a"], r["b"]) for r in db.execute("SELECT a, b FROM tag_kept")}


def flyer_in_use(db, name: str) -> bool:
    """A flyer is served only while a listing that is approved or waiting uses it."""
    return db.execute("SELECT 1 FROM events WHERE state IN ('approved','pending') AND json_extract(body, '$.source.flyer') = ? "
                      "LIMIT 1", (name,)).fetchone() is not None


def events(db, states: tuple[str, ...]) -> list[dict]:
    q = f"SELECT body FROM events WHERE state IN ({','.join('?' * len(states))}) ORDER BY start_date"
    return [json.loads(r["body"]) for r in db.execute(q, states)]


def areas(db) -> list[dict]:
    return [dict(r) for r in db.execute("SELECT * FROM areas ORDER BY name")]


def add_area(db, name: str, lat: float, lng: float, reach_km: float, by: str | None) -> dict:
    with _lock:
        cur = db.execute("INSERT INTO areas(name,lat,lng,reach_km,created_by,created_at) VALUES(?,?,?,?,?,?)",
                         (name.strip(), lat, lng, reach_km, by, now()))
        db.commit()
    return {"id": cur.lastrowid, "name": name.strip(), "lat": lat, "lng": lng, "reach_km": reach_km}


def delete_area(db, aid: int):
    with _lock:
        db.execute("DELETE FROM areas WHERE id=?", (aid,))
        db.commit()


def km(a_lat, a_lng, b_lat, b_lng) -> float:
    r = 6371.0
    p1, p2 = math.radians(a_lat), math.radians(b_lat)
    dp, dl = p2 - p1, math.radians(b_lng - a_lng)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(h))


def areas_for(rec: dict, all_areas: list[dict]) -> list[str]:
    if rec.get("latitude") is None:
        return []
    return [a["name"] for a in all_areas if km(a["lat"], a["lng"], rec["latitude"], rec["longitude"]) <= a["reach_km"]]


def geocode(db, rec: dict) -> dict:
    """Venue -> coordinates through OpenStreetMap's Nominatim (1 request a second, cached)."""
    if rec.get("latitude") is not None or rec.get("online"):
        return rec
    parts = [rec.get("location_name"), rec.get("location_address"), rec.get("location_locality")]
    q = ", ".join(p for p in parts if p)
    if not q:
        return rec
    q += ", New Zealand"
    row = db.execute("SELECT lat,lng FROM geocache WHERE q=?", (q,)).fetchone()
    if row is None:
        hits = []
        for attempt in (q, ", ".join(p for p in [rec.get("location_locality")] if p) + ", New Zealand"):
            if attempt.startswith(","):
                continue
            wait = 1.1 - (time.time() - _last_geocode[0])
            if wait > 0:
                time.sleep(wait)
            _last_geocode[0] = time.time()
            r = requests.get("https://nominatim.openstreetmap.org/search",
                             params={"q": attempt, "format": "jsonv2", "limit": 1, "countrycodes": "nz"},
                             headers={"User-Agent": UA}, timeout=20)
            hits = r.json() if r.ok else []
            if hits:
                break
        lat, lng = (float(hits[0]["lat"]), float(hits[0]["lon"])) if hits else (None, None)
        with _lock:
            db.execute("INSERT OR REPLACE INTO geocache VALUES(?,?,?,?,?)",
                       (q, lat, lng, hits[0].get("display_name") if hits else None, now()))
            db.commit()
        row = {"lat": lat, "lng": lng}
    if row["lat"] is not None:
        rec["latitude"], rec["longitude"] = row["lat"], row["lng"]
    return rec


def words(s: str) -> set[str]:
    return set(re.findall(r"[a-zāēīōū0-9]+", (s or "").lower())) - {"the", "a", "and", "at", "of", "live"}


def likely_duplicates(db, rec: dict) -> list[dict]:
    """Same day, and at least half the name's words shared: shown to the reviewer, never merged by itself."""
    out = []
    for row in db.execute("SELECT body FROM events WHERE start_date=? AND id<>? AND state<>'rejected'",
                          (rec["start_date"], rec["id"])):
        other = json.loads(row["body"])
        a, b = words(rec.get("name")), words(other.get("name"))
        if a and b and len(a & b) / min(len(a), len(b)) >= 0.5:
            out.append({"id": other["id"], "name": other["name"], "state": other["review"]["state"]})
    return out
