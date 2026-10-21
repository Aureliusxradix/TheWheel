"""Supporters: prepaid months of looks, paid for with codes, shown on a profile the member shapes.

His calls (2026-10-21, 2026-10-22): the name Supporter; pay what you like from NZ$2 (NZ$5 suggested); codes, cash, PayPal
by hand and Monero matched by itself, to a subaddress of the aureliusxradix wallet kept for The Wheel; the watching
wallet on the box that runs the Monero node; sales open at launch; profiles in the Ledger layout.
Under the sink rule (ruled 2026-07-11): money buys looks, never standing. Rep, tiers, review weight, listing order and
the daily limits are untouched by anything here.

What this file refuses to hold:
  - which payment bought which code (an order and its code are deleted once the code is shown)
  - which account used which code (a code row keeps its day of use; the account keeps its months)
  - links, numbers, emails or @names on a profile (they join a profile to the member's other accounts)
"""
import hashlib
import json
import math
import os
import re
import secrets
import time
import urllib.request
from datetime import date, timedelta

from hub import chats

NAME = "Supporter"
MIN_NZD, SUGGEST_NZD = 2, 5
MONTHS = (1, 6, 12)
FLOOR = 15  # supporters before anyone's mark shows to others: the anonymity floor the Charter names (15 to 20)
XMR_ADDRESS = "82WBg4D1iXzHVXPQQ7B7UPagk4wKtLnD6EhW9yKvErRTdqbrSiseJ57L25x1KNxhckVE7PYQaRbTsZygcoDBRDdWJ8s8gRC"
ATOMIC = 10 ** 12  # piconero in one XMR
CONFIRMATIONS = 10
ORDER_PAY_S = 60 * 60          # the amount holds this long
ORDER_KEEP_S = 24 * 60 * 60    # a late payment still counts this long; then the order is gone
PAID_KEEP_S = 30 * 24 * 60 * 60  # a paid code waits this long to be shown
CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"  # no 0/O, 1/I/L

# Looks. Free ones for everyone; the rest while supporter months run. Colours stay clear of the anon face's teal and gold.
COLOURS = {"ink": ("", False), "rust": ("#C2603A", False), "sky": ("#3B8FD6", False), "leaf": ("#3E9B4F", False),
           "bloom": ("#E0459A", True), "violet": ("#7A4DFF", True), "rose": ("#E77FAF", True), "ember": ("#E8743B", True),
           "plum": ("#9B4DB0", True), "dusk": ("#5B5FC7", True), "moss": ("#7C9A2E", True)}
GLYPHS = {"ring": False, "bloom": True, "haze": True, "tide": True, "turning": True}
SIGNS = {"moon": "☾", "sun": "☀", "spark": "✦", "flower": "❀", "music": "♪", "clover": "☘", "water": "≈", "fire": "△"}
AUDIENCES = ("all", "mem", "me")  # everyone · members · only me
RANK = {"all": 0, "mem": 1, "me": 2}
TEXT = {"name": 40, "about": 280, "area": 40}
NO_LINKS = ("Profiles keep links, numbers, emails and @names off: each one joins this profile to your other accounts. "
            "Take it out and save again.")


# ---------- codes ----------
def norm_code(code: str) -> str:
    c = re.sub(r"[^A-Za-z0-9]", "", str(code or "")).upper()
    return c[5:] if c.startswith("WHEEL") else c


def code_hash(code: str) -> str:
    return hashlib.sha256(("wheel-code:" + norm_code(code)).encode()).hexdigest()


def new_code() -> str:
    body = "".join(secrets.choice(CODE_ALPHABET) for _ in range(12))
    return f"WHEEL-{body[:4]}-{body[4:8]}-{body[8:]}"


