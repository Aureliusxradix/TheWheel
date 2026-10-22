"""The Wheel's web app: the three modes, add a listing, review, areas, members.

    /usr/bin/python3 -E -s hub/server.py [--port 8790]

Binds 127.0.0.1. Accounts are Semaphore logins (zk/): a member proves they belong and gets a pen name.
Adding listings and reviewing need an account (his ruling 2026-10-20); areas and opening check-ins need a steward.

Every answer passes the identity gate (hub/gate.py, threat profile F4) and the server will not start without its
word list. Going live, the page is a static shell on the site and this server answers the API only:
    WHEEL_API_ONLY=1             no pages, no test aids: /api/* only
    WHEEL_ORIGINS=https://...    the pages allowed to call it from another address (comma-separated)
    WHEEL_HOST=0.0.0.0           inside a container; 127.0.0.1 otherwise
    WHEEL_GATE_PATTERNS=/path    the gate's private word list
    WHEEL_SITE=https://...       the page itself, where a share link sends people on (default: this server's own page)
    WHEEL_DATA, EVENTHUB_DB, WHEEL_ZK_ADMIN_FILE, WHEEL_ZK_URL   where the store, uploads and the member service are
"""

import argparse
import base64
import hashlib
import json
import os
import re
import secrets
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from hub import chats, flyer, gate, kinds, organisers, repeats, rep, share, store, support  # noqa: E402
from reader import core  # noqa: E402

STATIC = ROOT / "hub" / "static"
TZ = core.HUB_TZ  # days (today, the daily caps, review days) are Auckland days, whatever the host clock says
DATA = Path(os.environ.get("WHEEL_DATA") or ROOT / "data")  # the store's folder; the database itself: EVENTHUB_DB
UPLOADS = DATA / "uploads"
FLYERS = UPLOADS / "flyers"  # cleaned flyers only (hub/flyer.py); an upload as sent is never kept
LINK_FIELDS = ("website", "tickets_url")
ADMIN_TOKEN = Path(os.environ.get("WHEEL_ZK_ADMIN_FILE") or DATA / "zk-admin.token")
TYPES = {".wasm": "application/wasm", ".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8",
         ".css": "text/css; charset=utf-8", ".svg": "image/svg+xml", ".png": "image/png",
         ".webmanifest": "application/manifest+json"}
EDITABLE = {"name", "summary", "description", "start_date", "start_time", "end_date", "end_time", "recurrence",
            "status", "location_name", "location_address", "location_locality", "price", "website",
            "tickets_url", "tags", "organiser", "online", "modes", "listing_kind", "slots", "requirements",
            "chat_platform", "chat_link", "chat_link_ok", "chat_text", "festival"}
MEMBERS_ONLY = ("chat_link", "chat_link_ok", "chat_text", "appeal_note")  # a group's link and its announcement: signed-in members only
MODES = {"day", "night", "recovery"}
MAX_BODY = 12 * 1024 * 1024
ZK = os.environ.get("WHEEL_ZK_URL", "http://127.0.0.1:8792")  # zk/server.mjs, the member service (zk/run.sh)
SELFTEST = os.environ.get("WHEEL_SELFTEST") == "1"  # serves tests/browser/selftest.html, test runs only
ZK_PUBLIC = {("GET", "/group"), ("GET", "/count"), ("POST", "/join"), ("POST", "/showup"), ("POST", "/challenge"), ("POST", "/login")}
JOIN_FIRST = "Join The Wheel first, on the Me page. It takes one tap."
API_ONLY = os.environ.get("WHEEL_API_ONLY") == "1"
ORIGINS = {o.strip() for o in os.environ.get("WHEEL_ORIGINS", "").split(",") if o.strip()}
SITE = os.environ.get("WHEEL_SITE", "/")
FUND_STEPS = [3000, 6000, 10000]  # his "4 steps" 2026-10-23: the bench test at nothing, then these three
FUND_GOAL = float(os.environ.get("WHEEL_FUND_GOAL", "10000"))  # NZ$ toward The Wheel's own AI (his figure 2026-10-23, "say some 10knzd")  # a share link opens the listing here, at #l/<id>
ORG_FIELDS = ("start_date", "start_time", "end_date", "end_time", "location_name", "location_address", "location_locality",
              "price", "website", "tickets_url", "description", "status", "recurrence")  # what a proven organiser keeps right
STATUSES = ("confirmed", "tentative", "postponed", "cancelled")
REPORT_REASONS = {"wrong": "The details are wrong", "over": "Cancelled, moved or over", "unsafe": "Unsafe or harmful"}
PRIVATE_FIELDS = ("deposited_by", "deposited_account", "deposit_day")  # who added a listing never leaves the server
HELD = "The Wheel held this answer back: it carried something that stays on the server."
GATE = None  # set in main(): the identity gate's compiled word list
# Whole-site daily caps (2026-10-20, going live; provisional, his to change). Joining needs no account, so per-account
# limits alone do not hold: a script could join without end, spend his Claude plan on readings, or fill the members
# list past the 1,024 the proving files cover (depth 10), which would lock every member out.
CAPS = {"join": int(os.environ.get("WHEEL_JOINS_PER_DAY", "50")),
        "read": int(os.environ.get("WHEEL_READS_PER_DAY", "60")),
        "submit": int(os.environ.get("WHEEL_SUBMITS_PER_DAY", "100")),
        "order": int(os.environ.get("WHEEL_ORDERS_PER_DAY", "100")),
        "org": int(os.environ.get("WHEEL_ORGS_PER_DAY", "20"))}
CAP_TEXT = {"join": "The Wheel has taken all the new members it takes in one day. Join tomorrow.",
            "read": "The Wheel has read all the posts it reads in one day. Paste it tomorrow, or fill the listing in by hand.",
            "submit": "The Wheel has taken all the new listings it takes in one day. Add it tomorrow.",
            "order": "The Wheel has opened all the Monero orders it opens in one day. Try tomorrow, or pay another way.",
            "org": "The Wheel has made all the organiser accounts it makes in one day. Try tomorrow."}


# A few seconds of work in the browser before a join (his "Do A-F", 2026-10-22): cheap for one person, a cost per
# account for anyone making them in bulk. A script with native hashing pays far less than a phone does, so the daily
# join cap above stays the real limit; this only makes each spare account cost something.
JOIN_BITS = int(os.environ.get("WHEEL_JOIN_WORK_BITS", "18"))  # about 1.5 s on a laptop, a few seconds on a phone
JOIN_WORK_TTL = 600
_join_work: dict[str, float] = {}
_join_lock = threading.Lock()


def join_work() -> dict:
    now = time.time()
    with _join_lock:
        for k in [k for k, exp in _join_work.items() if exp < now]:
            del _join_work[k]
        if len(_join_work) > 5000:  # a flood of asks: drop the oldest
            for k in sorted(_join_work, key=_join_work.get)[:1000]:
                del _join_work[k]
        nonce = secrets.token_hex(16)
        _join_work[nonce] = now + JOIN_WORK_TTL
    return {"nonce": nonce, "bits": JOIN_BITS}


def zero_bits(digest: bytes) -> int:
    n = 0
    for b in digest:
        if b:
            return n + 8 - b.bit_length()
        n += 8
    return n


def work_ok(nonce, commitment, n) -> bool:
    """The browser found n with sha256("nonce:commitment:n") starting in JOIN_BITS zero bits. Each ask is single use."""
    with _join_lock:
        exp = _join_work.pop(str(nonce), None)
    if not exp or exp < time.time() or not isinstance(n, int) or n < 0:
        return False
    return zero_bits(hashlib.sha256(f"{nonce}:{commitment}:{n}".encode()).digest()) >= JOIN_BITS


# Supporters (his calls 2026-10-22): a watcher beside the Monero node reads its own view-only wallet and reports
# payments here. Its token is a file (a podman secret in production); without it the Monero way stays hidden.
WATCH_FILE = Path(os.environ.get("WHEEL_WATCH_TOKEN_FILE") or DATA / "watch.token")
PAYPAL_LINK = os.environ.get("WHEEL_PAYPAL_LINK", "")
_watch_seen = [0.0]


def watch_token() -> str:
    try:
        return WATCH_FILE.read_text().strip()
    except OSError:
        return ""


def monero_open() -> bool:
    """Orders open only while the watcher has asked for them in the last half hour: a payment then gets seen."""
    return bool(watch_token()) and time.time() - _watch_seen[0] < 1800


