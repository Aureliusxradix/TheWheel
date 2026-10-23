"""Recovery's own (his calls 2026-10-24, round two): places that stay and practitioners you can contact.

His rulings, verbatim: "practitioners are given an 'advertising code for heath claims' link when
setting up their profile. ZKP first, everyone in every type of account has the ability to withhold informational
points. Practitioners show contact information with platforms like signal suggested to maintain anon/privacy.
community review method for saunas/organisers can claim them."

Places (saunas, hot pools, float tanks, cold plunges) come in from members and are checked by reviews weighted like a
listing's; an organiser can claim one the way it claims a listing. A practitioner is an organiser account with a
practice: each field carries its own audience (everyone, members, or held back), so every point can be withheld.
Vouches are member proofs kept by the member service, one per member per practitioner; this file never sees them.
"""
import re

PLACE_KINDS = {"sauna": "Sauna", "hotpools": "Hot pools", "float": "Float tank", "coldplunge": "Cold plunge",
               "bathhouse": "Bathhouse", "other": "Another kind of place"}
DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
HOURS = re.compile(r"[0-2]\d:[0-5]\d-[0-2]\d:[0-5]\d")
AUDIENCES = ("all", "mem", "off")  # everyone · members · held back
PRACTICE_FIELDS = ("modalities", "area", "about", "price", "registration", "page", "signal", "email", "phone", "booking")
DEFAULT_AUDIENCE = {"signal": "mem", "email": "mem", "phone": "mem"}  # contact goes to members unless the practitioner opens it
ASA_CODE = "https://www.asa.co.nz/codes/codes/therapeutic-and-health-advertising-code/"


def _line(x, n: int) -> str:
    return re.sub(r"\s+", " ", str(x or "")).strip()[:n]


def _link(v, what: str) -> str | None:
    v = _line(v, 300) or None
    if v and not re.fullmatch(r"https?://[^\s<>\"']+", v):
        raise ValueError(f"The {what} needs a web address starting https://")
    return v


def clean_hours(v) -> dict:
    """Opening hours a day at a time: "07:00-21:00", or two ranges "07:00-12:00, 16:00-21:00"; empty is closed."""
    out = {}
    for d in DAYS:
        raw = _line((v or {}).get(d) if isinstance(v, dict) else "", 40).replace("–", "-").replace(" ", "")
        if not raw:
            continue
        parts = [p for p in raw.split(",") if p]
        if not all(HOURS.fullmatch(p) for p in parts):
            raise ValueError(f"Hours look like 07:00-21:00 ({d.title()}), or two ranges with a comma between.")
        out[d] = ", ".join(parts)
    return out


def clean_place(b: dict, care_keys) -> dict:
    rec = {"name": _line(b.get("name"), 80), "kind": b.get("kind") if b.get("kind") in PLACE_KINDS else "other",
           "locality": _line(b.get("locality"), 80), "address": _line(b.get("address"), 160),
           "link": _link(b.get("link"), "page"), "booking": _link(b.get("booking"), "booking link"),
           "price": _line(b.get("price"), 120) or None, "temp": _line(b.get("temp"), 80) or None,
           "about": str(b.get("about") or "").strip()[:600] or None, "hours": clean_hours(b.get("hours")),
           "sessions": [{"when": _line(s.get("when"), 80), "what": _line(s.get("what"), 80)}
                        for s in (b.get("sessions") or [])[:12] if isinstance(s, dict) and _line(s.get("what"), 80)],
           "care": [c for c in care_keys if c in (b.get("care") or [])]}
    if len(rec["name"]) < 2:
        raise ValueError("Give the place its name.")
    if not rec["locality"]:
        raise ValueError("Say where it is: the town or suburb.")
    return rec


def place_public(p: dict) -> dict:
    return {k: p.get(k) for k in ("id", "name", "kind", "locality", "address", "link", "booking", "price", "temp",
                                  "about", "hours", "sessions", "care")}


def clean_practice(b: dict) -> dict:
    """A practitioner's profile: each field a value and an audience. Contact details are allowed here (his ruling)."""
    out = {"listed": bool(b.get("listed"))}
    for k in PRACTICE_FIELDS:
        f = b.get(k) if isinstance(b.get(k), dict) else {"v": b.get(k)}
        a = f.get("a") if f.get("a") in AUDIENCES else DEFAULT_AUDIENCE.get(k, "all")
        if k == "modalities":
            v = [_line(m, 40) for m in (f.get("v") if isinstance(f.get("v"), list) else str(f.get("v") or "").split(","))[:8] if _line(m, 40)]
        elif k == "about":
            v = str(f.get("v") or "").strip()[:800]
        elif k in ("page", "booking"):
            v = _link(f.get("v"), "booking link" if k == "booking" else "page")
        elif k == "signal":
            v = _line(f.get("v"), 80)
            if v and not (re.fullmatch(r"https://signal\.me/[^\s<>\"']+", v) or re.fullmatch(r"@?[A-Za-z0-9_.]{3,40}", v)):
                raise ValueError("Signal: your username (like quietwater.01) or your signal.me link.")
        elif k == "email":
            v = _line(f.get("v"), 120)
            if v and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", v):
                raise ValueError("That email address looks wrong.")
        elif k == "phone":
            v = _line(f.get("v"), 30)
            if v and not re.fullmatch(r"\+?[0-9 ()-]{6,30}", v):
                raise ValueError("A phone number in digits, like 021 555 1234.")
        else:
            v = _line(f.get("v"), 160)
        if v:
            out[k] = {"v": v, "a": a}
    return out


def practice_shown(practice: dict, member: bool) -> dict:
    """What a viewer sees: everyone's fields to all, members' fields to signed-in members, held-back fields to nobody."""
    return {k: f["v"] for k, f in practice.items() if isinstance(f, dict) and (f["a"] == "all" or (f["a"] == "mem" and member))}
