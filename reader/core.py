"""One deposit -> hub records (schema/event.schema.json), each waiting for review.

Order of reading, cheapest first: a calendar feed, then a page's schema.org
data, then the AI step for everything else (plain text, a page without
structured data, a flyer image).
"""

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

from . import ics, jsonld, llm, netguard

netguard.install()  # a pasted link reaches the public internet only

HUB_TZ = ZoneInfo("Pacific/Auckland")
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
PAGE_TEXT_LIMIT = 60000
UA = "TheWheel/0.1 (community events hub; +https://aureliusxradix.com/thewheel/)"
FETCH_LIMIT = 8_000_000
SCHEMA = json.loads((Path(__file__).resolve().parent.parent / "schema" / "event.schema.json").read_text())


class Deposit:
    """What a person dropped in: text, a file path, or a URL."""

    def __init__(self, raw: str, received: datetime, by: str | None = None, allow_path: bool = True):
        self.raw, self.received, self.by, self.allow_path = raw, received, by, allow_path
        self.notes: list[str] = []
        self.cost_usd = 0.0

    @property
    def is_url(self) -> bool:
        return self.raw.strip().lower().startswith(("http://", "https://"))

    @property
    def path(self) -> Path | None:
        if not self.allow_path:  # the server: what a member pastes is text or a link, never a file on the box
            return None
        p = Path(self.raw.strip()).expanduser()
        return p if len(self.raw) < 4096 and "\n" not in self.raw and p.is_file() else None


def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


PREFETCHED: dict[str, tuple[bytes, str]] = {}  # filled by crawl.py, which fetches politely


def _fetch(url: str) -> tuple[bytes, str]:
    if url in PREFETCHED:
        return PREFETCHED[url]
    with requests.get(url, headers={"User-Agent": UA}, timeout=30, stream=True) as r:
        r.raise_for_status()
        body = b""
        for chunk in r.iter_content(65536):
            body += chunk
            if len(body) > FETCH_LIMIT:
                raise ValueError(f"That page is over {FETCH_LIMIT // 1_000_000} MB. Paste the event's text instead.")
        return body, r.headers.get("content-type", "")


def _read(dep: Deposit) -> tuple[list[dict], dict, dict]:
    """-> (candidate events, source block, extraction block)."""
    received_iso = dep.received.isoformat()
    if dep.is_url:
        body, ctype = _fetch(dep.raw.strip())
        source = {"kind": "web", "url": dep.raw.strip(), "fetched_at": received_iso, "raw_sha256": _sha(body)}
        text = body.decode("utf-8", errors="replace")
        if "calendar" in ctype or text.lstrip().startswith("BEGIN:VCALENDAR"):
            return ics.parse(text), {**source, "kind": "ics"}, {"method": "ics"}
        if "html" in ctype or "<html" in text[:2000].lower():
            found = jsonld.parse(text)
            if found and not jsonld.is_thin(found):
                return found, {**source, "kind": "jsonld"}, {"method": "jsonld"}
            if found:
                dep.notes.append("the page's own event data gave only names and times; the AI read the page")
            page = jsonld.page_text(text, PAGE_TEXT_LIMIT + 1)
            if len(page) > PAGE_TEXT_LIMIT:
                dep.notes.append(f"page text cut at {PAGE_TEXT_LIMIT} characters")
                page = page[:PAGE_TEXT_LIMIT]
            events, src, extraction = _ai(dep, f"Web page {dep.raw.strip()}\n\n{page}", None, source)
            if found and not events:  # the page itself says it is an event: never drop it on the AI's say-so
                dep.notes.append("the AI found no event, so the page's own thin record is kept for a reviewer")
                return found, {**source, "kind": "jsonld"}, {"method": "jsonld"}
            return events, src, extraction
        return _ai(dep, text, None, source)
    if dep.path is not None:
        p = dep.path
        body = p.read_bytes()
        source = {"kind": "manual", "url": None, "fetched_at": received_iso, "raw_sha256": _sha(body)}
        if p.suffix.lower() in IMAGE_EXT:
            return _ai(dep, None, p, {**source, "kind": "flyer"})
        text = body.decode("utf-8", errors="replace")
        if p.suffix.lower() == ".ics" or text.lstrip().startswith("BEGIN:VCALENDAR"):
            return ics.parse(text), {**source, "kind": "ics"}, {"method": "ics"}
        if p.suffix.lower() in (".html", ".htm"):
            found = jsonld.parse(text)
            if found:
                return found, {**source, "kind": "jsonld"}, {"method": "jsonld"}
            return _ai(dep, jsonld.page_text(text, PAGE_TEXT_LIMIT), None, {**source, "kind": "web"})
        return _ai(dep, text, None, {**source, "kind": "deposit"})
    source = {"kind": "deposit", "url": None, "fetched_at": received_iso, "raw_sha256": _sha(dep.raw.encode())}
    return _ai(dep, dep.raw, None, source)


