"""Organiser accounts (his ruling 2026-10-23: "A, and yes to organiser accounts").

An organiser account is its own key with a public name, kept apart from any member's pen name: the browser sends it
only with organiser actions, and the store never links the two. It proves itself by a code on its own page (his
option 1, picked for anon pathways), or a steward vouches where a page cannot be read (Facebook and Instagram block
outside readers). A proven organiser claims the listings that link to its page, keeps their details right, posts
updates, and opens check-ins whose door code changes every minute.
"""
import hashlib
import re
import secrets
from datetime import date
from urllib.parse import urlsplit

# hosts many organisers share: a match there needs the organiser's own path, never the host alone
SHARED = ("facebook.com", "fb.com", "fb.me", "instagram.com", "eventbrite.", "humanitix.com", "meetup.com", "linktr.ee",
          "x.com", "twitter.com", "tiktok.com", "youtube.com", "google.com", "forms.gle", "allevents.in", "eventfinda.",
          "trybooking.com", "ticketfairy.com", "patreon.com", "substack.com", "bandcamp.com", "eventbrite.co.nz",
          "lu.ma", "partiful.com", "squarespace.com", "wixsite.com", "github.io", "wordpress.com", "blogspot.com")
NAME_LIMIT = 60
CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"


def key_hash(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


def norm(url: str) -> str:
    """host/path, lower-case host, no scheme, no www., no query, no trailing slash."""
    u = urlsplit(url.strip() if "://" in url else "https://" + url.strip())
    host = (u.hostname or "").lower().removeprefix("www.").removeprefix("m.")
    return (host + u.path).rstrip("/")


def shared(host: str) -> bool:
    return any(host == s or host.endswith("." + s) or (s.endswith(".") and s in host) for s in SHARED)


def links_to(page: str, url: str) -> bool:
    """Whether a listing's link sits under the organiser's page: its path, or its whole site when the site is its own."""
    p, u = norm(page), norm(url or "")
    if not p or not u:
        return False
    if u == p or u.startswith(p + "/"):
        return True
    host = p.split("/")[0]
    return u.split("/")[0] == host and not shared(host)


def clean_name(name) -> str:
    n = re.sub(r"\s+", " ", str(name or "")).strip()
    if not 2 <= len(n) <= NAME_LIMIT:
        raise ValueError(f"An organiser's name is 2 to {NAME_LIMIT} letters.")
    if re.search(r"https?://|www\.|@|\d{6,}", n):
        raise ValueError("The name is a name only: links, @names and numbers go elsewhere.")
    return n


def clean_page(page) -> str:
    p = str(page or "").strip()
    if not re.fullmatch(r"https://[^\s<>\"']+", p):
        raise ValueError("Your page is a web address starting https:// : your site, or your page on Facebook or Instagram.")
    return p


def new(db, name, page) -> dict:
    """A new organiser account: its id, its key (shown once, kept as a fingerprint) and the code for its page."""
    oid, key = secrets.token_hex(8), secrets.token_urlsafe(32)
    code = "WHEEL-" + "".join(secrets.choice(CODE_ALPHABET) for _ in range(6))
    db.execute("INSERT INTO organisers(id, name, key_hash, page, code, made_day) VALUES(?,?,?,?,?,?)",
               (oid, clean_name(name), key_hash(key), clean_page(page), code, date.today().isoformat()))
    db.commit()
    return {"id": oid, "key": key, "code": code}


def by_key(db, key: str | None) -> dict | None:
    if not key or len(key) > 100:
        return None
    r = db.execute("SELECT * FROM organisers WHERE key_hash=?", (key_hash(key),)).fetchone()
    return dict(r) if r else None


def get(db, oid: str) -> dict | None:
    r = db.execute("SELECT * FROM organisers WHERE id=?", (oid,)).fetchone()
    return dict(r) if r else None


def public(o: dict) -> dict:
    return {"id": o["id"], "name": o["name"], "page": o["page"], "proven": bool(o["verified_day"]),
            "proven_by": o["verified_by"]}


def prove(db, oid: str, by: str):
    db.execute("UPDATE organisers SET verified_day=?, verified_by=? WHERE id=?", (date.today().isoformat(), by, oid))
    db.commit()


def page_shows(body: bytes, code: str) -> bool:
    return code.encode() in body or code in body.decode("utf-8", errors="replace").upper()


def ask_vouch(db, oid: str):
    db.execute("UPDATE organisers SET vouch_asked=? WHERE id=?", (date.today().isoformat(), oid))
    db.commit()


def waiting_vouch(db) -> list[dict]:
    return [dict(r) for r in db.execute("SELECT * FROM organisers WHERE vouch_asked IS NOT NULL AND verified_day IS NULL ORDER BY vouch_asked")]


def claim_of(db, listing_id: str) -> dict | None:
    r = db.execute("SELECT * FROM claims WHERE listing_id=?", (listing_id,)).fetchone()
    return dict(r) if r else None


def claim(db, o: dict, rec: dict) -> str:
    """'claimed' when the listing links under the organiser's page; 'waiting' for a steward otherwise."""
    if not o["verified_day"]:
        raise PermissionError("Prove your page first: put your code on it, or ask a steward.")
    held = claim_of(db, rec["id"])
    if held and held["organiser_id"] != o["id"]:
        raise PermissionError("Another organiser has claimed this listing. Ask a steward if it is yours.")
    links = [rec.get("website"), rec.get("tickets_url"), (rec.get("source") or {}).get("url")]
    state = "claimed" if any(links_to(o["page"], u) for u in links if u) else "waiting"
    db.execute("INSERT INTO claims(listing_id, organiser_id, state, day) VALUES(?,?,?,?) ON CONFLICT(listing_id) DO UPDATE "
               "SET organiser_id=excluded.organiser_id, state=excluded.state, day=excluded.day",
               (rec["id"], o["id"], state, date.today().isoformat()))
    db.commit()
    return state


def answer_claim(db, listing_id: str, grant: bool) -> dict | None:
    c = claim_of(db, listing_id)
    if c is None or c["state"] != "waiting":
        return None
    if grant:
        db.execute("UPDATE claims SET state='claimed' WHERE listing_id=?", (listing_id,))
    else:
        db.execute("DELETE FROM claims WHERE listing_id=?", (listing_id,))
    db.commit()
    return c


def claims_waiting(db) -> list[dict]:
    return [dict(r) for r in db.execute("SELECT * FROM claims WHERE state='waiting' ORDER BY day")]


def claims_for(db, oid: str) -> list[dict]:
    return [dict(r) for r in db.execute("SELECT * FROM claims WHERE organiser_id=? ORDER BY day DESC", (oid,))]


def holds(db, o: dict, listing_id: str) -> bool:
    c = claim_of(db, listing_id)
    return bool(o and o["verified_day"] and c and c["organiser_id"] == o["id"] and c["state"] == "claimed")
