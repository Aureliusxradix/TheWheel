"""Getting listings to people (the Roadmap's "Getting events to you", built 2026-10-22): a link per listing that shows
a preview in a group chat, a calendar file per listing, and feeds to subscribe to (calendar and RSS).

Everything here is built from a listing as anyone would see it: the server strips private and members-only fields
before a record reaches these functions, and the identity gate reads each answer before it leaves.
"""
import html
from datetime import date, datetime, timedelta, timezone
from xml.sax.saxutils import escape as xml_escape

from reader.core import HUB_TZ

CAL_STATUS = {"cancelled": "CANCELLED", "tentative": "TENTATIVE", "postponed": "TENTATIVE"}


def on(rec: dict) -> str:
    """The date a listing is shown on: a repeating one's next date, else its own."""
    return rec.get("next_date") or rec["start_date"]


def short_day(iso: str) -> str:
    d = date.fromisoformat(iso)
    return f"{d:%a} {d.day} {d:%b}"


def where(rec: dict) -> str:
    name, town = rec.get("location_name") or "", rec.get("location_locality") or ""
    return ", ".join(p for p in (name, town if town and town not in name else "") if p)


def line(rec: dict) -> str:
    """One line on when and where: what a preview and a feed item say under the name."""
    when = short_day(on(rec)) + (f", {rec['start_time']}" if rec.get("start_time") else "")
    parts = [when, where(rec), rec.get("price") or ""]
    if rec.get("status") in ("cancelled", "postponed"):
        parts.insert(0, rec["status"].capitalize())
    return " · ".join(p for p in parts if p)


def page(rec: dict, share_url: str, open_url: str, flyer_url: str | None) -> str:
    """The share link's page: a preview for chat apps, then straight on to the listing on The Wheel."""
    e = lambda s: html.escape(str(s), quote=True)  # noqa: E731
    desc = line(rec) + (f". {rec['summary']}" if rec.get("summary") else "")
    checked = rec.get("review", {}).get("state") == "approved"
    meta = [f'<meta property="og:title" content="{e(rec["name"])}">',
            f'<meta property="og:description" content="{e(desc[:300])}">',
            '<meta property="og:site_name" content="The Wheel">', '<meta property="og:type" content="website">',
            f'<meta property="og:url" content="{e(share_url)}">', '<meta name="twitter:card" content="summary">']
    if flyer_url:
        meta.append(f'<meta property="og:image" content="{e(flyer_url)}">')
    if not checked:  # still waiting for review: kept out of search until a person has checked it
        meta.append('<meta name="robots" content="noindex">')
    return f"""<!doctype html>
<html lang="en-NZ"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{e(rec["name"])} · The Wheel</title>
<meta name="description" content="{e(desc[:300])}">
{chr(10).join(meta)}
<meta http-equiv="refresh" content="0; url={e(open_url)}">
<style>body{{font:1rem/1.6 system-ui,sans-serif;max-width:36rem;margin:3rem auto;padding:0 16px;background:#100D16;color:#fff}}a{{color:#FF9EC7}}</style>
</head><body><p><a href="{e(open_url)}">{e(rec["name"])}</a></p><p>{e(line(rec))}</p><p>On The Wheel, community events in one list.</p></body></html>
"""


def gone(open_url: str) -> str:
    """A share link to a listing that has gone (turned down, or held back): a plain page on to the list."""
    u = html.escape(open_url, quote=True)
    return f"""<!doctype html>
<html lang="en-NZ"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>The Wheel</title><meta name="robots" content="noindex">
<style>body{{font:1rem/1.6 system-ui,sans-serif;max-width:36rem;margin:3rem auto;padding:0 16px;background:#100D16;color:#fff}}a{{color:#FF9EC7}}</style>
</head><body><p>This listing has gone from The Wheel.</p><p><a href="{u}">See what's on</a></p></body></html>
"""


# ---------- calendar files (RFC 5545) ----------

def _text(s) -> str:
    return str(s).replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\r\n", "\\n").replace("\n", "\\n")


def _fold(ln: str) -> str:
    """Lines longer than 75 bytes continue on the next line after a space, never splitting a character."""
    raw, out = ln.encode(), []
    while len(raw) > 75:
        cut = 75 if not out else 74
        while cut and (raw[cut] & 0xC0) == 0x80:
            cut -= 1
        out.append(raw[:cut].decode())
        raw = raw[cut:]
    out.append(raw.decode())
    return "\r\n ".join(out)


def _utc(day: str, hhmm: str) -> datetime:
    local = datetime.combine(date.fromisoformat(day), datetime.strptime(hhmm, "%H:%M").time(), HUB_TZ)
    return local.astimezone(timezone.utc)


