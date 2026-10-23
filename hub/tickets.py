"""Monero tickets, paid straight to the organiser (his calls 2026-10-24).

Under the Radar ended its ticketing on 2026-10-23. His route: court the promoters it left, and offer them Monero ticket
sales. His call on custody: the buyer pays the organiser's own address. The Wheel never holds the money or anyone's
view key. The buyer's wallet hands them a proof of payment (the transaction id and its transaction key), and the
watcher beside the Monero node checks it with check_tx_key, which confirms an amount to any address from those two.

A ticket shows at the door once the payment is seen; the door screen says how many of its 10 confirmations it has,
and the organiser decides whether to wait.

What this file refuses to hold:
  - a ticket code in plain text (codes come from the buyer's own token; the store keeps fingerprints)
  - the transaction id or key once a sale settles (kept only while the watcher checks; after that a hash of the id,
    so one payment buys once)
  - who bought (no account, no address of the payer)
"""
import hashlib
import math
import re
import secrets
import time
from datetime import date

CONFIRMATIONS = 10
QUOTE_S = 3600  # the XMR amount holds an hour
MAX_QTY = 10
MAX_TRIES = 8  # failed checks (about 16 minutes of watcher runs) before a proof counts as wrong
ATOMIC = 10 ** 12
ADDRESS = re.compile(r"[48][1-9A-HJ-NP-Za-km-z]{94}")  # a standard address or a subaddress
TXID = re.compile(r"[0-9a-f]{64}")
LETTERS = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no I, O, 0 or 1 to misread at a door


def _id(token: str) -> str:
    return hashlib.sha256(str(token or "").encode()).hexdigest()


def _fp(listing_id: str, code: str) -> str:
    return hashlib.sha256(f"{listing_id}:{normal(code)}".encode()).hexdigest()


def normal(code: str) -> str:
    return re.sub(r"[^A-Z2-9]", "", str(code or "").upper())


def codes_for(token: str, qty: int) -> list[str]:
    """The order's ticket codes, worked out from the buyer's token: the same token gives the same codes every time."""
    out = []
    for i in range(qty):
        n = int.from_bytes(hashlib.sha256(f"ticket:{token}:{i}".encode()).digest()[:5], "big")
        s = "".join(LETTERS[(n >> (5 * k)) & 31] for k in range(8))
        out.append(f"{s[:4]}-{s[4:]}")
    return out


def xmr_text(atomic: int) -> str:
    return f"{atomic // ATOMIC}.{atomic % ATOMIC:012d}"


# ---------- the organiser's side ----------
def set_sale(db, listing_id: str, organiser_id: str, address: str, nzd, cap, open_: bool) -> dict:
    address = str(address or "").strip()
    if not ADDRESS.fullmatch(address):
        raise ValueError("That Monero address looks wrong: 95 characters, starting with 4 or 8. Copy it from your wallet.")
    if not isinstance(nzd, (int, float)) or not 1 <= nzd <= 2000:
        raise ValueError("A ticket price from NZ$1 to NZ$2000.")
    if not isinstance(cap, int) or not 1 <= cap <= 5000:
        raise ValueError("How many tickets: from 1 to 5000.")
    sold = counts(db, listing_id)["sold"]
    if cap < sold:
        raise ValueError(f"{sold} tickets are already sold; set at least that many.")
    db.execute("INSERT INTO ticket_sales VALUES(?,?,?,?,?,?,?) ON CONFLICT(listing_id) DO UPDATE SET organiser_id=excluded.organiser_id, "
               "address=excluded.address, nzd=excluded.nzd, cap=excluded.cap, open=excluded.open, day=excluded.day",
               (listing_id, organiser_id, address, round(float(nzd), 2), cap, 1 if open_ else 0, date.today().isoformat()))
    db.commit()
    return sale_for_org(db, listing_id)


def sale(db, listing_id: str):
    return db.execute("SELECT * FROM ticket_sales WHERE listing_id=?", (listing_id,)).fetchone()


def counts(db, listing_id: str) -> dict:
    _sweep(db)
    sold = db.execute("SELECT COUNT(*) n FROM tickets WHERE listing_id=? AND conf >= 0", (listing_id,)).fetchone()["n"]
    used = db.execute("SELECT COUNT(*) n FROM tickets WHERE listing_id=? AND used_at IS NOT NULL", (listing_id,)).fetchone()["n"]
    held = db.execute("SELECT COALESCE(SUM(qty),0) n FROM ticket_orders WHERE listing_id=? AND "
                      "(state='checking' OR (state='quoted' AND pay_by >= ?))", (listing_id, int(time.time()))).fetchone()["n"]
    return {"sold": sold, "used": used, "held": held}


