"""Web pages -> candidate events from their schema.org data, no AI.

Many ticket and venue pages carry an `Event` record in a
<script type="application/ld+json"> block for search engines. This reads it.
Pages without one hand their visible text to the AI step instead (`page_text`).
"""

import html
import json
import re
from datetime import datetime
from zoneinfo import ZoneInfo

from lxml import html as lxml_html

HUB_TZ = ZoneInfo("Pacific/Auckland")
STATUS = {"EventCancelled": "cancelled", "EventPostponed": "postponed", "EventRescheduled": "confirmed"}


def _nodes(data):
    if isinstance(data, list):
        for d in data:
            yield from _nodes(d)
    elif isinstance(data, dict):
        if "@graph" in data:
            yield from _nodes(data["@graph"])
        yield data


def _is_event(node: dict) -> bool:
    types = node.get("@type", [])
    types = [types] if isinstance(types, str) else types
    return any(t.endswith("Event") for t in types if isinstance(t, str))


def _when(value: str | None):
    if not value:
        return None, None
    if len(value) == 10:
        return value, None
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=HUB_TZ)
    local = dt.astimezone(HUB_TZ)
    return local.date().isoformat(), local.strftime("%H:%M")


def _text(v) -> str | None:
    if isinstance(v, dict):
        v = v.get("name")
    if isinstance(v, list):
        v = ", ".join(str(x.get("name", x)) if isinstance(x, dict) else str(x) for x in v)
    return html.unescape(str(v)).strip() if v else None  # some builders escape twice ("&amp;amp;")


def _strip_site(name: str | None, site: str | None) -> str | None:
    """'Make Give Live — Hub Matakana' -> 'Make Give Live' when the tail is the site's own name."""
    if not name or not site:
        return name
    return re.sub(r"\s+[—–|-]\s+" + re.escape(site.strip()) + r"\s*$", "", name).strip() or name


def _event(node: dict) -> dict:
    ev = {"name": _text(node.get("name")), "description": _text(node.get("description"))}
    ev["start_date"], ev["start_time"] = _when(node.get("startDate"))
    ev["end_date"], ev["end_time"] = _when(node.get("endDate"))
    ev["time_known"] = ev["start_time"] is not None
    status = str(node.get("eventStatus", "")).rsplit("/", 1)[-1]
    ev["status"] = STATUS.get(status, "confirmed")
    loc = node.get("location") or {}
    loc = loc[0] if isinstance(loc, list) and loc else loc
    if isinstance(loc, dict):
        ev["online"] = "VirtualLocation" in str(loc.get("@type"))
        ev["location_name"] = _text(loc.get("name"))
        addr = loc.get("address")
        if isinstance(addr, dict):
            ev["location_address"] = _text(addr.get("streetAddress"))
            ev["location_locality"] = _text(addr.get("addressLocality"))
        elif addr:
            ev["location_address"] = _text(addr)
        geo = loc.get("geo") or {}
        if isinstance(geo, dict) and geo.get("latitude"):
            ev["latitude"], ev["longitude"] = float(geo["latitude"]), float(geo["longitude"])
    offers = node.get("offers")
    offers = offers[0] if isinstance(offers, list) and offers else offers
    if isinstance(offers, dict):
        if offers.get("price") is not None:
            ev["price"] = f"${offers['price']}" if str(offers["price"]) not in ("0", "0.00") else "free"
        ev["tickets_url"] = offers.get("url")
    ev["organiser"] = _text(node.get("organizer"))
    ev["website"] = node.get("url")
    image = node.get("image")
    ev["cover_image"] = image[0] if isinstance(image, list) and image else (image if isinstance(image, str) else None)
    return {k: v for k, v in ev.items() if v is not None}


def parse(page: str) -> list[dict]:
    tree = lxml_html.fromstring(page)
    site = (tree.xpath('//meta[@property="og:site_name"]/@content') or [None])[0]
    events = []
    for script in tree.xpath('//script[@type="application/ld+json"]'):
        try:
            data = json.loads(script.text_content())
        except (json.JSONDecodeError, TypeError):
            continue
        events += [_event(n) for n in _nodes(data) if _is_event(n)]
    for e in events:
        e["name"] = _strip_site(e.get("name"), site)
    return [e for e in events if e.get("name") and e.get("start_date")]


def is_thin(events: list[dict]) -> bool:
    """Page data that gives only a name and times (Squarespace does): the AI reads the page for the rest."""
    return all(not e.get("location_name") and not e.get("description") for e in events)


def page_text(page: str, limit: int = 20000) -> str:
    """Visible text plus the page's own title and description, for the AI step."""
    tree = lxml_html.fromstring(page)
    meta = []
    for prop in ("og:title", "og:description", "description"):
        for m in tree.xpath(f'//meta[@property="{prop}" or @name="{prop}"]/@content'):
            meta.append(m.strip())
    for bad in tree.xpath("//script|//style|//noscript|//svg|//header|//footer|//nav"):
        bad.drop_tree()
    # the page's own content, where it marks one; menus and footers list other events
    main = tree.xpath("//main|//article|//*[@role='main']|//div[@id='ajax-content-wrap']")
    body = html.unescape(" ".join((main[0] if main else tree).text_content().split()))
    return ("\n".join(dict.fromkeys(meta)) + "\n\n" + body)[:limit]
