"""A repeating listing's next date, read from the source's own words (the `recurrence` field).

A listing keeps the date it was found with; the page shows the next time it happens, so a weekly class found on a
Monday reads the same on every view a week later. Only clear wording moves a date:
  weekly       every Monday · Tuesdays · weekly · every week
  every n weeks  fortnightly · every second Friday · every other Friday · every six weeks
  monthly      the second Sunday of the month · monthly, every fourth Sunday · every two months, the last Sunday
Anything else (opening hours like "Monday–Friday", a bare "monthly", wording that names a different weekday from
the listing's own date) keeps the date it was found with, and the page points to the link for the next one.
"""
import re
from datetime import date, timedelta

DAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
DAY = r"(" + "|".join(DAYS) + r")"  # full names only: "mon" would catch "monthly"
NUMS = {"two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "eight": 8, "other": 2, "second": 2}
NTH = {"first": 1, "1st": 1, "second": 2, "2nd": 2, "third": 3, "3rd": 3, "fourth": 4, "forth": 4, "4th": 4, "last": -1}


def _weekday(word: str) -> int:
    return next(i for i, d in enumerate(DAYS) if d.startswith(word[:3]))


def rule(text: str, start: date):
    """-> ("days", n) or ("months", n, nth, weekday), or None when the wording is not clear enough to move a date."""
    t = (text or "").lower()
    if re.search(DAY + r"\s*(–|-|to)\s*" + DAY, t):  # opening hours, not a repeat
        return None
    named = [_weekday(m.group(1)) for m in re.finditer(r"\b" + DAY + r"s?\b", t)]
    if any(w != start.weekday() for w in named):  # the words and the listing's own date disagree
        return None
    monthly = re.search(r"\bmonth", t)
    nth = re.search(r"\b(" + "|".join(NTH) + r")\s+" + DAY, t)
    if monthly and nth:
        n = NTH[nth.group(1)]
        weekday = _weekday(nth.group(2))
        every = re.search(r"every\s+(two|three|four|six|2|3|4|6)\s+months|bi-?monthly", t)
        months = 1 if not every else 2 if every.group(0).startswith("bi") else int(NUMS.get(every.group(1), every.group(1)))
        return ("months", months, n, weekday) if _nth_weekday(start.year, start.month, n, weekday) == start else None
    if monthly:
        return None
    m = re.search(r"every\s+(two|three|four|six|eight|other|second|2|3|4|6|8)\s+(" + DAY + r"|weeks?)", t)
    if m:
        return ("days", 7 * int(NUMS.get(m.group(1), m.group(1))))
    if re.search(r"fortnight|bi-?weekly", t):
        return ("days", 14)
    if re.search(r"weekly|every\s+week|every\s+" + DAY + r"|\b" + DAY + r"s\b", t):
        return ("days", 7)
    return None


def _nth_weekday(year: int, month: int, n: int, weekday: int):
    if n > 0:
        first = date(year, month, 1)
        day = first + timedelta(days=(weekday - first.weekday()) % 7 + 7 * (n - 1))
        return day if day.month == month else None
    last = (date(year + month // 12, month % 12 + 1, 1) - timedelta(days=1))
    return last - timedelta(days=(last.weekday() - weekday) % 7)


def next_on(text: str, start_iso: str, today_iso: str):
    """The first date on or after today the listing happens, as YYYY-MM-DD, or None when it cannot be read."""
    start, today = date.fromisoformat(start_iso), date.fromisoformat(today_iso)
    r = rule(text, start)
    if not r:
        return None
    if start >= today:
        return start_iso
    if r[0] == "days":
        steps = -(-(today - start).days // r[1])
        return (start + timedelta(days=steps * r[1])).isoformat()
    _, months, n, weekday = r
    y, m = start.year, start.month
    for _ in range(60):
        day = _nth_weekday(y, m, n, weekday)
        if day and day >= today:
            return day.isoformat()
        m += months
        y, m = y + (m - 1) // 12, (m - 1) % 12 + 1
    return None


def dates_ahead(text: str, start_iso: str, today_iso: str, days: int = 183) -> list[str]:
    """Every date the listing happens from today to about half a year on, for picking a day; empty when unread."""
    out, frm = [], date.fromisoformat(today_iso)
    until = frm + timedelta(days=days)
    while True:
        nxt = next_on(text, start_iso, frm.isoformat())
        if not nxt or date.fromisoformat(nxt) > until:
            return out
        out.append(nxt)
        frm = date.fromisoformat(nxt) + timedelta(days=1)