def support_config() -> dict:
    return {"name": support.NAME, "min_nzd": support.MIN_NZD, "suggest_nzd": support.SUGGEST_NZD,
            "months": list(support.MONTHS), "paypal": PAYPAL_LINK, "monero": monero_open(),
            "supporters": support.count(db()), "floor": support.FLOOR,
            "colours": {k: {"hex": v[0], "supporter": v[1]} for k, v in support.COLOURS.items()},
            "glyphs": support.GLYPHS, "signs": support.SIGNS}


def my_profile(acct: str) -> dict:
    d = db()
    p = support.get_profile(d, acct)
    return {"profile": p, "until": support.until(d, acct), "supporter": support.active(d, acct),
            "lookalike": support.lookalike(d, acct), "floor_ok": support.count(d) >= support.FLOOR}


_active = {"at": 0.0, "n": 0}


def active_members() -> int:
    if time.time() - _active["at"] > 60:
        _active.update(at=time.time(), n=rep.active(db()))
    return _active["n"]


def over_cap(kind: str) -> bool:
    return store.count_deposit(db(), f"site:{kind}", datetime.now(TZ).date().isoformat()) > CAPS[kind]


def zk_call(method: str, path: str, query: str = "", body: bytes | None = None, admin: bool = False) -> tuple[int, bytes]:
    headers = {"content-type": "application/json"} if body is not None else {}
    if admin:
        headers["x-wheel-admin"] = ADMIN_TOKEN.read_text().strip()
    req = urllib.request.Request(ZK + path + (f"?{query}" if query else ""), data=body, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()
    except OSError:
        return 503, b'{"ok": false, "why": "offline"}'


_local = threading.local()


def db():
    """One SQLite connection per server thread; a shared one drops requests that arrive together."""
    if not hasattr(_local, "db"):
        _local.db = store.connect()
    return _local.db


def clean(rec: dict, edits: dict) -> dict:
    for k, v in list(edits.items()):  # a copy: rec and edits can be the same dict
        if k not in EDITABLE:
            continue
        if k in ("tags", "requirements"):
            v = [t.strip() for t in (v if isinstance(v, list) else str(v).split(",")) if t.strip()]
            v = [t.lower() for t in v] if k == "tags" else v
            v = v or None
        elif k == "modes":
            v = [m for m in (v or []) if m in MODES] or None
        elif k in LINK_FIELDS:
            v = str(v or "").strip() or None
            if v and not re.fullmatch(r"https?://[^\s<>\"']+", v):
                raise ValueError("Links need to be web addresses starting https://")
            c = chats.classify(v) if v else None
            if c and c[0] == "group":
                raise ValueError("That's a group chat's link: put it under \"Organised in a group chat\", where members only see it.")
            if c:
                raise ValueError(chats.PERSON_TEXT)
        elif k == "chat_platform":
            v = v if v in chats.PLATFORMS else None
        elif k == "chat_link":
            v = str(v or "").strip() or None
            c = chats.classify(v) if v else None
            if v and not c:
                raise ValueError(chats.LINKS_HELP)
            if c and c[0] == "person":
                raise ValueError(chats.PERSON_TEXT)
            if c:
                rec["chat_platform"] = c[1]
        elif k == "chat_link_ok":
            v = True if v in (True, 1, "1", "true", "on") else None
        elif k == "chat_text":
            v = chats.scrub(str(v or ""))[:4000] or None
        elif k == "listing_kind":
            v = v if v in ("event", "volunteer", "festival") else "event"
        elif k == "festival":
            v = clean_festival(v)
        elif k == "slots":
            out = []
            for sl in v or []:
                if not isinstance(sl, dict) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(sl.get("date") or "")):
                    continue
                n = sl.get("needed")
                out.append({"date": sl["date"], "start": (sl.get("start") or None), "end": (sl.get("end") or None),
                            "needed": int(n) if str(n or "").isdigit() else None, "task": (str(sl.get("task") or "").strip() or None)})
            v = out or None
        elif isinstance(v, str):
            v = v.strip() or None
        if v is None:
            rec.pop(k, None)
        else:
            rec[k] = v
    if rec.get("chat_link") and not rec.get("chat_link_ok"):  # his ruling 2026-10-21: the organiser's word decides
        raise ValueError("Tick that the organiser shares this group link openly, or take the link out.")
    if rec.get("chat_link"):
        rec["chat_platform"] = chats.classify(rec["chat_link"])[1]  # the link names its app
    rec["time_known"] = bool(rec.get("start_time"))
    if not rec.get("modes"):
        raise ValueError("Pick at least one mode: Day, Night or Recovery.")
    if rec.get("start_date") and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", rec["start_date"]):
        raise ValueError("The date needs to look like 2026-10-24.")
    for f in ("start_time", "end_time"):
        if rec.get(f) and not re.fullmatch(r"[0-2]\d:[0-5]\d", rec[f]):
            raise ValueError("Times need to look like 19:30.")
    return rec


def clean_festival(v) -> dict | None:
    """A festival's own details (his ask 2026-10-23), kept short and plain."""
    if not isinstance(v, dict):
        return None
    line = lambda x, n: re.sub(r"\s+", " ", str(x or "")).strip()[:n]  # noqa: E731
    lineup = [line(x, 120) for x in (v.get("lineup") or [])[:80] if line(x, 120)]
    tickets = [{"name": line(t.get("name"), 80), "price": line(t.get("price"), 40) or None}
               for t in (v.get("tickets") or [])[:20] if isinstance(t, dict) and line(t.get("name"), 80)]
    out = {"lineup": lineup, "tickets": tickets, **{k: line(v.get(k), 300) or None for k in ("camping", "ages", "bring", "access")}}
    return out if any(out.values()) else None


def looks_like_festival(rec: dict) -> bool:
    """After reading: a name or a kind that says festival (the reader's prompt stays as scored)."""
    words = " ".join([rec.get("name") or ""] + list(rec.get("tags") or []))
    return bool(re.search(r"\b(festival|fest)s?\b", words, re.I))


def settle(rec: dict) -> dict:
    """Work out a listing's certainty from its reviews and move its state when it settles."""
    rnd = rec.get("round", 0)  # a reported listing back in review starts a new round: earlier reviews stay for rep only
    revs = [r for r in store.reviews_for(db(), rec["id"]) if r["round"] == rnd]
    fors = [r["weight"] for r in revs if r["verdict"] == "approve"]
    against = [r["weight"] for r in revs if r["verdict"] == "reject"]
    c_for, c_against = rep.certainty(fors, against)
    rec["certainty"] = {"for": c_for, "against": c_against, "reviews": len(revs)}
    if revs:
        new = rep.settled_state(c_for, c_against)
        if new != rec["review"].get("state"):
            if new == "approved":
                store.geocode(db(), rec)
            rec["review"] = {"state": new, "by": "reviews", "at": store.now()}
    elif rec["review"].get("state") == "approved" and not rnd:  # checked before accounts existed: by him, as steward
        rec["certainty"] = {"for": rep.WEIGHT[3], "against": 0.0, "reviews": 1}
    return rec


def changes(rec: dict, edits: dict) -> dict:
    """The fields an edit would change, as they would read after it: what a suggested fix carries."""
    fixed = clean(json.loads(json.dumps(rec)), edits)
    return {k: fixed.get(k) for k in sorted(EDITABLE) if fixed.get(k) != rec.get(k)}


def shown_suggestions(sugs: list[dict]) -> list[dict]:
    """Suggested fixes as a Reviewer sees them: no pen names, and one carrying a private mark held back alone."""
    out = []
    for sg in sugs:
        h = gate.hit(GATE, json.dumps(sg["fields"], ensure_ascii=False))
        if h:
            sys.stderr.write(f"gate: suggestion {sg['id']} on {sg['listing_id']} withheld (/{h}/)\n")
            continue
        out.append({"id": sg["id"], "fields": sg["fields"]})
    return out


def for_viewer(rec: dict, member: bool) -> dict:
    """A group's link and announcement go to signed-in members; everyone else learns there is a way in."""
    if not member:
        if rec.get("chat_link"):
            rec["chat_link_hidden"] = True
        if rec.get("chat_text"):
            rec["chat_text_hidden"] = True
        for k in MEMBERS_ONLY:
            rec.pop(k, None)
    return rec


def public(rec: dict) -> dict:
    for k in PRIVATE_FIELDS:
        rec.pop(k, None)
    return rec


def withheld(rec: dict) -> bool:
    """A listing that carries a private mark stays out of every answer; the server log names it for a steward."""
    h = gate.hit(GATE, json.dumps(rec, ensure_ascii=False))
    if h:
        sys.stderr.write(f"gate: listing {rec.get('id')} withheld (/{h}/); see hub/wheelctl.py held\n")
    return bool(h)


