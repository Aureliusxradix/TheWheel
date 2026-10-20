"""Calendar feeds (RFC 5545) -> candidate events, no AI. Standard library only.

Covers what venue and Google calendars publish: VEVENT with SUMMARY,
DESCRIPTION, LOCATION, URL, STATUS, RRULE, and DTSTART/DTEND as a date,
a UTC time, a TZID time or a floating time.
"""

from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

HUB_TZ = ZoneInfo("Pacific/Auckland")


def _unfold(text: str) -> list[str]:
    lines: list[str] = []
    for raw in text.replace("\r\n", "\n").split("\n"):
        if raw[:1] in (" ", "\t") and lines:
            lines[-1] += raw[1:]
        elif raw:
            lines.append(raw)
    return lines


def _unescape(v: str) -> str:
    return v.replace("\\n", "\n").replace("\\N", "\n").replace("\\,", ",").replace("\\;", ";").replace("\\\\", "\\")


def _split(line: str) -> tuple[str, dict, str]:
    head, _, value = line.partition(":")
    name, *params = head.split(";")
    return name.upper(), dict(p.split("=", 1) for p in params if "=" in p), value


def _when(value: str, params: dict) -> tuple[date, str | None]:
    """-> (local date, HH:MM or None) in Auckland time."""
    if params.get("VALUE") == "DATE" or len(value) == 8:
        return date(int(value[:4]), int(value[4:6]), int(value[6:8])), None
    dt = datetime.strptime(value.rstrip("Z"), "%Y%m%dT%H%M%S")
    if value.endswith("Z"):
        dt = dt.replace(tzinfo=timezone.utc)
    elif "TZID" in params:
        try:
            dt = dt.replace(tzinfo=ZoneInfo(params["TZID"].strip('"')))
        except Exception:
            dt = dt.replace(tzinfo=HUB_TZ)
    else:
        dt = dt.replace(tzinfo=HUB_TZ)  # floating time: read as local
    local = dt.astimezone(HUB_TZ)
    return local.date(), local.strftime("%H:%M")


def parse(text: str) -> list[dict]:
    events, cur = [], None
    for line in _unfold(text):
        name, params, value = _split(line)
        if name == "BEGIN" and value.upper() == "VEVENT":
            cur = {}
        elif name == "END" and value.upper() == "VEVENT" and cur is not None:
            if "start_date" in cur:
                events.append(cur)
            cur = None
        elif cur is None:
            continue
        elif name == "UID":
            cur["source_id"] = value
        elif name == "SUMMARY":
            cur["name"] = _unescape(value).strip()
        elif name == "DESCRIPTION":
            cur["description"] = _unescape(value).strip()
        elif name == "LOCATION":
            cur["location_name"] = _unescape(value).strip()
        elif name == "URL":
            cur["website"] = value.strip()
        elif name == "RRULE":
            cur["recurrence"] = value.strip()
        elif name == "STATUS":
            cur["status"] = {"CANCELLED": "cancelled", "TENTATIVE": "tentative"}.get(value.upper(), "confirmed")
        elif name in ("DTSTART", "DTEND"):
            d, t = _when(value, params)
            key = "start" if name == "DTSTART" else "end"
            cur[f"{key}_date"], cur[f"{key}_time"] = d.isoformat(), t
            if name == "DTSTART":
                cur["time_known"] = t is not None
    return events