def _ai(dep: Deposit, text: str | None, image: Path | None, source: dict):
    got = llm.extract(text, image, dep.received)
    dep.cost_usd += got.get("cost_usd") or 0
    out = got["output"]
    dep.visible_text = out.get("visible_text")  # a flyer's own words, for the identity gate before the flyer is shown
    if not out["is_event_post"] and out.get("rejected_reason"):
        dep.notes.append(f"not an event: {out['rejected_reason']}")
    extraction = {"method": "llm", "model": got["model"], "prompt_version": llm.PROMPT_VERSION,
                  "cost_usd": got.get("cost_usd")}
    events = []
    for e in out["events"]:
        e = dict(e)
        tags = e.pop("kind_tags", []) or []
        e["tags"] = [t.strip().lower() for t in tags if t.strip()]
        events.append(e)
    return events, source, extraction


def _record(ev: dict, source: dict, extraction: dict, dep: Deposit) -> dict:
    key = "|".join([source["kind"], ev.get("source_id") or source.get("url") or source["raw_sha256"],
                    ev["start_date"], ev.get("start_time") or "", ev.get("name", "")])
    src = {**source}
    if ev.get("source_id"):
        src["source_id"] = ev.pop("source_id")
    rec = {
        "id": _sha(key.encode())[:16],
        "timezone": "Pacific/Auckland",
        "status": "confirmed",
        "online": False,
        "tags": [],
        **{k: v for k, v in ev.items() if v not in (None, "")},
        "source": src,
        "extraction": {**extraction, **({"confidence_notes": "; ".join(dep.notes)} if dep.notes else {})},
        "review": {"state": "pending", "by": None, "at": None},
        "deposited_by": dep.by,
        "duplicate_of": None,
    }
    rec.setdefault("time_known", rec.get("start_time") is not None)
    rec.setdefault("listing_kind", "event")
    if not rec.get("modes"):  # feeds and page data carry no mode: a first guess by the clock, the reviewer corrects it
        multi = bool(rec.get("end_date")) and rec["end_date"] != rec["start_date"]
        evening = (rec.get("start_time") or "") >= "17:00"
        rec["modes"] = ["day", "night"] if multi else (["night"] if evening else ["day"])
        rec["extraction"]["modes_guessed"] = True
    for k in ("slots", "requirements"):
        if not rec.get(k):
            rec.pop(k, None)
    return rec


def check(rec: dict) -> list[str]:
    """Light check against the schema: required fields, enums, time patterns."""
    import re
    problems = [f"missing {f}" for f in SCHEMA["required"] if f not in rec]
    props = SCHEMA["properties"]
    if rec.get("status") not in props["status"]["enum"]:
        problems.append(f"bad status {rec.get('status')!r}")
    for f in ("start_time", "end_time"):
        if rec.get(f) and not re.fullmatch(props[f]["pattern"], rec[f]):
            problems.append(f"bad {f} {rec[f]!r}")
    for f in ("start_date", "end_date"):
        if rec.get(f):
            try:
                datetime.strptime(rec[f], "%Y-%m-%d")
            except ValueError:
                problems.append(f"bad {f} {rec[f]!r}")
    return problems


def read(raw: str, received: datetime | None = None, by: str | None = None, allow_path: bool = True) -> dict:
    received = (received or datetime.now(timezone.utc)).astimezone(HUB_TZ)
    dep = Deposit(raw, received, by, allow_path)
    events, source, extraction = _read(dep)
    records = [_record(e, source, extraction, dep) for e in events]
    return {
        "received": received.isoformat(),
        "records": records,
        "notes": dep.notes,
        "visible_text": getattr(dep, "visible_text", None),
        "cost_usd": round(dep.cost_usd, 6),
        "problems": {r["id"]: p for r in records if (p := check(r))},
    }