def dated(r: dict, today: str) -> dict:
    """Whether a listing is past, and a repeating one's next date: the same answer for the list and the review queue."""
    if (r.get("recurrence") or "").strip().lower() in ("unknown", "none", "n/a"):  # the reader's filler, not a repeat
        r.pop("recurrence")
    end = r.get("end_date") or r["start_date"]
    r["past"] = end < today and not r.get("recurrence")  # kept as the archive (his call, 2026-10-20)
    if r.get("recurrence"):  # every date it happens for the next half year: picking a day finds it (2026-10-21)
        ahead = repeats.dates_ahead(r["recurrence"], r["start_date"], today)
        if len(ahead) > 1:
            r["repeats_on"] = ahead
    nxt = repeats.next_on(r["recurrence"], r["start_date"], today) if r.get("recurrence") and end < today else None
    if nxt:  # shown on its next date everywhere; the listing keeps the date it was found with
        span = (date.fromisoformat(end) - date.fromisoformat(r["start_date"])).days
        r["next_date"], r["next_end"] = nxt, (date.fromisoformat(nxt) + timedelta(days=span)).isoformat()
    return r


# Duplicates (his ask 2026-10-23: "some kind of duplicate listing auto detect function"). The same name on the same day is
# a copy: the list shows one, the checked one first, and nothing is deleted. Look-alikes on the same day go to Review as
# pairs, where a Reviewer merges a copy into the listing it repeats (state "merged": no rep either way) or keeps them apart.
FILL_FROM_COPY = ("website", "tickets_url", "location_name", "location_address", "location_locality", "price", "description",
                  "summary", "end_date", "end_time", "start_time")


def copy_key(r: dict) -> tuple:
    return (re.sub(r"[^a-z0-9āēīōū]+", " ", (r.get("name") or "").lower()).strip(), r.get("start_date"))


def collapse_copies(recs: list[dict]) -> list[dict]:
    """One listing per name and day: the checked copy, else the first, stands for the rest. A listing kept apart from
    every shown one with its name and day still shows."""
    apart, groups, shown = store.dups_apart(db()), {}, set()
    for r in sorted(recs, key=lambda r: (r.get("review", {}).get("state") != "approved", r["id"])):
        group = groups.setdefault(copy_key(r), [])
        if any(tuple(sorted((g["id"], r["id"]))) not in apart for g in group):
            continue  # a copy of one already shown
        group.append(r)
        shown.add(r["id"])
    return [r for r in recs if r["id"] in shown]


def duplicate_pairs() -> list[dict]:
    """Look-alike listings on the same day, still to come, that nobody has kept apart."""
    today, apart, seen, out = datetime.now(TZ).date().isoformat(), store.dups_apart(db()), set(), []
    recs = [r for r in store.events(db(), ("approved", "pending")) if not withheld(public(r))]
    by_id = {r["id"]: r for r in recs}
    shown = {r["id"] for r in collapse_copies(recs)}  # a look-alike pair is offered once, between listings on the list
    for r in recs:
        if (r.get("end_date") or r["start_date"]) < today:
            continue
        for d in store.likely_duplicates(db(), r):
            pair = tuple(sorted((r["id"], d["id"])))
            if pair in seen or pair in apart or d["id"] not in by_id:
                continue
            seen.add(pair)
            a, b = by_id[pair[0]], by_id[pair[1]]
            if copy_key(a) != copy_key(b) and not (a["id"] in shown and b["id"] in shown):
                continue
            out.append({"exact": copy_key(a) == copy_key(b), "listings": [for_viewer(dup_summary(x), False) for x in (a, b)]})
    return sorted(out, key=lambda p: (not p["exact"], p["listings"][0]["start_date"]))


def dup_summary(r: dict) -> dict:
    keys = ("id", "name", "start_date", "start_time", "end_time", "location_name", "location_locality", "price", "website",
            "tickets_url", "modes", "review", "recurrence")
    return {**{k: r.get(k) for k in keys}, "source_url": (r.get("source") or {}).get("url"), "flyer": (r.get("source") or {}).get("flyer")}


def merge_copy(keep: dict, drop: dict):
    """The copy goes out as merged into the listing it repeats; anything the kept one lacks comes across."""
    for f in FILL_FROM_COPY:
        if not keep.get(f) and drop.get(f):
            keep[f] = drop[f]
    if drop.get("source", {}).get("flyer") and not keep.get("source", {}).get("flyer"):
        keep.setdefault("source", {})["flyer"] = drop["source"]["flyer"]
    drop["merged_into"] = keep["id"]
    drop["review"] = {"state": "merged", "by": "duplicate", "at": store.now()}
    store.put(db(), keep, keep["review"]["state"])
    store.put(db(), drop, "merged")
    store.close_reports(db(), drop["id"])


def claimed_map() -> dict:
    """listing id -> the proven organiser holding it, as everyone sees it."""
    return {r["listing_id"]: {"id": r["id"], "name": r["name"]} for r in db().execute(
        "SELECT c.listing_id, o.id, o.name FROM claims c JOIN organisers o ON o.id = c.organiser_id "
        "WHERE c.state='claimed' AND o.verified_day IS NOT NULL") if not gate.hit(GATE, r["name"])}  # a marked name stays off


def org_update(rec: dict, o: dict, edits: dict) -> list[str]:
    """A proven organiser keeps its listing right: the details in ORG_FIELDS and an update note, straight away."""
    if edits.get("status") not in (None, "") and edits["status"] not in STATUSES:
        raise ValueError("Pick a status: confirmed, tentative, postponed or cancelled.")
    fields = {k: v for k, v in edits.items() if k in ORG_FIELDS}
    changed = sorted(changes(rec, fields))
    clean(rec, fields)
    note = chats.scrub(str(edits.get("note") or ""))[:280]
    if note and note != (rec.get("org_note") or {}).get("text"):
        rec["org_note"] = {"text": note, "day": datetime.now(TZ).date().isoformat()}
        changed.append("org_note")
    if changed:
        store.put(db(), rec, rec["review"]["state"])
    return changed


def listing(params: dict, member: bool = False) -> dict:
    states = ("approved", "pending") if params.get("unreviewed", ["1"])[0] == "1" else ("approved",)
    all_areas = store.areas(db())
    today = datetime.now(TZ).date().isoformat()
    out = []
    merged = store.merges(db())
    held = claimed_map()
    for r in collapse_copies(store.events(db(), states)):
        if withheld(public(r)):
            continue
        if r["id"] in held:
            r["claimed_by"] = held[r["id"]]
        r["tags"] = kinds.apply(r.get("tags") or [], merged)  # shown merged; the listing keeps its own words
        dated(r, today)
        r["areas"] = store.areas_for(r, all_areas)
        r["certainty"] = settle(dict(r))["certainty"]
        out.append(for_viewer(r, member))
    tags: dict[str, int] = {}
    for r in out:
        for t in r.get("tags", []):
            tags[t] = tags.get(t, 0) + 1
    return {"events": out, "tags": sorted(tags.items(), key=lambda kv: (-kv[1], kv[0])), "areas": all_areas,
            "today": today, "at": store.now()}


def shown_listing(eid: str) -> dict | None:
    """One listing as anyone sees it in the list (checked or waiting, never members-only fields), or None."""
    rec = store.get(db(), eid)
    if rec is None or rec.get("review", {}).get("state") not in ("approved", "pending") or withheld(public(rec)):
        return None
    rec["tags"] = kinds.apply(rec.get("tags") or [], store.merges(db()))
    return for_viewer(dated(rec, datetime.now(TZ).date().isoformat()), False)


def feed_items(mode: str | None) -> list[dict]:
    """Checked listings still to come, in one mode or all: what a calendar subscription and the RSS feed carry."""
    today = datetime.now(TZ).date().isoformat()
    out = []
    for r in store.events(db(), ("approved",)):
        if withheld(public(r)) or (mode and mode not in (r.get("modes") or [])):
            continue
        dated(r, today)
        if not r["past"]:
            out.append(for_viewer(r, False))
    return sorted(out, key=lambda r: (share.on(r), r.get("start_time") or ""))


def share_url(base: str, eid: str) -> str:
    return f"{base}/l/{eid}"


def file_report(rec: dict, acct: str, t: int, reason: str, note, day: str) -> bool:
    """Keep a member's report; a checked listing whose open reports reach rep.REOPEN goes back to review in a new
    round, where earlier reviews count for rep only. Returns whether it went back."""
    note = chats.scrub(str(note or ""))[:300] or None  # reviewers read it: names and numbers out first
    store.report(db(), rec["id"], acct, reason, note, rep.WEIGHT[t], day)
    if rec["review"]["state"] != "approved":
        return False  # waiting already: reviewers see the report on its card
    if rep.certainty([r["weight"] for r in store.reports_for(db(), rec["id"])], [])[0] < rep.REOPEN:
        return False
    rec["round"] = rec.get("round", 0) + 1
    rec["reopened"] = True
    rec["review"] = {"state": "pending", "by": "reports", "at": store.now()}
    store.put(db(), rec, "pending")
    store.log(db(), "reopened", rec["id"])
    return True