def vevent(rec: dict, day: str, url: str, stamp: datetime) -> list[str]:
    """One date of a listing. Times are Auckland times written in UTC; a listing without a time is an all-day one."""
    span = 0
    if rec.get("end_date") and rec["end_date"] >= rec["start_date"]:
        span = (date.fromisoformat(rec["end_date"]) - date.fromisoformat(rec["start_date"])).days
    end_day = (date.fromisoformat(day) + timedelta(days=span)).isoformat()
    out = ["BEGIN:VEVENT", f"UID:{rec['id']}-{day.replace('-', '')}@the-wheel", f"DTSTAMP:{stamp:%Y%m%dT%H%M%SZ}"]
    if rec.get("start_time"):
        start = _utc(day, rec["start_time"])
        out.append(f"DTSTART:{start:%Y%m%dT%H%M%SZ}")
        if rec.get("end_time"):
            end = _utc(end_day, rec["end_time"])
            if end <= start:  # ends after midnight
                end += timedelta(days=1)
            out.append(f"DTEND:{end:%Y%m%dT%H%M%SZ}")
    else:
        out.append(f"DTSTART;VALUE=DATE:{day.replace('-', '')}")
        out.append(f"DTEND;VALUE=DATE:{(date.fromisoformat(end_day) + timedelta(days=1)):%Y%m%d}")
    out.append("SUMMARY:" + _text(rec["name"]))
    place = ", ".join(p for p in (rec.get("location_name"), rec.get("location_address"), rec.get("location_locality")) if p)
    if place:
        out.append("LOCATION:" + _text(place))
    desc = [rec.get("summary") or "", f"Price: {rec['price']}" if rec.get("price") else "",
            f"Repeats: {rec['recurrence']}" if rec.get("recurrence") else "",
            f"Organiser's page: {rec['website']}" if rec.get("website") else "", f"On The Wheel: {url}"]
    out.append("DESCRIPTION:" + _text("\n".join(d for d in desc if d)))
    out.append("URL:" + url)
    out.append("STATUS:" + CAL_STATUS.get(rec.get("status") or "", "CONFIRMED"))
    out.append("END:VEVENT")
    return out


def calendar(items: list[tuple[dict, str, str]], name: str) -> bytes:
    """items: (listing, date, its link). A feed refreshes every 6 hours in apps that read the hint."""
    stamp = datetime.now(timezone.utc)
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//The Wheel//Community events//EN", "CALSCALE:GREGORIAN",
             "METHOD:PUBLISH", "X-WR-CALNAME:" + _text(name), "X-WR-TIMEZONE:Pacific/Auckland",
             "REFRESH-INTERVAL;VALUE=DURATION:PT6H", "X-PUBLISHED-TTL:PT6H"]
    for rec, day, url in items:
        lines += vevent(rec, day, url, stamp)
    lines.append("END:VCALENDAR")
    return ("\r\n".join(_fold(ln) for ln in lines) + "\r\n").encode()


def dates_for_feed(rec: dict) -> list[str]:
    """Every date ahead for a repeating listing (about half a year), else the one it is on."""
    return rec.get("repeats_on") or [on(rec)]


# ---------- RSS ----------

def rss(items: list[tuple[dict, str]], title: str, site_url: str) -> bytes:
    """items: (listing, its link), soonest first. Each listing is one item; a new listing is a new item."""
    x = xml_escape
    out = ['<?xml version="1.0" encoding="utf-8"?>', '<rss version="2.0"><channel>', f"<title>{x(title)}</title>",
           f"<link>{x(site_url)}</link>", "<description>Community events, added and checked by the people who go.</description>",
           "<language>en-nz</language>"]
    for rec, url in items:
        body = line(rec) + (f". {rec['summary']}" if rec.get("summary") else "")
        out.append(f"<item><title>{x(short_day(on(rec)) + ': ' + rec['name'])}</title><link>{x(url)}</link>"
                   f'<guid isPermaLink="false">{x(rec["id"])}</guid><description>{x(body)}</description></item>')
    out.append("</channel></rss>")
    return "\n".join(out).encode()


# ---------- the weekly digest (2026-10-22, the Roadmap's "A weekly digest"): the coming week's checked listings ----------

def week_items(items: list[dict], start: str, days: int = 7) -> list[tuple[str, dict]]:
    """(date, listing) for every checked listing on in the days from start, soonest first; a repeat on each of its dates."""
    end = (date.fromisoformat(start) + timedelta(days=days - 1)).isoformat()
    out = []
    for rec in items:
        span = 0
        if rec.get("end_date") and rec["end_date"] > rec["start_date"]:
            span = (date.fromisoformat(rec["end_date"]) - date.fromisoformat(rec["start_date"])).days
        for day in dates_for_feed(rec):
            last = (date.fromisoformat(day) + timedelta(days=span)).isoformat()
            if day <= end and last >= start:
                out.append((max(day, start), rec))
    return sorted(out, key=lambda x: (x[0], x[1].get("start_time") or "", x[1]["name"]))


def digest(items: list[dict], start: str, site_url: str, limit: int = 3500) -> dict:
    """The week as one short message: a line per listing under its day, cut to fit a phone notification."""
    rows = week_items(items, start)
    lines, day, shown = [], None, 0
    for d, rec in rows:
        head = f"**{short_day(d)}**"
        add = ([head] if d != day else []) + [" · ".join([f"- {rec['name']}"] + [x for x in (rec.get("start_time"), where(rec)) if x])]
        if len("\n".join(lines + add)) > limit:
            break
        lines += add
        day, shown = d, shown + 1
    more = len(rows) - shown
    if more:
        lines.append(f"…and {more} more on The Wheel.")
    first = short_day(start)
    return {"week": start, "title": f"The Wheel: the week from {first}", "count": len(rows), "url": site_url,
            "text": "\n".join(lines) if lines else "A quiet week so far. Add what you know about on The Wheel."}


def digest_rss(d: dict, feed_url: str) -> bytes:
    """The digest as a feed: one item a week, the same words as the push."""
    x = xml_escape
    return "\n".join(['<?xml version="1.0" encoding="utf-8"?>', '<rss version="2.0"><channel>',
                      "<title>The Wheel: weekly</title>", f"<link>{x(d['url'])}</link>",
                      "<description>What's on in the coming week, checked by the people who go.</description>", "<language>en-nz</language>",
                      f"<item><title>{x(d['title'])}</title><link>{x(d['url'])}</link>"
                      f'<guid isPermaLink="false">the-wheel-week-{x(d["week"])}</guid><description>{x(d["text"])}</description></item>',
                      "</channel></rss>"]).encode()