def sale_for_org(db, listing_id: str) -> dict | None:
    s = sale(db, listing_id)
    if not s:
        return None
    return {"address": s["address"], "nzd": s["nzd"], "cap": s["cap"], "open": bool(s["open"]), **counts(db, listing_id)}


def sale_public(db, listing_id: str, holder_id: str | None) -> dict | None:
    """What a card shows: the price and how many are left. Only while the organiser holding the listing runs the sale."""
    s = sale(db, listing_id)
    if not s or not s["open"] or s["organiser_id"] != holder_id:
        return None
    c = counts(db, listing_id)
    return {"nzd": s["nzd"], "left": max(0, s["cap"] - c["sold"] - c["held"])}


def door(db, listing_id: str, code: str) -> dict:
    """The organiser checks a code at the door. A good code is marked used the first time."""
    r = db.execute("SELECT * FROM tickets WHERE fp=?", (_fp(listing_id, code),)).fetchone()
    if not r or r["conf"] < 0:  # a ticket counts once its payment is seen
        return {"state": "unknown"}
    if r["used_at"]:
        return {"state": "used", "at": r["used_at"]}
    db.execute("UPDATE tickets SET used_at=? WHERE fp=?", (int(time.time()), r["fp"]))
    db.commit()
    return {"state": "valid" if r["conf"] >= CONFIRMATIONS else "confirming", "confirmations": r["conf"], "need": CONFIRMATIONS}


# ---------- the buyer's side ----------
def _sweep(db):
    now = int(time.time())
    db.execute("DELETE FROM ticket_orders WHERE state='quoted' AND pay_by < ?", (now - 86400,))
    db.execute("DELETE FROM ticket_orders WHERE state IN ('bad','short') AND created < ?", (now - 7 * 86400,))
    db.execute("DELETE FROM ticket_orders WHERE state='paid' AND created < ?", (now - 120 * 86400,))
    db.commit()


def quote(db, listing_id: str, qty, rate: float, holder_id: str | None) -> dict:
    s = sale(db, listing_id)
    if not s or not s["open"] or s["organiser_id"] != holder_id:
        raise LookupError("This listing sells no Monero tickets right now.")
    if not isinstance(qty, int) or not 1 <= qty <= MAX_QTY:
        raise ValueError(f"From 1 to {MAX_QTY} tickets at a time.")
    left = sale_public(db, listing_id, holder_id)["left"]
    if qty > left:
        raise ValueError(f"{left} left." if left else "Sold out.")
    nzd = round(qty * s["nzd"], 2)
    atomic = math.ceil(nzd / rate * ATOMIC / 10 ** 6) * 10 ** 6  # to the micro-XMR
    token = secrets.token_urlsafe(24)
    now = int(time.time())
    db.execute("INSERT INTO ticket_orders(id, listing_id, qty, atomic, address, nzd, created, pay_by, state) VALUES(?,?,?,?,?,?,?,?,?)",
               (_id(token), listing_id, qty, atomic, s["address"], nzd, now, now + QUOTE_S, "quoted"))
    db.commit()
    return {"token": token, "address": s["address"], "amount": xmr_text(atomic), "nzd": nzd, "qty": qty,
            "pay_by": now + QUOTE_S, "confirmations": CONFIRMATIONS}


def prove(db, token: str, txid: str, txkey: str) -> dict:
    r = db.execute("SELECT * FROM ticket_orders WHERE id=?", (_id(token),)).fetchone()
    if not r:
        raise LookupError("That order has ended. Start again from the listing.")
    if r["state"] not in ("quoted", "bad"):
        return status(db, token)
    txid, txkey = str(txid or "").strip().lower(), str(txkey or "").strip().lower()
    if not TXID.fullmatch(txid):
        raise ValueError("The transaction ID is 64 letters and numbers (0-9, a-f). Copy it from your wallet's transaction details.")
    if not re.fullmatch(r"[0-9a-f]{64}([0-9a-f]{64})*", txkey):
        raise ValueError("The transaction key is 64 letters and numbers (0-9, a-f), sometimes longer. Your wallet shows it beside the ID.")
    txh = hashlib.sha256(txid.encode()).hexdigest()
    other = db.execute("SELECT id FROM ticket_orders WHERE txh=? AND id<>?", (txh, r["id"])).fetchone()
    if other:
        raise ValueError("That payment has already bought tickets.")
    db.execute("UPDATE ticket_orders SET state='checking', txh=?, txid=?, txkey=?, tries=0, note=NULL WHERE id=?",
               (txh, txid, txkey, r["id"]))
    # the fingerprints are made now, while the token is here; they count only once the watcher sees the payment (conf -1)
    db.executemany("INSERT OR IGNORE INTO tickets(fp, listing_id, order_id, conf) VALUES(?,?,?,-1)",
                   [(_fp(r["listing_id"], c), r["listing_id"], r["id"]) for c in codes_for(token, r["qty"])])
    db.commit()
    return status(db, token)


