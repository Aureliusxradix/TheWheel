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
    CREATE TABLE IF NOT EXISTS organisers (id TEXT PRIMARY KEY, name TEXT NOT NULL, key_hash TEXT NOT NULL UNIQUE,
      page TEXT NOT NULL, code TEXT NOT NULL, made_day TEXT NOT NULL, verified_day TEXT, verified_by TEXT, vouch_asked TEXT);
    CREATE TABLE IF NOT EXISTS claims (listing_id TEXT PRIMARY KEY, organiser_id TEXT NOT NULL, state TEXT NOT NULL,
      day TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS communities (id TEXT PRIMARY KEY, state TEXT NOT NULL, body TEXT NOT NULL, account TEXT,
      day TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS fund (id INTEGER PRIMARY KEY, day TEXT NOT NULL, nzd REAL NOT NULL, how TEXT);
    CREATE TABLE IF NOT EXISTS dup_apart (a TEXT NOT NULL, b TEXT NOT NULL, day TEXT NOT NULL, PRIMARY KEY (a, b));
    CREATE TABLE IF NOT EXISTS modlog (id INTEGER PRIMARY KEY, day TEXT NOT NULL, kind TEXT NOT NULL, listing_id TEXT,
      data TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS appeals (id INTEGER PRIMARY KEY, account TEXT NOT NULL, note TEXT, day TEXT NOT NULL,
      state TEXT NOT NULL DEFAULT 'open');
    CREATE TABLE IF NOT EXISTS reports (listing_id TEXT NOT NULL, account TEXT NOT NULL, reason TEXT NOT NULL, note TEXT,
      weight REAL NOT NULL, day TEXT NOT NULL, open INTEGER NOT NULL DEFAULT 1, PRIMARY KEY (listing_id, account));
    CREATE TABLE IF NOT EXISTS ticket_sales (listing_id TEXT PRIMARY KEY, organiser_id TEXT NOT NULL, address TEXT NOT NULL,
      nzd REAL NOT NULL, cap INTEGER NOT NULL, open INTEGER NOT NULL DEFAULT 1, day TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS ticket_orders (id TEXT PRIMARY KEY, listing_id TEXT NOT NULL, qty INTEGER NOT NULL,
      atomic INTEGER NOT NULL, address TEXT NOT NULL, nzd REAL NOT NULL, created INTEGER NOT NULL, pay_by INTEGER NOT NULL,
      state TEXT NOT NULL, txh TEXT UNIQUE, txid TEXT, txkey TEXT, tries INTEGER NOT NULL DEFAULT 0,
      received INTEGER NOT NULL DEFAULT 0, conf INTEGER NOT NULL DEFAULT 0, note TEXT);
    CREATE TABLE IF NOT EXISTS shift_claims (listing_id TEXT NOT NULL, slot TEXT NOT NULL, account TEXT NOT NULL,
      day TEXT NOT NULL, thanked INTEGER NOT NULL DEFAULT 0, thanked_day TEXT, PRIMARY KEY (listing_id, slot, account));
    CREATE TABLE IF NOT EXISTS crews (organiser_id TEXT NOT NULL, account TEXT NOT NULL, day TEXT NOT NULL,
      PRIMARY KEY (organiser_id, account));
    CREATE TABLE IF NOT EXISTS asks (id TEXT PRIMARY KEY, account TEXT NOT NULL, kind TEXT NOT NULL, text TEXT NOT NULL,
      area TEXT, by_day TEXT NOT NULL, day TEXT NOT NULL, state TEXT NOT NULL DEFAULT 'open');
    CREATE TABLE IF NOT EXISTS ask_msgs (id INTEGER PRIMARY KEY, ask_id TEXT NOT NULL, responder TEXT NOT NULL,
      from_asker INTEGER NOT NULL, text TEXT NOT NULL, at INTEGER NOT NULL);
    CREATE TABLE IF NOT EXISTS swap (account TEXT NOT NULL, topic TEXT NOT NULL, side TEXT NOT NULL, day TEXT NOT NULL,
      PRIMARY KEY (account, topic, side));
    CREATE TABLE IF NOT EXISTS places (id TEXT PRIMARY KEY, state TEXT NOT NULL, body TEXT NOT NULL, account TEXT,
      day TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS tickets (fp TEXT PRIMARY KEY, listing_id TEXT NOT NULL, order_id TEXT NOT NULL,
      conf INTEGER NOT NULL DEFAULT -1, used_at INTEGER);  -- conf -1: proof in, payment yet to be seen
    """)
    cols = {r["name"] for r in db.execute("PRAGMA table_info(events)")}
    for col in ("deposited_account TEXT", "deposit_day TEXT"):  # pen names, day only: no clock times
        if col.split()[0] not in cols:
            db.execute(f"ALTER TABLE events ADD COLUMN {col}")
    if "practice" not in {r["name"] for r in db.execute("PRAGMA table_info(organisers)")}:
        db.execute("ALTER TABLE organisers ADD COLUMN practice TEXT")  # a practitioner's profile (2026-10-24), fields with audiences
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


def log(db, kind: str, listing_id: str | None = None, **data):
    """One line in the public moderation log (2026-10-22): what was done and by which role, a day, never a pen name."""
    with _lock:
        db.execute("INSERT INTO modlog(day, kind, listing_id, data) VALUES(date('now','localtime'), ?, ?, ?)",
                   (kind, listing_id, json.dumps(data, ensure_ascii=False)))
        db.commit()


def modlog(db, before: int | None = None, n: int = 100) -> list[dict]:
    q = "SELECT * FROM modlog" + (" WHERE id < ?" if before else "") + " ORDER BY id DESC LIMIT ?"
    return [{**dict(r), "data": json.loads(r["data"])} for r in db.execute(q, ((before, n) if before else (n,)))]


def appeal_rank(db, account: str, note: str | None, day: str):
    """A member whose rank was reset asks the stewards to look again: one open appeal at a time."""
    with _lock:
        db.execute("DELETE FROM appeals WHERE account=? AND state='open'", (account,))
        db.execute("INSERT INTO appeals(account, note, day) VALUES(?,?,?)", (account, note, day))
        db.commit()


def appeals(db, state: str = "open") -> list[dict]:
    return [dict(r) for r in db.execute("SELECT * FROM appeals WHERE state=? ORDER BY id", (state,))]


def close_appeal(db, aid: int, state: str) -> dict | None:
    row = db.execute("SELECT * FROM appeals WHERE id=?", (aid,)).fetchone()
    if row is None:
        return None
    with _lock:
        db.execute("UPDATE appeals SET state=? WHERE id=?", (state, aid))
        if state == "restored":
            db.execute("UPDATE accounts SET reset_day=NULL WHERE account=?", (row["account"],))
        db.commit()
    return dict(row)


def deposits(db, account: str) -> list[dict]:
    """A member's own listings, for their Me page only."""
    return [json.loads(r["body"]) for r in db.execute(
        "SELECT body FROM events WHERE deposited_account=? ORDER BY start_date DESC LIMIT 100", (account,))]


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
    for row in db.execute("SELECT body FROM events WHERE start_date=? AND id<>? AND state NOT IN ('rejected', 'merged')",
                          (rec["start_date"], rec["id"])):
        other = json.loads(row["body"])
        a, b = words(rec.get("name")), words(other.get("name"))
        if a and b and len(a & b) / min(len(a), len(b)) >= 0.5:
            out.append({"id": other["id"], "name": other["name"], "state": other["review"]["state"]})
    return out


def keep_dups_apart(db, a: str, b: str, day: str):
    """Two look-alike listings a person says are different events: never offered as duplicates again."""
    x, y = sorted((a, b))
    with _lock:
        db.execute("INSERT OR IGNORE INTO dup_apart VALUES(?,?,?)", (x, y, day))
        db.commit()


def dups_apart(db) -> set[tuple[str, str]]:
    return {(r["a"], r["b"]) for r in db.execute("SELECT a, b FROM dup_apart")}


def fund_add(db, nzd: float, how: str | None, day: str):
    """A gift toward The Wheel's own AI (his ask 2026-10-23), entered by hand. Only the total and the count ever leave."""
    with _lock:
        db.execute("INSERT INTO fund(day, nzd, how) VALUES(?,?,?)", (day, round(float(nzd), 2), how))
        db.commit()


def fund_total(db) -> dict:
    r = db.execute("SELECT COALESCE(SUM(nzd), 0) total, COUNT(*) n, MAX(day) last FROM fund").fetchone()
    return {"raised": round(r["total"], 2), "gifts": r["n"], "updated": r["last"]}


def community_put(db, rec: dict, state: str, account: str | None = None, day: str | None = None):
    """A community that keeps meeting (his ask 2026-10-23), added directly and checked like a listing."""
    with _lock:
        db.execute("INSERT INTO communities(id, state, body, account, day) VALUES(?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET "
                   "state=excluded.state, body=excluded.body", (rec["id"], state, json.dumps(rec, ensure_ascii=False), account, day or ""))
        db.commit()


def communities(db, state: str) -> list[dict]:
    return [{**json.loads(r["body"]), "state": r["state"], "_account": r["account"]}
            for r in db.execute("SELECT * FROM communities WHERE state=? ORDER BY day DESC", (state,))]


def place_put(db, rec: dict, state: str, account: str | None = None, day: str | None = None):
    """A place that stays (his calls 2026-10-24: saunas, hot pools), added by a member and checked like a listing."""
    with _lock:
        db.execute("INSERT INTO places(id, state, body, account, day) VALUES(?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET "
                   "state=excluded.state, body=excluded.body", (rec["id"], state, json.dumps(rec), account, day or now()[:10]))
        db.commit()


def places(db, state: str) -> list[dict]:
    return [{**json.loads(r["body"]), "state": r["state"], "_account": r["account"]}
            for r in db.execute("SELECT * FROM places WHERE state=? ORDER BY day DESC", (state,))]


def place(db, pid: str) -> dict | None:
    r = db.execute("SELECT * FROM places WHERE id=?", (pid,)).fetchone()
    return {**json.loads(r["body"]), "state": r["state"], "_account": r["account"]} if r else None


def community(db, cid: str) -> dict | None:
    r = db.execute("SELECT * FROM communities WHERE id=?", (cid,)).fetchone()
    return {**json.loads(r["body"]), "state": r["state"], "_account": r["account"]} if r else None