def make_codes(db, months: int, n: int, note: str = "") -> list[str]:
    if months not in MONTHS or not 1 <= n <= 200:
        raise ValueError("months is 1, 6 or 12; up to 200 codes at once")
    out = []
    for _ in range(n):
        c = new_code()
        db.execute("INSERT INTO codes(hash, months, made_day, note) VALUES(?,?,?,?)",
                   (code_hash(c), months, date.today().isoformat(), note[:20]))
        out.append(c)
    db.commit()
    return out


def until(db, account: str):
    r = db.execute("SELECT supporter_until FROM accounts WHERE account=?", (account,)).fetchone()
    return r["supporter_until"] if r and r["supporter_until"] else None


def active(db, account: str) -> bool:
    u = until(db, account)
    return bool(u) and u >= date.today().isoformat()


def count(db) -> int:
    return db.execute("SELECT COUNT(*) FROM accounts WHERE supporter_until >= ?", (date.today().isoformat(),)).fetchone()[0]


def add_months(start: date, months: int) -> date:
    m = start.month - 1 + months
    y, m = start.year + m // 12, m % 12 + 1
    last = (date(y + m // 12, m % 12 + 1, 1) - timedelta(days=1)).day
    return date(y, m, min(start.day, last))


def redeem(db, account: str, code: str):
    """-> the new last day of supporter months, or None for a code that is unknown or used."""
    h = code_hash(code)
    row = db.execute("SELECT months, used_day FROM codes WHERE hash=?", (h,)).fetchone()
    if not row or row["used_day"]:
        return None
    today = date.today()
    cur = until(db, account)
    start = max(today, date.fromisoformat(cur) + timedelta(days=1)) if cur else today
    new = add_months(start, row["months"]) - timedelta(days=1)
    db.execute("UPDATE codes SET used_day=? WHERE hash=?", (today.isoformat(), h))
    db.execute("UPDATE accounts SET supporter_until=? WHERE account=?", (new.isoformat(), account))
    db.commit()
    return new.isoformat()


# ---------- profiles ----------
def _clean_text(v, limit: int) -> str:
    t = re.sub(r"\s+", " ", str(v or "")).strip()[:limit]
    phone = any(len(re.sub(r"\D", "", m.group(0))) >= 7 for m in re.finditer(chats.PHONE, t))
    link = re.search(r"https?://|www\.|\b[\w-]+\.(com|nz|net|org|io|me|app|gg|link)\b", t, re.I)
    if t and (phone or link or re.search(chats.EMAIL, t) or re.search(r"(?<![\w.@])@[\w.+-]{2,}", t)):
        raise ValueError(NO_LINKS)
    return t


def clean_profile(data: dict) -> dict:
    """A profile as saved: every field a value and an audience. Locked looks are kept as chosen and shown only while
    supporter months run (choices come back with the next code)."""
    data = data if isinstance(data, dict) else {}
    out = {}
    for k, limit in TEXT.items():
        f = data.get(k) or {}
        v = _clean_text(f.get("v"), limit)
        if v:
            out[k] = {"v": v, "a": f.get("a") if f.get("a") in AUDIENCES else "me"}
    f = data.get("kinds") or {}
    kinds = [re.sub(r"\s+", " ", str(x)).strip().lower()[:30] for x in (f.get("v") or []) if str(x).strip()][:5]
    kinds = [_clean_text(x, 30) for x in dict.fromkeys(kinds)]
    if kinds:
        out["kinds"] = {"v": kinds, "a": f.get("a") if f.get("a") in AUDIENCES else "me"}
    f = data.get("status") or {}
    if f.get("v") in SIGNS:
        out["status"] = {"v": f["v"], "a": f.get("a") if f.get("a") in AUDIENCES else "me"}
    f = data.get("mark") or {}
    if f.get("v"):
        out["mark"] = {"v": True, "a": f.get("a") if f.get("a") in AUDIENCES else "me"}
    look = data.get("look") or {}
    out["look"] = {"colour": look.get("colour") if look.get("colour") in COLOURS else "ink",
                   "glyph": look.get("glyph") if look.get("glyph") in GLYPHS else "ring"}
    return out


def get_profile(db, account: str) -> dict:
    r = db.execute("SELECT data FROM profiles WHERE account=?", (account,)).fetchone()
    return json.loads(r["data"]) if r else {"look": {"colour": "ink", "glyph": "ring"}}


def save_profile(db, account: str, data: dict) -> dict:
    p = clean_profile(data)
    db.execute("INSERT INTO profiles(account, data) VALUES(?,?) ON CONFLICT(account) DO UPDATE SET data=excluded.data",
               (account, json.dumps(p, ensure_ascii=False)))
    db.commit()
    return p


def shown(p: dict, viewer: str, supporter: bool, floor_ok: bool) -> dict:
    """What a viewer at one level sees: "all" (anyone), "mem" (a signed-in member), "me" (the owner)."""
    out = {}
    for k, f in p.items():
        if k == "look" or RANK[f.get("a", "me")] > RANK[viewer]:
            continue
        if k in ("status", "mark") and not supporter:
            continue  # supporter looks go quiet when the months run out; the choice stays saved
        if k == "mark" and viewer != "me" and not floor_ok:
            continue  # the mark shows to others only once enough members hold one
        out[k] = f["v"]
    look = p.get("look") or {}
    colour, glyph = look.get("colour", "ink"), look.get("glyph", "ring")
    out["look"] = {"colour": colour if supporter or not COLOURS.get(colour, ("", True))[1] else "ink",
                   "glyph": glyph if supporter or not GLYPHS.get(glyph, True) else "ring"}
    return out


CATEGORICAL = ("area", "kinds", "status", "mark")


def _covers(theirs: dict, mine: dict) -> bool:
    for k in CATEGORICAL:
        if k not in mine:
            continue
        if k == "kinds":
            if not set(mine[k]) <= set(theirs.get(k) or []):
                return False
        elif theirs.get(k) != mine[k]:
            return False
    lm, lt = mine.get("look") or {}, theirs.get("look") or {}
    return all(lm.get(x) in (None, "ink", "ring") or lm.get(x) == lt.get(x) for x in ("colour", "glyph"))


def band(n: int) -> str:
    return "20 or more" if n >= 20 else "5 to 19" if n >= 5 else "1 to 4"


def lookalike(db, account: str) -> dict:
    """For each audience, how many members (the owner included) show at least what this member shows: a band, never
    a number, so the count says little about anyone else. Names and the few lines are left out: they are pen-name
    level, and their note covers them."""
    sup = {r["account"] for r in db.execute("SELECT account FROM accounts WHERE supporter_until >= ?", (date.today().isoformat(),))}
    floor_ok = len(sup) >= FLOOR
    profiles = {r["account"]: json.loads(r["data"]) for r in db.execute("SELECT account, data FROM profiles")}
    everyone = [r["account"] for r in db.execute("SELECT account FROM accounts")]
    mine_p = profiles.get(account) or {}
    out = {}
    for viewer in ("all", "mem"):
        mine = shown(mine_p, viewer, account in sup, floor_ok)
        n = sum(1 for a in everyone if _covers(shown(profiles.get(a) or {}, viewer, a in sup, floor_ok), mine))
        out[viewer] = band(max(n, 1))
    return out


# ---------- Monero: one subaddress, a unique amount per order ----------
_rate = {"at": 0.0, "nzd": None}


def xmr_nzd(fetch=None) -> float | None:
    """NZ dollars for one XMR, from CoinGecko, cached ten minutes. The server asks; nothing about members goes with it."""
    if os.environ.get("WHEEL_XMR_NZD"):  # tests: a fixed price, no network
        return float(os.environ["WHEEL_XMR_NZD"])
    if time.time() - _rate["at"] < 600 and _rate["nzd"]:
        return _rate["nzd"]
    try:
        if fetch:
            v = fetch()
        else:
            req = urllib.request.Request("https://api.coingecko.com/api/v3/simple/price?ids=monero&vs_currencies=nzd",
                                         headers={"User-Agent": "TheWheel/0.1"})
            with urllib.request.urlopen(req, timeout=10) as r:
                v = json.load(r)["monero"]["nzd"]
        v = float(v)
        if v > 0:
            _rate.update(at=time.time(), nzd=v)
    except Exception:
        pass
    return _rate["nzd"]


def _sweep(db):
    now = time.time()
    db.execute("DELETE FROM orders WHERE state IN ('waiting','seen') AND created < ?", (now - ORDER_KEEP_S,))
    db.execute("DELETE FROM orders WHERE state='paid' AND created < ?", (now - PAID_KEEP_S,))
    db.commit()


def open_order(db, months: int, nzd_month: float, rate: float) -> dict:
    """-> the token (kept by the browser), the address and the exact amount to send."""
    if months not in MONTHS:
        raise ValueError("Pick 1, 6 or 12 months.")
    if not isinstance(nzd_month, (int, float)) or not MIN_NZD <= nzd_month <= 1000:
        raise ValueError(f"From NZ${MIN_NZD} a month.")
    _sweep(db)
    nzd = round(months * float(nzd_month), 2)
    base = math.ceil(nzd / rate * ATOMIC / 10 ** 6) * 10 ** 6  # to the micro-XMR
    taken = {r["atomic"] for r in db.execute("SELECT atomic FROM orders")}
    for _ in range(50):
        atomic = base + secrets.randbelow(999_999) + 1  # the last six digits tell this order apart
        if atomic not in taken:
            break
    token = secrets.token_urlsafe(24)
    db.execute("INSERT INTO orders(id, months, atomic, nzd, created, state, conf) VALUES(?,?,?,?,?,?,0)",
               (hashlib.sha256(token.encode()).hexdigest(), months, atomic, nzd, int(time.time()), "waiting"))
    db.commit()
    return {"token": token, "address": XMR_ADDRESS, "amount": xmr_text(atomic), "nzd": nzd, "months": months,
            "pay_by": int(time.time()) + ORDER_PAY_S, "confirmations": CONFIRMATIONS}


def xmr_text(atomic: int) -> str:
    return f"{atomic // ATOMIC}.{atomic % ATOMIC:012d}"


def order_status(db, token: str) -> dict | None:
    """The browser asks after its order. A paid order hands over its code once; then the order is gone."""
    oid = hashlib.sha256(str(token or "").encode()).hexdigest()
    r = db.execute("SELECT * FROM orders WHERE id=?", (oid,)).fetchone()
    if not r:
        return None
    out = {"state": r["state"], "confirmations": r["conf"], "need": CONFIRMATIONS, "months": r["months"],
           "amount": xmr_text(r["atomic"]), "address": XMR_ADDRESS}
    if r["state"] == "paid":
        out["code"] = r["code"]
        db.execute("DELETE FROM orders WHERE id=?", (oid,))
        db.commit()
    return out


def watch_list(db) -> list[dict]:
    """For the payment watcher: open orders by id and amount, with the time to look back from."""
    _sweep(db)
    return [{"id": r["id"], "atomic": r["atomic"], "since": r["created"]}
            for r in db.execute("SELECT id, atomic, created FROM orders WHERE state IN ('waiting','seen')")]


def watch_report(db, oid: str, confirmations: int) -> str | None:
    r = db.execute("SELECT state, months FROM orders WHERE id=?", (str(oid),)).fetchone()
    if not r or r["state"] == "paid":
        return r["state"] if r else None
    conf = max(0, int(confirmations))
    if conf >= CONFIRMATIONS:
        code = make_codes(db, r["months"], 1, "monero")[0]
        db.execute("UPDATE orders SET state='paid', conf=?, code=? WHERE id=?", (conf, code, oid))
    else:
        db.execute("UPDATE orders SET state='seen', conf=? WHERE id=?", (conf, oid))
    db.commit()
    return "paid" if conf >= CONFIRMATIONS else "seen"