def status(db, token: str) -> dict | None:
    r = db.execute("SELECT * FROM ticket_orders WHERE id=?", (_id(token),)).fetchone()
    if not r:
        return None
    out = {"state": r["state"], "listing": r["listing_id"], "qty": r["qty"], "amount": xmr_text(r["atomic"]),
           "address": r["address"], "nzd": r["nzd"], "pay_by": r["pay_by"], "confirmations": r["conf"], "need": CONFIRMATIONS}
    if r["state"] in ("issued", "paid"):
        out["codes"] = codes_for(token, r["qty"])
    if r["state"] == "short":
        out["received"] = xmr_text(r["received"])
    if r["note"]:
        out["note"] = r["note"]
    return out


# ---------- the watcher beside the node ----------
def watch_list(db) -> list[dict]:
    _sweep(db)
    return [{"id": r["id"], "txid": r["txid"], "txkey": r["txkey"], "address": r["address"]}
            for r in db.execute("SELECT * FROM ticket_orders WHERE state IN ('checking','issued')")]


def watch_report(db, oid: str, received=None, confirmations=0, in_pool=False, error=None) -> str | None:
    """One check_tx_key answer. The payment issues the tickets when it covers the amount; the confirmations then climb."""
    r = db.execute("SELECT * FROM ticket_orders WHERE id=?", (str(oid),)).fetchone()
    if not r or r["state"] not in ("checking", "issued"):
        return r["state"] if r else None
    if error is not None:
        if r["state"] == "checking":
            tries = r["tries"] + 1
            bad = tries >= MAX_TRIES
            if bad:
                db.execute("DELETE FROM tickets WHERE order_id=?", (r["id"],))
                db.execute("UPDATE ticket_orders SET txh=NULL, txid=NULL, txkey=NULL WHERE id=?", (r["id"],))
            db.execute("UPDATE ticket_orders SET tries=?, state=?, note=? WHERE id=?",
                       (tries, "bad" if bad else "checking",
                        "The payment failed to check against this organiser's address. Check the ID and key, and that you paid the address shown." if bad else None,
                        r["id"]))
            db.commit()
            return "bad" if bad else "checking"
        return r["state"]
    got, conf = max(0, int(received or 0)), max(0, int(confirmations or 0))
    if r["state"] == "checking":
        if got < r["atomic"]:
            db.execute("DELETE FROM tickets WHERE order_id=?", (r["id"],))
        if got == 0:
            db.execute("UPDATE ticket_orders SET state='bad', txh=NULL, txid=NULL, txkey=NULL, note=? WHERE id=?",
                       ("That transaction pays nothing to this organiser's address.", r["id"]))
            db.commit()
            return "bad"
        if got < r["atomic"]:
            db.execute("UPDATE ticket_orders SET state='short', received=?, txid=NULL, txkey=NULL, note=? WHERE id=?",
                       (got, "The payment arrived short of the amount. The organiser holds it; ask them.", r["id"]))
            db.commit()
            return "short"
        db.execute("UPDATE ticket_orders SET state='issued', received=? WHERE id=?", (got, r["id"]))
    state = "paid" if conf >= CONFIRMATIONS else "issued"
    db.execute("UPDATE ticket_orders SET conf=?, state=? WHERE id=?", (conf, state, r["id"]))
    db.execute("UPDATE tickets SET conf=? WHERE order_id=?", (conf, r["id"]))
    if state == "paid":
        db.execute("UPDATE ticket_orders SET txid=NULL, txkey=NULL WHERE id=?", (r["id"],))
    db.commit()
    return state
