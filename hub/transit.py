"""The way home (Night, his calls 2026-10-24): the last buses, trains and ferries from near a venue, on the night.

Auckland Transport publishes its timetable openly (GTFS, gtfs.at.govt.nz, no key). Once a week the hub fetches it and
keeps a small index: each stop's departures from 20:00 on, with the route and where it heads, and which days each
service runs. A night listing with coordinates then asks: from stops within a short walk, the last departure of each
route after the event ends. The answer is a timetable's, so the card says to check before relying on it.
"""
import csv
import io
import json
import math
import time
import urllib.request
import zipfile
from datetime import date, timedelta
from pathlib import Path

URL = "https://gtfs.at.govt.nz/gtfs.zip"
LATE = 20 * 60  # keep departures from 20:00 (GTFS runs past 24:00 for after-midnight trips)
WALK_M = 600
REFRESH_S = 7 * 86400
MODES = {"0": "tram", "1": "train", "2": "train", "3": "bus", "4": "ferry"}


def _rows(z: zipfile.ZipFile, name: str):
    with z.open(name) as f:
        yield from csv.DictReader(io.TextIOWrapper(f, encoding="utf-8-sig"))


def _mins(hms: str) -> int | None:
    try:
        h, m, _ = hms.strip().split(":")
        return int(h) * 60 + int(m)
    except ValueError:
        return None


def build(zip_path: Path) -> dict:
    """The index from a GTFS zip: stops, late departures per stop, and the service calendar."""
    z = zipfile.ZipFile(zip_path)
    routes = {r["route_id"]: (r.get("route_short_name") or r.get("route_long_name") or "", MODES.get(r.get("route_type", "3"), "bus"))
              for r in _rows(z, "routes.txt")}
    trips = {t["trip_id"]: (t["service_id"], t["route_id"], t.get("trip_headsign") or "") for t in _rows(z, "trips.txt")}
    late: dict[str, dict] = {}
    for st in _rows(z, "stop_times.txt"):
        m = _mins(st["departure_time"])
        if m is None or m < LATE or st.get("pickup_type") == "1":
            continue
        tr = trips.get(st["trip_id"])
        if not tr:
            continue
        service, route, head = tr
        key = (service, route, head)
        per = late.setdefault(st["stop_id"], {})
        if m > per.get(key, -1):  # only the last departure of each route and direction per service day matters
            per[key] = m
    used = set(late)
    stops = {s["stop_id"]: [s["stop_name"], round(float(s["stop_lat"]), 6), round(float(s["stop_lon"]), 6)]
             for s in _rows(z, "stops.txt") if s["stop_id"] in used}
    cal = {}
    for c in _rows(z, "calendar.txt"):
        cal[c["service_id"]] = {"days": "".join(c[d] for d in ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")),
                                "from": c["start_date"], "to": c["end_date"], "add": [], "drop": []}
    for c in _rows(z, "calendar_dates.txt"):
        e = cal.setdefault(c["service_id"], {"days": "0000000", "from": "99999999", "to": "00000000", "add": [], "drop": []})
        (e["add"] if c["exception_type"] == "1" else e["drop"]).append(c["date"])
    deps = {sid: [[svc, routes.get(r, ("", "bus"))[0], routes.get(r, ("", "bus"))[1], head, m] for (svc, r, head), m in per.items()]
            for sid, per in late.items()}
    return {"built": int(time.time()), "stops": stops, "deps": deps, "cal": cal}


def runs(cal: dict, service: str, day: date) -> bool:
    c = cal.get(service)
    if not c:
        return False
    d = day.strftime("%Y%m%d")
    if d in c["drop"]:
        return False
    if d in c["add"]:
        return True
    return c["from"] <= d <= c["to"] and c["days"][day.weekday()] == "1"


def _metres(a_lat, a_lng, b_lat, b_lng) -> float:
    k = math.pi / 180
    x = (b_lng - a_lng) * k * math.cos((a_lat + b_lat) / 2 * k)
    return math.hypot(x, (b_lat - a_lat) * k) * 6371000


def last_rides(index: dict, lat: float, lng: float, day: date, after_min: int, limit: int = 3) -> list[dict]:
    """The last departure of each route from stops within a short walk, after the event ends, latest first."""
    near = [(sid, s) for sid, s in index["stops"].items() if _metres(lat, lng, s[1], s[2]) <= WALK_M]
    best: dict[tuple, dict] = {}
    for sid, s in near:
        for svc, route, mode, head, m in index["deps"].get(sid, []):
            if m < after_min or not runs(index["cal"], svc, day):
                continue
            key = (route, head)
            if key not in best or m > best[key]["m"]:
                best[key] = {"m": m, "route": route, "mode": mode, "to": head, "stop": s[0],
                             "walk": round(_metres(lat, lng, s[1], s[2]))}
    out = sorted(best.values(), key=lambda x: -x["m"])[:limit]
    for x in out:
        x["at"] = f"{x['m'] // 60 % 24:02d}:{x['m'] % 60:02d}"
    return out


class Timetable:
    """The index on disk beside the store, refreshed weekly in the background; never blocks a request."""
    def __init__(self, folder: Path):
        self.folder, self.index, self.busy = Path(folder), None, False
        f = self.folder / "transit.json"
        if f.exists():
            try:
                self.index = json.loads(f.read_text())
            except ValueError:
                self.index = None

    def stale(self) -> bool:
        return self.index is None or time.time() - self.index.get("built", 0) > REFRESH_S

    def refresh(self) -> None:
        if self.busy:
            return
        self.busy = True
        try:
            self.folder.mkdir(parents=True, exist_ok=True)
            z = self.folder / "gtfs.zip"
            req = urllib.request.Request(URL, headers={"User-Agent": "TheWheel/0.1"})
            with urllib.request.urlopen(req, timeout=300) as r, open(z, "wb") as f:
                while chunk := r.read(1 << 20):
                    f.write(chunk)
            idx = build(z)
            (self.folder / "transit.json.tmp").write_text(json.dumps(idx, separators=(",", ":")))
            (self.folder / "transit.json.tmp").rename(self.folder / "transit.json")
            z.unlink(missing_ok=True)
            self.index = idx
        finally:
            self.busy = False

    def rides(self, rec: dict, day: str) -> list[dict] | None:
        if not self.index or rec.get("latitude") is None or rec.get("longitude") is None:
            return None
        end = rec.get("end_time") or rec.get("last_entry") or rec.get("start_time")
        after = (_mins(end + ":00") if end else None) or 21 * 60
        start = _mins((rec.get("start_time") or "00:00") + ":00") or 0
        if after < start or after < 6 * 60:  # ends after midnight: GTFS counts those trips as 24:00 and on
            after += 24 * 60
        d = date.fromisoformat(day)
        return last_rides(self.index, rec["latitude"], rec["longitude"], d, after) or []
