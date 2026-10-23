"""Night's own, round four (his calls 2026-10-24): set times, the way home from a timetable, rides for a night.
The anonymous Going count lives in the member service (zk/test/e2e.test.mjs).

    /usr/bin/python3 -E -s -m unittest tests/test_night.py
"""
import json
import sys
import tempfile
import unittest
import zipfile
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "tests" / "fixtures" / "gate-patterns.txt"
TMP = Path(tempfile.mkdtemp(prefix="wheel-night-"))
sys.path.insert(0, str(ROOT))
from hub import day, gate, server, store, transit  # noqa: E402

SAT = date(2026, 10, 31)  # a Saturday


def tiny_gtfs(path: Path):
    files = {
        "routes.txt": "route_id,route_short_name,route_long_name,route_type\nR18,18,,3\nRT,EAST,,2\n",
        "trips.txt": "route_id,service_id,trip_id,trip_headsign\nR18,WE,t1,Henderson\nR18,WE,t2,Henderson\nRT,WD,t3,Manukau\n",
        "stop_times.txt": "trip_id,arrival_time,departure_time,stop_id,stop_sequence,pickup_type\n"
                          "t1,23:10:00,23:10:00,S1,1,0\nt2,25:05:00,25:05:00,S1,1,0\nt3,23:40:00,23:40:00,S2,1,0\nt1,19:00:00,19:00:00,S2,2,0\n",
        "stops.txt": "stop_id,stop_name,stop_lat,stop_lon\nS1,Karangahape Rd,-36.8580,174.7560\nS2,Far away,-36.95,174.90\n",
        "calendar.txt": "service_id,monday,tuesday,wednesday,thursday,friday,saturday,sunday,start_date,end_date\n"
                        "WE,0,0,0,0,0,1,1,20260101,20271231\nWD,1,1,1,1,1,0,0,20260101,20271231\n",
        "calendar_dates.txt": "service_id,date,exception_type\nWE,20261107,2\n",
    }
    with zipfile.ZipFile(path, "w") as z:
        for k, v in files.items():
            z.writestr(k, v)


class WayHome(unittest.TestCase):
    def setUp(self):
        tiny_gtfs(TMP / "g.zip")
        self.idx = transit.build(TMP / "g.zip")

    def test_index_keeps_late_departures_only(self):
        self.assertEqual(set(self.idx["stops"]), {"S1", "S2"})
        self.assertTrue(all(d[4] >= transit.LATE for deps in self.idx["deps"].values() for d in deps))

    def test_last_ride_after_the_event_on_its_day(self):
        got = transit.last_rides(self.idx, -36.8594, 174.7543, SAT, 23 * 60)
        self.assertEqual([(x["at"], x["route"], x["to"]) for x in got], [("01:05", "18", "Henderson")], "the after-midnight trip, the far stop left out")
        self.assertEqual(transit.last_rides(self.idx, -36.8594, 174.7543, SAT + timedelta(days=7), 23 * 60), [], "a dropped date runs nothing")
        self.assertEqual(transit.last_rides(self.idx, -36.8594, 174.7543, SAT + timedelta(days=2), 23 * 60), [], "weekend service only")

    def test_listing_times(self):
        tt = transit.Timetable(TMP / "none")
        tt.index = self.idx
        rec = {"latitude": -36.8594, "longitude": 174.7543, "start_time": "21:00", "end_time": "01:30"}
        self.assertEqual(tt.rides(rec, SAT.isoformat()), [], "ends 01:30: the 01:05 has gone")
        rec["end_time"] = "00:30"
        self.assertEqual([x["at"] for x in tt.rides(rec, SAT.isoformat())], ["01:05"])
        self.assertIsNone(tt.rides({"start_time": "21:00"}, SAT.isoformat()), "no coordinates, no line")


class Sets(unittest.TestCase):
    def test_clean(self):
        got = server.clean_sets([{"act": "Moana Trio", "start": "21:30", "end": "22:15", "stage": "Main"},
                                 {"act": "Opening DJ", "start": "20:00"}, {"act": "", "start": "23:00"}])
        self.assertEqual([x["act"] for x in got], ["Opening DJ", "Moana Trio"])
        for bad in ([{"act": "x", "start": "9pm"}], [{"act": "x", "start": "21:00", "date": "Sat"}]):
            with self.assertRaises(ValueError):
                server.clean_sets(bad)


class Rides(unittest.TestCase):
    def test_rides_stay_off_the_ask_board(self):
        store.DB = TMP / "rides.db"
        server._local.__dict__.clear()
        server.GATE = gate.load(FIXTURE, builtin=False)
        db = server.db()
        today = date.today().isoformat()
        r = day.clean_ride({"kind": "offer", "dir": "from", "seats": "3", "area": "Ponsonby"})
        db.execute("INSERT INTO asks(id, account, kind, text, area, by_day, day, listing_id, dir, seats) VALUES(?,?,?,?,?,?,?,?,?,?)",
                   ("8" * 16, "a" * 16, r["kind"], r["text"], r["area"], today, today, "9" * 16, r["dir"], r["seats"]))
        db.commit()
        self.assertEqual(day.asks_open(db, today, None), [])
        self.assertEqual([(x["kind"], x["dir"], x["seats"]) for x in day.rides_for(db, "9" * 16, "b" * 16)], [("offer", "from", 3)])
        self.assertEqual(day.ride_counts(db), {"9" * 16: {"offer": 1, "need": 0}})
        with self.assertRaises(ValueError):
            day.clean_ride({"kind": "teleport", "dir": "to"})


if __name__ == "__main__":
    unittest.main()