def steps_aside(rec: dict, acct: str) -> bool:
    """In an appeal's round, a member who reviewed the listing before it was turned down leaves it to others."""
    return rec.get("appeal_round") is not None and rec.get("appeal_round") == rec.get("round") and any(
        x["account"] == acct and x["round"] < rec["round"] for x in store.reviews_for(db(), rec["id"]))


def file_appeal(rec: dict, acct: str, note) -> str | None:
    """The member who added a turned-down listing asks once for another look: back to review in a new round, where
    those who reviewed it before step aside. Returns why it was refused, or None."""
    if rec.get("deposited_account") != acct:
        return "Only the member who added a listing can appeal it."
    if rec.get("review", {}).get("state") != "rejected":
        return "Only a turned-down listing can be appealed."
    if rec.get("appealed"):
        return "This listing has had its appeal."
    rec["round"] = rec.get("round", 0) + 1
    rec["appeal_round"], rec["appealed"] = rec["round"], True
    rec["appeal_note"] = chats.scrub(str(note or ""))[:300] or None
    rec["review"] = {"state": "pending", "by": "appeal", "at": store.now()}
    store.put(db(), rec, "pending")
    store.log(db(), "appealed", rec["id"])
    return None


# The moderation log (2026-10-22, the Roadmap's "A public moderation log"): each line says what was done and by which
# role, never by which pen name. A listing is named only while it is on the list; a turned-down one stays "a listing".
LOG_TEXT = {
    "checked": "Reviews checked {L}.",
    "turned_down": "Reviews turned down a listing.",
    "reopened": "Members reported {L}, so it went back to review.",
    "appealed": "The member who added {L} asked for another look, so it went back to review with fresh reviewers.",
    "fixed": "A {by} fixed {fields} on {L}.",
    "suggestion_used": "A {by} used a member's suggested fix on {L}.",
    "suggestion_dropped": "A {by} set aside a member's suggested fix on {L}.",
    "kind_merged": "A Steward merged the kind \u201c{a}\u201d into \u201c{c}\u201d.",
    "kind_apart": "A Steward kept the kinds \u201c{a}\u201d and \u201c{c}\u201d apart.",
    "kind_unmerged": "A Steward undid the merge of the kind \u201c{a}\u201d.",
    "area_added": "A Steward added the area {name}.",
    "area_removed": "A Steward removed the area {name}.",
    "checkin_opened": "A Steward opened check-in for {L}.",
    "steward_named": "A member became a Steward.",
    "rank_reset": "A Steward reset a member's rank to zero.",
    "tier_given": "A Steward set a member's tier by hand: {tier}.",
    "taken_out": "A Steward took out a listing.",
    "flyer": "A Steward attached a flyer to {L}.",
    "rank_appeal": "A member asked the stewards to look again at their rank reset.",
    "rank_restored": "A Steward looked again and restored a member's rank.",
    "rank_kept": "A Steward looked again and kept a member's rank reset.",
    "org_proven": "The organiser {org} proved its page.",
    "org_vouched": "A Steward vouched for the organiser {org}.",
    "org_claimed": "The organiser {org} claimed {L}.",
    "org_claim_granted": "A Steward gave {L} to the organiser {org}.",
    "org_claim_refused": "A Steward turned down a claim on {L}.",
    "org_updated": "The organiser {org} updated {fields} on {L}.",
    "org_checkin": "The organiser {org} opened check-in for {L}.",
    "dup_merged": "A {by} merged a copy into {L}.",
    "dup_apart": "A {by} marked {L} and a look-alike on the same day as different events.",
}
FIELD_WORDS = {"name": "the name", "start_date": "the date", "start_time": "the start time", "end_date": "the end date",
               "end_time": "the end time", "location_name": "the place", "location_locality": "the town",
               "location_address": "the address", "price": "the price", "website": "the organiser's link",
               "tickets_url": "the tickets link", "tags": "the kinds", "description": "the description", "modes": "the modes",
               "recurrence": "the repeat", "slots": "the shifts", "requirements": "what it asks for",
               "listing_kind": "the kind of listing", "status": "the status", "organiser": "the organiser",
               "summary": "the summary", "online": "online or not", "org_note": "its update note"}


def log_entries(before: int | None) -> dict:
    out, rows = [], store.modlog(db(), before, 101)
    for e in rows[:100]:
        rec = store.get(db(), e["listing_id"]) if e["listing_id"] else None
        shown = (e["kind"] not in ("turned_down", "taken_out") and rec is not None
                 and rec.get("review", {}).get("state") in ("approved", "pending") and not withheld(public(dict(rec))))
        d = {k: v for k, v in e["data"].items()}
        if "fields" in d:
            words = [FIELD_WORDS.get(f, "a detail") for f in d["fields"]]
            d["fields"] = ", ".join(dict.fromkeys(words)) or "a detail"
        try:
            text = LOG_TEXT[e["kind"]].format(L=f"\u201c{rec['name']}\u201d" if shown else "a listing", **d)
        except (KeyError, IndexError):
            continue
        if gate.hit(GATE, text):
            continue
        out.append({"id": e["id"], "day": e["day"], "text": text, "listing": e["listing_id"] if shown else None})
    return {"entries": out, "more": len(rows) > 100}


def reported(rec: dict) -> list[dict]:
    """A listing's open reports as reviewers read them: the reason and the note, never who sent it."""
    out = []
    for r in store.reports_for(db(), rec["id"]):
        note = r["note"] if r["note"] and not gate.hit(GATE, r["note"]) else None
        out.append({"reason": REPORT_REASONS.get(r["reason"], r["reason"]), "note": note})
    return out


