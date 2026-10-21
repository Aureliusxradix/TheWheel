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

from hub import chats, flyer, gate, kinds, repeats, rep, store, support  # noqa: E402
from reader import core  # noqa: E402

STATIC = ROOT / "hub" / "static"
TZ = core.HUB_TZ  # days (today, the daily caps, review days) are Auckland days, whatever the host clock says
DATA = Path(os.environ.get("WHEEL_DATA") or ROOT / "data")  # the store's folder; the database itself: EVENTHUB_DB
UPLOADS = DATA / "uploads"
FLYERS = UPLOADS / "flyers"  # cleaned flyers only (hub/flyer.py); an upload as sent is never kept
LINK_FIELDS = ("website", "tickets_url")
ADMIN_TOKEN = Path(os.environ.get("WHEEL_ZK_ADMIN_FILE") or DATA / "zk-admin.token")
TYPES = {".wasm": "application/wasm", ".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8",
         ".css": "text/css; charset=utf-8", ".svg": "image/svg+xml", ".png": "image/png"}
EDITABLE = {"name", "summary", "description", "start_date", "start_time", "end_date", "end_time", "recurrence",
            "status", "location_name", "location_address", "location_locality", "price", "website",
            "tickets_url", "tags", "organiser", "online", "modes", "listing_kind", "slots", "requirements",
            "chat_platform", "chat_link", "chat_link_ok", "chat_text"}
MEMBERS_ONLY = ("chat_link", "chat_link_ok", "chat_text")  # a group's link and its announcement: signed-in members only
MODES = {"day", "night", "recovery"}
MAX_BODY = 12 * 1024 * 1024
ZK = os.environ.get("WHEEL_ZK_URL", "http://127.0.0.1:8792")  # zk/server.mjs, the member service (zk/run.sh)
SELFTEST = os.environ.get("WHEEL_SELFTEST") == "1"  # serves tests/browser/selftest.html, test runs only
ZK_PUBLIC = {("GET", "/group"), ("GET", "/count"), ("POST", "/join"), ("POST", "/showup"), ("POST", "/challenge"), ("POST", "/login")}
JOIN_FIRST = "Join The Wheel first, on the Me page. It takes one tap."
API_ONLY = os.environ.get("WHEEL_API_ONLY") == "1"
ORIGINS = {o.strip() for o in os.environ.get("WHEEL_ORIGINS", "").split(",") if o.strip()}
PRIVATE_FIELDS = ("deposited_by", "deposited_account", "deposit_day")  # who added a listing never leaves the server
HELD = "The Wheel held this answer back: it carried something that stays on the server."
GATE = None  # set in main(): the identity gate's compiled word list
# Whole-site daily caps (2026-10-20, going live; provisional, his to change). Joining needs no account, so per-account
# limits alone do not hold: a script could join without end, spend his Claude plan on readings, or fill the members
# list past the 1,024 the proving files cover (depth 10), which would lock every member out.
CAPS = {"join": int(os.environ.get("WHEEL_JOINS_PER_DAY", "50")),
        "read": int(os.environ.get("WHEEL_READS_PER_DAY", "60")),
        "submit": int(os.environ.get("WHEEL_SUBMITS_PER_DAY", "100")),
        "order": int(os.environ.get("WHEEL_ORDERS_PER_DAY", "100"))}
CAP_TEXT = {"join": "The Wheel has taken all the new members it takes in one day. Join tomorrow.",
            "read": "The Wheel has read all the posts it reads in one day. Paste it tomorrow, or fill the listing in by hand.",
            "submit": "The Wheel has taken all the new listings it takes in one day. Add it tomorrow.",
            "order": "The Wheel has opened all the Monero orders it opens in one day. Try tomorrow, or pay another way."}


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
            v = v if v in ("event", "volunteer") else "event"
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


def settle(rec: dict) -> dict:
    """Work out a listing's certainty from its reviews and move its state when it settles."""
    revs = store.reviews_for(db(), rec["id"])
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
    elif rec["review"].get("state") == "approved":  # checked before accounts existed: by him, as steward
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


def listing(params: dict, member: bool = False) -> dict:
    states = ("approved", "pending") if params.get("unreviewed", ["1"])[0] == "1" else ("approved",)
    all_areas = store.areas(db())
    today = datetime.now(TZ).date().isoformat()
    out = []
    merged = store.merges(db())
    for r in store.events(db(), states):
        if withheld(public(r)):
            continue
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
            "today": today}


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
            self.send_header("Access-Control-Allow-Headers", "content-type, authorization")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Max-Age", "600")
            self.send_header("Vary", "Origin")

    def send(self, code: int, body, ctype="application/json; charset=utf-8"):
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
                mv = [x["verdict"] for x in store.reviews_for(db(), r["id"]) if x["account"] == mine]
                r["my_verdict"] = mv[0] if mv else None
                sugs = store.suggestions_for(db(), r["id"])
                r["my_suggestion"] = bool(mine) and any(sg["account"] == mine for sg in sugs)
                if t >= 2 and sugs:  # suggested fixes go to those who can use them
                    r["suggestions"] = shown_suggestions(sugs)
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
                if action == "suggest":  # below the Reviewer tier: a fix waits for a Reviewer or Steward (his ruling 2026-10-21)
                    fields = changes(rec, b.get("edits") or {})
                    if not fields:
                        return self.fail(400, "Change a detail first, then send it.")
                    store.suggest(db(), rec["id"], acct, fields, datetime.now(TZ).date().isoformat())
                    return self.send(200, {"suggested": sorted(fields)})
                edited = False
                if t >= 2:  # fixing a listing's fields: Reviewer tier and up
                    rec = clean(rec, b.get("edits") or {})
                    edited = True
                elif action == "save":
                    return self.fail(403, "Fixing a listing's details needs the Reviewer tier. You can approve or reject it.")
                if action in ("approve", "reject"):
                    store.cast_review(db(), rec["id"], acct, action, rep.WEIGHT[t], datetime.now(TZ).date().isoformat())
                rec = settle(rec)
                store.put(db(), rec, rec["review"]["state"])
                return self.send(200, {"event": public(dict(rec)), "edited": edited, "me": rep.summary(db(), acct)})
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
                store.drop_suggestion(db(), sg["id"])
                return self.send(200, {"event": public(dict(rec)) if rec else None})
            if u.path == "/api/kinds":
                acct, t = self.need(3)  # merging kinds: stewards, a person saying yes to each (his ruling)
                if acct is None:
                    return
                a, k = str(b.get("merge") or "").strip().lower(), str(b.get("keep") or "").strip().lower()
                if b.get("action") == "merge" and a and k:
                    store.merge_tag(db(), a, k)
                elif b.get("action") == "keep" and a and k:
                    store.keep_apart(db(), a, k)
                elif b.get("action") == "undo" and a:
                    store.unmerge_tag(db(), a)
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
                return self.send(200, store.add_area(db(), name, float(b["lat"]), float(b["lng"]),
                                                     float(b.get("reach_km") or 5), b.get("by")))
            m = re.fullmatch(r"/api/areas/(\d+)/delete", u.path)
            if m:
                store.delete_area(db(), int(m.group(1)))
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