class Handler(BaseHTTPRequestHandler):
    server_version = "TheWheel"

    def version_string(self):  # the Server header names no software or version
        return self.server_version

    def log_message(self, fmt, *args):
        sys.stderr.write("%s %s\n" % (self.log_date_time_string(), fmt % args))

    def cors(self):
        origin = self.headers.get("Origin")
        if origin and origin in ORIGINS:
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Access-Control-Allow-Headers", "content-type, authorization, x-wheel-organiser")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Max-Age", "600")
            self.send_header("Vary", "Origin")

    def send(self, code: int, body, ctype="application/json; charset=utf-8", disposition: str | None = None):
        data = body if isinstance(body, bytes) else json.dumps(body, ensure_ascii=False).encode()
        if not ctype.startswith(("image/", "application/wasm", "application/octet-stream")):
            h = gate.hit(GATE, data)  # F4: the last look before anything leaves
            if h:
                sys.stderr.write(f"gate: answer to {self.command} {urlsplit(self.path).path} held back (/{h}/)\n")
                code, ctype = 500, "application/json; charset=utf-8"
                data = json.dumps({"error": HELD}).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        if disposition:
            self.send_header("Content-Disposition", disposition)
        self.cors()
        self.end_headers()
        self.wfile.write(data)

    def do_OPTIONS(self):
        if self.headers.get("Origin") in ORIGINS and urlsplit(self.path).path.startswith("/api/"):
            self.send_response(204)
            self.cors()
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        self.fail(404, "That address is empty.")

    def fail(self, code: int, message: str):
        self.send(code, {"error": message})

    def account(self) -> str | None:
        """The caller's pen name, from the Semaphore session token, or None."""
        h = self.headers.get("Authorization") or ""
        if not h.startswith("Bearer "):
            return None
        code, data = zk_call("GET", "/session", "token=" + h[7:].strip()[:100], admin=True)
        if code != 200:
            return None
        acct = json.loads(data).get("account")
        if acct:
            store.ensure_account(db(), acct)
        return acct

    def base(self) -> str:
        """This server's own address as the caller reached it: the start of a share link."""
        host = re.sub(r"[^A-Za-z0-9.:-]", "", self.headers.get("Host") or "localhost")
        local = host.split(":")[0] in ("localhost", "127.0.0.1")
        return f"{'http' if local else 'https'}://{host}"

    def organiser(self) -> dict | None:
        """The organiser account whose key came with this request, or None. Never read beside a member's login."""
        return organisers.by_key(db(), self.headers.get("X-Wheel-Organiser"))

    def org_need(self) -> dict | None:
        o = self.organiser()
        if o is None:
            self.send(401, {"error": "That needs your organiser account, on the For organisers page."})
        return o

    def watcher(self) -> bool:
        tok, given = watch_token(), self.headers.get("X-Wheel-Watch") or ""
        return bool(tok) and secrets.compare_digest(tok, given)

    def need(self, min_tier: int = 0) -> tuple[str | None, int]:
        acct = self.account()
        if acct is None:
            self.send(401, {"error": JOIN_FIRST, "login": True})
            return None, -1
        t = rep.tier(db(), acct)
        if t < min_tier:
            self.send(403, {"error": f"That needs the {rep.TIER_NAME[min_tier]} tier."})
            return None, t
        return acct, t

    def body(self) -> dict:
        n = int(self.headers.get("Content-Length") or 0)
        if n > MAX_BODY:
            raise ValueError("That file is over 12 MB. Send a smaller image.")
        return json.loads(self.rfile.read(n) or b"{}")

    def do_GET(self):
        try:
            return self.get()
        except Exception as exc:
            sys.stderr.write(f"error on GET {self.path}: {exc!r}\n")
            return self.fail(500, "The hub hit an error. The terminal running it has the detail.")

    def get(self):
        u = urlsplit(self.path)
        p = parse_qs(u.query)
        if u.path.startswith("/api/zk/") and ("GET", u.path[7:]) in ZK_PUBLIC:
            code, data = zk_call("GET", u.path[7:], u.query)
            return self.send(code, data)
        if u.path == "/api/events":
            member = bool(self.headers.get("Authorization")) and self.account() is not None
            return self.send(200, listing(p, member))
        if u.path == "/api/review":
            mine = self.account()
            t = rep.tier(db(), mine) if mine else -1
            recs = [r for r in store.events(db(), ("pending",)) if not withheld(public(dict(r)))]  # judged as it would leave
            today = datetime.now(TZ).date().isoformat()
            for r in recs:
                dated(r, today)
                r["duplicates"] = store.likely_duplicates(db(), r)
                r["certainty"] = settle(dict(r))["certainty"]
                r["mine"] = bool(mine) and r.get("deposited_account") == mine
                mv = [x["verdict"] for x in store.reviews_for(db(), r["id"])
                      if x["account"] == mine and x["round"] == r.get("round", 0)]
                r["my_verdict"] = mv[0] if mv else None
                sugs = store.suggestions_for(db(), r["id"])
                r["my_suggestion"] = bool(mine) and any(sg["account"] == mine for sg in sugs)
                if t >= 2 and sugs:  # suggested fixes go to those who can use them
                    r["suggestions"] = shown_suggestions(sugs)
                if mine:  # reports go to signed-in members, like a group's announcement
                    r["reports"] = reported(r)
                for_viewer(public(r), bool(mine))
            return self.send(200, {"events": recs, "me": rep.summary(db(), mine) if mine else None})
        if u.path == "/api/support":
            return self.send(200, support_config())
        if u.path == "/api/profile":
            acct, t = self.need(0)
            if acct is None:
                return
            return self.send(200, my_profile(acct))
        m = re.fullmatch(r"/api/p/([0-9a-f]{16})", u.path)
        if m:
            pen, d = m.group(1), db()
            if not d.execute("SELECT 1 FROM accounts WHERE account=?", (pen,)).fetchone():
                return self.fail(404, "No member goes by that pen name.")
            me = self.account() if self.headers.get("Authorization") else None
            viewer = "me" if me == pen else "mem" if me else "all"
            sup = support.active(d, pen)
            return self.send(200, {"pen": pen, "tier_name": rep.TIER_NAME[rep.tier(d, pen)], "viewer": viewer,
                                   "profile": support.shown(support.get_profile(d, pen), viewer, sup,
                                                            support.count(d) >= support.FLOOR)})
        m = re.fullmatch(r"/api/support/order/([A-Za-z0-9_-]{20,64})", u.path)
        if m:
            st = support.order_status(db(), m.group(1))
            return self.send(200, st) if st else self.fail(404, "That order has ended: an unpaid order lasts a day.")
        if u.path == "/api/support/watch":
            if not self.watcher():
                return self.fail(404, "That address is empty.")
            _watch_seen[0] = time.time()
            return self.send(200, {"orders": support.watch_list(db()), "address": support.XMR_ADDRESS})
        if u.path == "/api/modlog":  # the public moderation log, newest first, 100 at a time
            bf = p.get("before", [""])[0]
            return self.send(200, log_entries(int(bf) if bf.isdigit() else None))
        if u.path == "/api/mine":  # a member's own listings and any rank reset, for their Me page
            acct, t = self.need(0)
            if acct is None:
                return
            row = db().execute("SELECT reset_day FROM accounts WHERE account=?", (acct,)).fetchone()
            open_appeal = [a for a in store.appeals(db()) if a["account"] == acct]
            mine = [{"id": r["id"], "name": r.get("name"), "date": r.get("start_date"), "state": r.get("review", {}).get("state"),
                     "appealed": bool(r.get("appealed"))} for r in store.deposits(db(), acct) if not withheld(public(dict(r)))]
            return self.send(200, {"listings": mine, "reset_day": row["reset_day"] if row else None, "rank_appeal": bool(open_appeal)})
        if u.path == "/api/org/me":  # the organiser's own account: its code, its claims
            o = self.org_need()
            if o is None:
                return
            claims = []
            for c in organisers.claims_for(db(), o["id"]):
                r = store.get(db(), c["listing_id"])
                if r and not withheld(public(dict(r))):
                    claims.append({"id": r["id"], "name": r["name"], "date": r["start_date"], "state": c["state"],
                                   "listing": {k: r.get(k) for k in ORG_FIELDS + ("name", "org_note")}})
            return self.send(200, {"organiser": {**organisers.public(o), "code": o["code"], "asked": bool(o["vouch_asked"])},
                                   "claims": claims})
        m = re.fullmatch(r"/api/o/([0-9a-f]{16})", u.path)
        if m:  # an organiser as everyone sees it: name, page, proven, the listings it keeps
            o = organisers.get(db(), m.group(1))
            if o is None or not o["verified_day"]:
                return self.fail(404, "No proven organiser by that address.")
            held = [k for k, v in claimed_map().items() if v["id"] == o["id"]]
            recs = [store.get(db(), k) for k in held]
            today = datetime.now(TZ).date().isoformat()
            shown = [dated(r, today) for r in recs if r and r["review"].get("state") in ("approved", "pending") and not withheld(public(r))]
            return self.send(200, {"organiser": organisers.public(o),
                                   "listings": [{"id": r["id"], "name": r["name"], "date": share.on(r), "past": r["past"]} for r in shown]})
        if u.path == "/api/org/waiting":  # stewards: organisers asking for a vouch, claims to decide
            acct, t = self.need(3)
            if acct is None:
                return
            claims = []
            for c in organisers.claims_waiting(db()):
                r, o = store.get(db(), c["listing_id"]), organisers.get(db(), c["organiser_id"])
                if r and o:
                    claims.append({"listing": r["id"], "name": r["name"], "links": [x for x in (r.get("website"), r.get("tickets_url"),
                                   (r.get("source") or {}).get("url")) if x], "organiser": organisers.public(o)})
            return self.send(200, {"vouch": [organisers.public(o) for o in organisers.waiting_vouch(db())], "claims": claims})
        if u.path == "/api/duplicates":  # look-alike listings on the same day, for Review
            return self.send(200, {"pairs": duplicate_pairs()})
        if u.path == "/api/appeals":  # stewards: rank appeals waiting for a look
            acct, t = self.need(3)
            if acct is None:
                return
            return self.send(200, {"appeals": store.appeals(db())})
        if u.path == "/api/fund":  # the pool toward The Wheel's own AI: the total and the count, never who or when
            t = store.fund_total(db())
            return self.send(200, {"raised": t["raised"], "gifts": t["gifts"], "goal": FUND_GOAL, "steps": FUND_STEPS})
        if u.path == "/api/active":  # members in good standing: the cover a check-in can count on
            return self.send(200, {"active": active_members()})
        if u.path == "/api/me":
            acct = self.account()
            return self.send(200, {"me": rep.summary(db(), acct) if acct else None})
        if u.path == "/api/areas":
            return self.send(200, {"areas": store.areas(db())})
        if u.path == "/api/kinds":  # stewards: near-twin kinds to merge or keep apart
            acct, t = self.need(3)
            if acct is None:
                return
            merged = store.merges(db())
            counts: dict[str, int] = {}
            for r in store.events(db(), ("approved", "pending")):
                for tg in kinds.apply(r.get("tags") or [], merged):
                    counts[tg] = counts.get(tg, 0) + 1
            return self.send(200, {"suggestions": kinds.suggest(counts, store.kept_apart(db())), "kinds": len(counts),
                                   "merged": [{"alias": a, "canonical": c} for a, c in sorted(merged.items())]})
        base = self.base()
        m = re.fullmatch(r"/l/([0-9a-f]{16})", u.path)
        if m:  # a share link: a preview for chat apps, then on to the listing
            rec = shown_listing(m.group(1))
            if rec is None:
                return self.send(404, share.gone(SITE + "#night").encode(), TYPES[".html"])
            fl = (rec.get("source") or {}).get("flyer")
            return self.send(200, share.page(rec, share_url(base, rec["id"]), f"{SITE}#l/{rec['id']}",
                                             f"{base}/api/flyer/{fl}" if fl and flyer.NAME.fullmatch(str(fl)) else None).encode(),
                             TYPES[".html"])
        m = re.fullmatch(r"/api/ics/([0-9a-f]{16})\.ics", u.path)
        if m:  # one listing for your calendar, on the date it is shown on
            rec = shown_listing(m.group(1))
            if rec is None:
                return self.fail(404, "That listing has gone, or is waiting for review.")
            days = share.dates_for_feed(rec) if p.get("all", [""])[0] == "1" else [share.on(rec)]  # ?all=1: every date ahead
            return self.send(200, share.calendar([(rec, d, share_url(base, rec["id"])) for d in days], rec["name"]),
                             "text/calendar; charset=utf-8", f'attachment; filename="the-wheel-{rec["id"]}.ics"')
        if u.path in ("/api/feed.ics", "/api/feed.xml"):  # subscribe once: checked listings, in one mode or all
            mode = p.get("mode", [""])[0]
            mode = mode if mode in MODES else None
            items = feed_items(mode)
            title = "The Wheel" + (f" · {mode.capitalize()}" if mode else "")
            if u.path.endswith(".ics"):
                return self.send(200, share.calendar([(r, day, share_url(base, r["id"])) for r in items
                                                      for day in share.dates_for_feed(r)], title), "text/calendar; charset=utf-8")
            return self.send(200, share.rss([(r, share_url(base, r["id"])) for r in items], title, SITE + (f"#{mode}" if mode else "")),
                             "application/rss+xml; charset=utf-8")
        if u.path in ("/api/digest", "/api/digest.xml"):  # the week ahead: the weekly push reads it, and feed readers
            d = share.digest(feed_items(None), datetime.now(TZ).date().isoformat(), SITE)
            if u.path.endswith(".xml"):
                return self.send(200, share.digest_rss(d, base + u.path), "application/rss+xml; charset=utf-8")
            return self.send(200, d)
        m = re.fullmatch(r"/api/flyer/([0-9a-f]{16}\.webp)", u.path)
        if m:
            f = FLYERS / m.group(1)
            if f.is_file() and store.flyer_in_use(db(), m.group(1)):
                return self.send(200, f.read_bytes(), "image/webp")
            return self.fail(404, "That address is empty.")
        if API_ONLY:
            return self.fail(404, "That address is empty.")
        if u.path == "/__wait":  # test aid: a slow pixel holds the page's load event for screenshots
            time.sleep(min(int(p.get("ms", ["2000"])[0]), 8000) / 1000)
            return self.send(200, base64.b64decode("R0lGODlhAQABAAAAACw="), "image/gif")
        if SELFTEST and u.path == "/selftest.html":
            return self.send(200, (ROOT / "tests" / "browser" / "selftest.html").read_bytes(), TYPES[".html"])
        name = "index.html" if u.path in ("/", "") else u.path.lstrip("/")
        f = (STATIC / name).resolve()
        if STATIC.resolve() in f.parents and f.is_file():
            return self.send(200, f.read_bytes(), TYPES.get(f.suffix, "application/octet-stream"))
        return self.fail(404, "That address is empty.")

    def do_POST(self):
        u = urlsplit(self.path)
        if u.path.startswith("/api/zk/"):
            n = int(self.headers.get("Content-Length") or 0)
            if n > 64 * 1024:
                return self.fail(400, "That request is too large.")
            raw = self.rfile.read(n)
            sub = u.path[7:]
            if sub == "/join-work":
                return self.send(200, join_work())
            if ("POST", sub) in ZK_PUBLIC:
                if sub == "/join":  # the work first, so junk joins cost work and leave the day's cap to real ones
                    try:
                        jb = json.loads(raw or b"{}")
                        w = jb.get("work") or {}
                        ok = work_ok(w.get("nonce"), str(jb.get("commitment", "")), w.get("n"))
                    except (ValueError, AttributeError):
                        ok = False
                    if not ok:
                        return self.send(400, {"ok": False, "why": "work"})
                    raw = json.dumps({"commitment": str(jb.get("commitment", ""))}).encode()
                    if over_cap("join"):
                        return self.fail(429, CAP_TEXT["join"])
                code, data = zk_call("POST", sub, body=raw)
                return self.send(code, data)
            if sub == "/checkin":  # opening a check-in makes a door code: stewards only
                acct, t = self.need(3)
                if acct is None:
                    return
                code, data = zk_call("POST", "/checkin", body=raw, admin=True)
                if code == 200:
                    try:
                        eid = str(json.loads(raw or b"{}").get("event", ""))
                        if re.fullmatch(r"[0-9a-f]{16}", eid):
                            store.log(db(), "checkin_opened", eid)
                    except ValueError:
                        pass
                return self.send(code, data)
            return self.fail(404, "That address is empty.")
        try:
            b = self.body()
            if u.path == "/api/profile":
                acct, t = self.need(0)
                if acct is None:
                    return
                support.save_profile(db(), acct, b)
                return self.send(200, my_profile(acct))
            if u.path == "/api/support/redeem":
                acct, t = self.need(0)
                if acct is None:
                    return
                if store.count_deposit(db(), "redeem:" + acct, datetime.now(TZ).date().isoformat()) > 10:
                    return self.fail(429, "Ten tries a day. Check the code and try tomorrow.")
                new = support.redeem(db(), acct, str(b.get("code", ""))[:40])
                if not new:
                    return self.fail(400, "That code is unknown or already used. Check it letter by letter.")
                return self.send(200, {**my_profile(acct), "added_until": new})
            if u.path == "/api/support/order":
                if not monero_open():
                    return self.fail(503, "Monero orders are paused while the payment watcher is offline. Try again later, or pay another way.")
                rate = support.xmr_nzd()
                if not rate:
                    return self.fail(503, "The Monero price failed to load. Try again in a few minutes.")
                if over_cap("order"):
                    return self.fail(429, CAP_TEXT["order"])
                months, nzd = b.get("months"), b.get("nzd")
                return self.send(200, support.open_order(db(), int(months) if str(months).isdigit() else 0,
                                                         float(nzd) if isinstance(nzd, (int, float)) else 0, rate))
            if u.path == "/api/support/watch":
                if not self.watcher():
                    return self.fail(404, "That address is empty.")
                _watch_seen[0] = time.time()
                st = support.watch_report(db(), str(b.get("id", "")), int(b.get("confirmations") or 0))
                return self.send(200, {"state": st})
            if u.path == "/api/read":
                acct, t = self.need(0)
                if acct is None:
                    return
                day = datetime.now(TZ).date().isoformat()
                # each reading costs a cent or two of AI: twice the day's deposit allowance
                if store.count_deposit(db(), "read:" + acct, day) > 2 * rep.DAILY_DEPOSITS[t]:
                    return self.fail(429, "That's today's reading allowance. More tomorrow, or as your rep grows.")
                if over_cap("read"):
                    return self.fail(429, CAP_TEXT["read"])
                return self.send(200, self.read_deposit(b))
            if u.path == "/api/submit":
                acct, t = self.need(0)
                if acct is None:
                    return
                day = datetime.now(TZ).date().isoformat()
                saved = []
                for rec in b.get("records", []):
                    if over_cap("submit"):
                        return self.send(429, {"error": CAP_TEXT["submit"], "saved": saved})
                    if store.count_deposit(db(), acct, day) > rep.DAILY_DEPOSITS[t]:
                        return self.send(429, {"error": f"That's today's {rep.DAILY_DEPOSITS[t]} listings for your tier.", "saved": saved})
                    rec.pop("duplicates", None)
                    fl = (rec.get("source") or {}).get("flyer")
                    if fl and not (flyer.NAME.fullmatch(str(fl)) and (FLYERS / str(fl)).is_file()):
                        rec["source"].pop("flyer", None)  # only a flyer this server cleaned and kept
                    rec = clean(rec, rec)
                    rec["deposited_by"] = None  # names stay out: the pen name below is enough
                    rec["deposited_account"], rec["deposit_day"] = acct, day
                    store.put(db(), rec, "pending")
                    saved.append(rec["id"])
                return self.send(200, {"saved": saved})
            m = re.fullmatch(r"/api/review/([0-9a-f]{16})", u.path)
            if m:
                rec = store.get(db(), m.group(1))
                if rec is None:
                    return self.fail(404, "That event is gone. Reload the review list.")
                acct, t = self.need(0)
                if acct is None:
                    return
                action = b.get("action")
                if action not in ("approve", "reject", "save", "suggest"):
                    return self.fail(400, "Pick approve, save, suggest or reject.")
                if rec.get("deposited_account") == acct:
                    return self.fail(403, "You added this one, so someone else checks it.")
                if steps_aside(rec, acct):
                    return self.fail(403, "You reviewed this before its appeal, so other members look at it now.")
                if action == "suggest":  # below the Reviewer tier: a fix waits for a Reviewer or Steward (his ruling 2026-10-21)
                    fields = changes(rec, b.get("edits") or {})
                    if not fields:
                        return self.fail(400, "Change a detail first, then send it.")
                    store.suggest(db(), rec["id"], acct, fields, datetime.now(TZ).date().isoformat())
                    return self.send(200, {"suggested": sorted(fields)})
                edited, before = False, rec["review"].get("state")
                if t >= 2:  # fixing a listing's fields: Reviewer tier and up
                    fixed = sorted(changes(rec, b.get("edits") or {}))
                    rec = clean(rec, b.get("edits") or {})
                    edited = True
                    if fixed:
                        store.log(db(), "fixed", rec["id"], by=rep.TIER_NAME[t], fields=fixed)
                elif action == "save":
                    return self.fail(403, "Fixing a listing's details needs the Reviewer tier. You can approve or reject it.")
                if action in ("approve", "reject"):
                    store.cast_review(db(), rec["id"], acct, action, rep.WEIGHT[t], datetime.now(TZ).date().isoformat(),
                                      rec.get("round", 0))
                rec = settle(rec)
                if rec["review"]["state"] != "pending":  # settled again: its reports are answered
                    rec.pop("reopened", None)
                    store.close_reports(db(), rec["id"])
                if rec["review"]["state"] != before and rec["review"]["state"] in ("approved", "rejected"):
                    store.log(db(), "checked" if rec["review"]["state"] == "approved" else "turned_down", rec["id"])
                store.put(db(), rec, rec["review"]["state"])
                return self.send(200, {"event": public(dict(rec)), "edited": edited, "me": rep.summary(db(), acct)})
            if u.path == "/api/org/new":  # a new organiser account; its key is shown once
                if over_cap("org"):
                    return self.fail(429, CAP_TEXT["org"])
                return self.send(200, organisers.new(db(), b.get("name"), b.get("page")))
            if u.path == "/api/org/check":  # look for the organiser's code on its page
                o = self.org_need()
                if o is None:
                    return
                if o["verified_day"]:
                    return self.send(200, {"proven": True})
                if store.count_deposit(db(), "orgcheck:" + o["id"], datetime.now(TZ).date().isoformat()) > 10:
                    return self.fail(429, "Ten checks a day. Try again tomorrow, or ask a steward.")
                try:
                    body, _ = core._fetch(o["page"])
                except Exception as exc:  # a page that refuses outside readers, or one that is gone
                    sys.stderr.write(f"org check {o['id']}: {exc!r}\n")
                    return self.send(200, {"proven": False, "why": "fetch"})
                if not organisers.page_shows(body, o["code"]):
                    return self.send(200, {"proven": False, "why": "code"})
                organisers.prove(db(), o["id"], "page")
                store.log(db(), "org_proven", org=o["name"])
                return self.send(200, {"proven": True})
            if u.path == "/api/org/ask":  # a page The Wheel cannot read: a steward vouches instead
                o = self.org_need()
                if o is None:
                    return
                organisers.ask_vouch(db(), o["id"])
                return self.send(200, {"asked": True})
            m = re.fullmatch(r"/api/org/(claim|update|checkin)/([0-9a-f]{16})", u.path)
            if m:
                o = self.org_need()
                if o is None:
                    return
                rec = store.get(db(), m.group(2))
                if rec is None or rec.get("review", {}).get("state") not in ("approved", "pending"):
                    return self.fail(404, "That listing has gone.")
                if m.group(1) == "claim":
                    try:
                        st = organisers.claim(db(), o, rec)
                    except PermissionError as exc:
                        return self.fail(403, str(exc))
                    if st == "claimed":
                        store.log(db(), "org_claimed", rec["id"], org=o["name"])
                    return self.send(200, {"state": st})
                if not organisers.holds(db(), o, rec["id"]):
                    return self.fail(403, "Claim this listing first.")
                if m.group(1) == "update":
                    changed = org_update(rec, o, b)
                    if changed:
                        store.log(db(), "org_updated", rec["id"], org=o["name"], fields=changed)
                    return self.send(200, {"changed": changed})
                code, data = zk_call("POST", "/checkin", body=json.dumps({"event": rec["id"], "rotating": True}).encode(), admin=True)
                if code == 200:
                    store.log(db(), "org_checkin", rec["id"], org=o["name"])
                return self.send(code, data)
            m = re.fullmatch(r"/api/org/([0-9a-f]{16})/vouch", u.path)
            if m:  # a steward vouches for an organiser whose page The Wheel cannot read
                acct, t = self.need(3)
                if acct is None:
                    return
                o = organisers.get(db(), m.group(1))
                if o is None:
                    return self.fail(404, "That organiser has gone.")
                organisers.prove(db(), o["id"], "steward")
                store.log(db(), "org_vouched", org=o["name"])
                return self.send(200, {"proven": True})
            m = re.fullmatch(r"/api/org/claims/([0-9a-f]{16})", u.path)
            if m:  # a steward decides a claim on a listing that links elsewhere
                acct, t = self.need(3)
                if acct is None:
                    return
                if b.get("action") not in ("grant", "refuse"):
                    return self.fail(400, "Pick grant or refuse.")
                c = organisers.answer_claim(db(), m.group(1), b["action"] == "grant")
                if c is None:
                    return self.fail(404, "That claim has gone. Reload the page.")
                o = organisers.get(db(), c["organiser_id"])
                store.log(db(), "org_claim_granted" if b["action"] == "grant" else "org_claim_refused", m.group(1), org=o["name"] if o else "")
                return self.send(200, {"ok": True})
            if u.path == "/api/duplicates":  # a Reviewer merges a copy, or keeps two look-alikes apart
                acct, t = self.need(2)
                if acct is None:
                    return
                ids = [str(b.get("keep") or b.get("a") or ""), str(b.get("drop") or b.get("b") or "")]
                recs = [store.get(db(), i) if re.fullmatch(r"[0-9a-f]{16}", i) else None for i in ids]
                if None in recs or ids[0] == ids[1]:
                    return self.fail(404, "One of those listings has gone. Reload Review.")
                if acct in (recs[0].get("deposited_account"), recs[1].get("deposited_account")):
                    return self.fail(403, "You added one of these, so someone else decides.")
                if b.get("action") == "merge":
                    if recs[1]["review"].get("state") not in ("approved", "pending"):
                        return self.fail(400, "That copy is already out of the list.")
                    merge_copy(recs[0], recs[1])
                    store.log(db(), "dup_merged", recs[0]["id"], by=rep.TIER_NAME[t])
                elif b.get("action") == "apart":
                    store.keep_dups_apart(db(), ids[0], ids[1], datetime.now(TZ).date().isoformat())
                    store.log(db(), "dup_apart", ids[0], by=rep.TIER_NAME[t])
                else:
                    return self.fail(400, "Pick merge or apart.")
                return self.send(200, {"ok": True})
            m = re.fullmatch(r"/api/appeal/([0-9a-f]{16})", u.path)
            if m:  # another look at a turned-down listing, asked by the member who added it
                rec = store.get(db(), m.group(1))
                if rec is None:
                    return self.fail(404, "That listing has gone.")
                acct, t = self.need(0)
                if acct is None:
                    return
                why = file_appeal(rec, acct, b.get("note"))
                return self.fail(403, why) if why else self.send(200, {"appealed": True})
            if u.path == "/api/appeal-rank":  # a member whose rank was reset asks the stewards to look again
                acct, t = self.need(0)
                if acct is None:
                    return
                row = db().execute("SELECT reset_day FROM accounts WHERE account=?", (acct,)).fetchone()
                if not row or not row["reset_day"]:
                    return self.fail(400, "Your rank has had no reset to appeal.")
                store.appeal_rank(db(), acct, chats.scrub(str(b.get("note") or ""))[:500] or None, datetime.now(TZ).date().isoformat())
                store.log(db(), "rank_appeal")
                return self.send(200, {"appealed": True})
            m = re.fullmatch(r"/api/appeals/(\d+)", u.path)
            if m:  # a steward's answer to a rank appeal
                acct, t = self.need(3)
                if acct is None:
                    return
                if b.get("action") not in ("restore", "keep"):
                    return self.fail(400, "Pick restore or keep.")
                ap = [x for x in store.appeals(db()) if x["id"] == int(m.group(1))]
                if not ap:
                    return self.fail(404, "That appeal has gone. Reload the page.")
                if ap[0]["account"] == acct:  # a steward never answers their own appeal
                    return self.fail(403, "That's your own appeal, so another steward answers it.")
                store.close_appeal(db(), ap[0]["id"], "restored" if b["action"] == "restore" else "kept")
                store.log(db(), "rank_restored" if b["action"] == "restore" else "rank_kept")
                return self.send(200, {"ok": True})
            m = re.fullmatch(r"/api/report/([0-9a-f]{16})", u.path)
            if m:  # a member says a listing is wrong, over or unsafe; enough weight sends a checked one back to review
                rec = store.get(db(), m.group(1))
                if rec is None or rec.get("review", {}).get("state") not in ("approved", "pending"):
                    return self.fail(404, "That listing has gone. Reload the list.")
                acct, t = self.need(0)
                if acct is None:
                    return
                reason = b.get("reason")
                if reason not in REPORT_REASONS:
                    return self.fail(400, "Pick what's wrong: the details, cancelled or over, or unsafe.")
                day = datetime.now(TZ).date().isoformat()
                if store.count_deposit(db(), "report:" + acct, day) > 10:
                    return self.fail(429, "That's ten reports today. More tomorrow.")
                return self.send(200, {"reopened": file_report(rec, acct, t, reason, b.get("note"), day)})
            m = re.fullmatch(r"/api/suggestion/(\d+)", u.path)
            if m:
                acct, t = self.need(2)  # using a suggested fix: Reviewer tier and up, as fixing is
                if acct is None:
                    return
                sg = store.suggestion(db(), int(m.group(1)))
                if sg is None:
                    return self.fail(404, "That suggestion is gone. Reload the review list.")
                rec = store.get(db(), sg["listing_id"])
                if rec and rec.get("deposited_account") == acct:
                    return self.fail(403, "You added this one, so someone else checks its fixes.")
                if b.get("action") == "use" and rec:
                    rec = clean(rec, sg["fields"])
                    store.put(db(), rec, rec["review"]["state"])
                elif b.get("action") not in ("use", "drop"):
                    return self.fail(400, "Pick use or drop.")
                store.log(db(), "suggestion_used" if b.get("action") == "use" else "suggestion_dropped", sg["listing_id"],
                          by=rep.TIER_NAME[t])
                store.drop_suggestion(db(), sg["id"])
                return self.send(200, {"event": public(dict(rec)) if rec else None})
            if u.path == "/api/kinds":
                acct, t = self.need(3)  # merging kinds: stewards, a person saying yes to each (his ruling)
                if acct is None:
                    return
                a, k = str(b.get("merge") or "").strip().lower(), str(b.get("keep") or "").strip().lower()
                if b.get("action") == "merge" and a and k:
                    store.merge_tag(db(), a, k)
                    store.log(db(), "kind_merged", a=a, c=k)
                elif b.get("action") == "keep" and a and k:
                    store.keep_apart(db(), a, k)
                    store.log(db(), "kind_apart", a=a, c=k)
                elif b.get("action") == "undo" and a:
                    store.unmerge_tag(db(), a)
                    store.log(db(), "kind_unmerged", a=a)
                else:
                    return self.fail(400, "Pick merge, keep apart or undo, with the two kinds.")
                return self.send(200, {"ok": True})
            if u.path == "/api/areas" or u.path.startswith("/api/areas/"):
                acct, t = self.need(3)  # areas: stewards only for now
                if acct is None:
                    return
            if u.path == "/api/areas":
                name = (b.get("name") or "").strip()
                if not name:
                    return self.fail(400, "Give the area a name.")
                area = store.add_area(db(), name, float(b["lat"]), float(b["lng"]), float(b.get("reach_km") or 5), b.get("by"))
                store.log(db(), "area_added", name=name)
                return self.send(200, area)
            m = re.fullmatch(r"/api/areas/(\d+)/delete", u.path)
            if m:
                gone = [x["name"] for x in store.areas(db()) if x["id"] == int(m.group(1))]
                store.delete_area(db(), int(m.group(1)))
                if gone:
                    store.log(db(), "area_removed", name=gone[0])
                return self.send(200, {"deleted": int(m.group(1))})
            return self.fail(404, "That address is empty.")
        except ValueError as exc:
            return self.fail(400, str(exc))
        except Exception as exc:  # the page gets a plain line; the server log keeps the detail
            sys.stderr.write(f"error on {u.path}: {exc!r}\n")
            return self.fail(500, "Something stopped on the server. Try again, or paste the event's text instead of a link or flyer.")

    def read_deposit(self, b: dict) -> dict:
        received = datetime.now(timezone.utc)
        if b.get("image"):
            UPLOADS.mkdir(parents=True, exist_ok=True)
            suffix = Path(b["image"].get("name") or "flyer.png").suffix.lower() or ".png"
            if suffix not in core.IMAGE_EXT:
                raise ValueError("Flyers need to be PNG, JPG, WEBP or GIF.")
            data = base64.b64decode(b["image"]["data"].split(",")[-1])
            with tempfile.NamedTemporaryFile(dir=UPLOADS, suffix=suffix, delete=False) as f:
                f.write(data)
            try:
                out = core.read(f.name, received, allow_path=True)  # our own temp file, never a path a member typed
                kept = None
                if out["records"]:
                    seen = out.get("visible_text") or ""
                    if gate.hit(GATE, seen):  # the flyer's own words carry a private mark: list it, never show it
                        sys.stderr.write("gate: a flyer was not kept (its text carries a private mark)\n")
                        out["notes"].append("The flyer itself stays off The Wheel; the listing can still go out.")
                    else:
                        kept = flyer.keep(FLYERS, flyer.clean(data))
                for r in out["records"]:
                    r["source"]["kind"] = "flyer"
                    if kept:
                        r["source"]["flyer"] = kept
            finally:
                Path(f.name).unlink(missing_ok=True)  # the upload as sent (with any GPS in it) is never kept
            if b.get("text"):  # a caption sent with the flyer: read it too (cleaned first when it came from a chat)
                cap = chats.scrub(b["text"]) if b.get("chat") or chats.is_chat(b["text"]) else b["text"]
                more = core.read(cap, received, allow_path=False)
                out["records"] += more["records"]
                out["notes"] += more["notes"]
                out["cost_usd"] += more["cost_usd"]
        else:
            raw = (b.get("text") or "").strip()
            if not raw:
                raise ValueError("Paste a post or a link, or add a flyer.")
            if b.get("chat") or chats.is_chat(raw):  # from a group chat: cleaned before the reader sees it
                cleaned, links = chats.scrub(raw), chats.group_links(raw)
                out = core.read(cleaned, received, allow_path=False) if cleaned.replace("[chat link]", "").strip() else \
                    {"records": [], "notes": ["A group link on its own gives the reader only a link: paste the announcement with it."], "cost_usd": 0}
                for r in out["records"]:
                    r["chat_text"] = cleaned[:4000]
                    if links:
                        r["chat_platform"], r["chat_link"] = links[0]
                    r.setdefault("chat_platform", "other")
            else:
                out = core.read(raw, received, allow_path=False)
        out.pop("visible_text", None)
        for r in out["records"]:
            if r.get("listing_kind") != "volunteer" and looks_like_festival(r):
                r["listing_kind"] = "festival"
            chats.sort_links(r)
            r["duplicates"] = store.likely_duplicates(db(), r)
            public(r)
        return out

def main():
    global GATE
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8790)
    a = ap.parse_args()
    try:
        GATE = gate.load()
    except gate.GateMissing as exc:
        sys.exit(f"The Wheel will not start: {exc}.")
    srv = ThreadingHTTPServer((os.environ.get("WHEEL_HOST", "127.0.0.1"), a.port), Handler)
    print(f"The Wheel on http://localhost:{a.port}/{'  (API only)' if API_ONLY else ''}  (Ctrl+C stops it)", flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
