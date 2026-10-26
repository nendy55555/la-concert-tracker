#!/usr/bin/env python3
"""Tests for scripts/refresh_concerts.py. Zero network: every HTTP call is injected."""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))

import refresh_concerts as rc  # noqa: E402
import weekly_digest as wd  # noqa: E402
from test_index_html_integrity import KNOWN_VENUES, KNOWN_GENRES  # noqa: E402

FIX = ROOT / "tests" / "fixtures"
FEED_FIXTURE = FIX / "mini_index_feed.html"
PT = ZoneInfo("America/Los_Angeles")
TODAY = date(2026, 10, 26)
NOW = datetime(2026, 10, 26, 9, 5, tzinfo=PT)


def load_fixture(name: str) -> dict:
    return json.loads((FIX / name).read_text())


class TestVenueRegistry(unittest.TestCase):
    def setUp(self):
        self.venues = rc.load_venues(ROOT / "scripts" / "venues.json")

    def test_names_match_known_venues(self):
        self.assertEqual({v["name"] for v in self.venues}, KNOWN_VENUES)

    def test_ids_unique_and_nonempty_strings(self):
        ids = [i for v in self.venues for i in v["tmVenueIds"]]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertTrue(all(isinstance(i, str) and i for i in ids))

    def test_tiers_and_vendors(self):
        for v in self.venues:
            self.assertIn(v["tier"], (1, 2, 3, 4), v["name"])
            self.assertTrue(v["vendor"], v["name"])


NOVO = {"name": "The Novo", "tmVenueIds": ["KovZ917A25f"], "vendor": "AXS", "tier": 2}


class TestEventToRow(unittest.TestCase):
    def setUp(self):
        self.events = load_fixture("tm_events_sample.json")["_embedded"]["events"]

    def test_e1_music_event_maps_to_row(self):
        row = rc.event_to_row(self.events[0], NOVO, NOW)
        self.assertEqual(row["date"], "2026-11-20")
        self.assertEqual(row["name"], "Headliner Name: The Big Tour")
        self.assertEqual(row["venue"], "The Novo")
        self.assertEqual(row["genre"], "Hip-Hop/R&B")
        self.assertEqual(row["artists"], ["Headliner Name", "Opener Name"])
        self.assertEqual(row["support"], "Opener Name")
        self.assertEqual(row["spotifyMonthlyListeners"], 0)
        self.assertEqual(row["ticketUrl"], "https://www.ticketmaster.com/headliner-name-los-angeles-11-20-2026/event/vvG1TEST0001")
        self.assertEqual(row["ticketVendor"], "AXS")
        self.assertEqual(row["onSaleDate"], "2026-05-29T10:00")
        self.assertEqual(row["presaleDate"], "2026-05-28T10:00")
        self.assertEqual(row["tmId"], "vvG1TEST0001")
        self.assertEqual(row["firstSeen"], "2026-10-26T09:05:00-07:00")

    def test_e2_sports_segment_excluded(self):
        crypto = {"name": "Crypto.com Arena", "tmVenueIds": ["KovZpZAEdntA"], "vendor": "AXS", "tier": 4}
        self.assertIsNone(rc.event_to_row(self.events[1], crypto, NOW))

    def test_e2b_out_of_state_venue_excluded(self):
        ev = json.loads(json.dumps(self.events[0]))
        ev["_embedded"]["venues"][0]["state"] = {"stateCode": "NM"}
        self.assertIsNone(rc.event_to_row(ev, NOVO, NOW))
        ev["_embedded"]["venues"][0]["state"] = {"stateCode": "CA"}
        self.assertIsNotNone(rc.event_to_row(ev, NOVO, NOW))

    def test_e3_cancelled_and_tbd_excluded(self):
        wiltern = {"name": "The Wiltern", "tmVenueIds": ["KovZpZAEAl6A"], "vendor": "Ticketmaster", "tier": 2}
        troub = {"name": "Troubadour", "tmVenueIds": ["KovZpa4eIe"], "vendor": "Troubadour Box Office", "tier": 1}
        self.assertIsNone(rc.event_to_row(self.events[2], wiltern, NOW))
        self.assertIsNone(rc.event_to_row(self.events[3], troub, NOW))

    def test_e4_genre_map(self):
        cases = {"Hip-Hop/Rap": "Hip-Hop/R&B", "R&B": "Hip-Hop/R&B", "Dance/Electronic": "Electronic/EDM",
                 "Metal": "Rock", "Alternative": "Rock", "Rock": "Rock", "Folk": "Indie/Folk", "Country": "Indie/Folk",
                 "Latin": "Latin", "Punk": "Punk", "Pop": "Pop", "Jazz": "Other", "Undefined": "Other", None: "Other"}
        for tm, want in cases.items():
            self.assertEqual(rc.map_genre(tm), want, tm)
            self.assertIn(want, KNOWN_GENRES)


class TestFetchVenueEvents(unittest.TestCase):
    def test_e5_pagination_dedupe_and_window(self):
        pages = {0: load_fixture("tm_events_sample.json"), 1: load_fixture("tm_events_page2.json")}
        calls: list[str] = []

        def fake_http(url: str) -> dict:
            calls.append(url)
            page = int(url.split("page=")[1].split("&")[0])
            return pages[page]

        seen: dict = {}
        rows = rc.fetch_venue_events(NOVO, "KEY", TODAY, NOW, http=fake_http, seen=seen)
        self.assertEqual(len(calls), 2)
        self.assertEqual(sorted(r["tmId"] for r in rows), ["vvG1TEST0001", "vvG1TEST0005"])
        self.assertEqual(seen, {"KovZ917A25f": "The Novo by Microsoft, ?"})  # fixture venues carry no city
        self.assertTrue(all("apikey=KEY" in u and "venueId=KovZ917A25f" in u for u in calls))
        self.assertTrue(all("classificationName=music" in u for u in calls))
        end = (TODAY + rc.timedelta(days=rc.HORIZON_DAYS)).isoformat()
        self.assertTrue(all(f"startDateTime=2026-10-26T00" in u and f"endDateTime={end}T" in u for u in calls))


HARD_NAMES = [
    "Tyler, The Creator “CHROMAKOPIA” Tour",
    "Dawes, Live: An Evening",
    "Back\\slash Act",
    "O'Rourke & Sons: {Brackets}, [Lists] // not a comment",
    "Señor Coconut – Ümlaut Tour",
]


class TestParserRoundTrip(unittest.TestCase):
    def test_e0_hard_names_round_trip(self):
        rows = [{"date": "2026-11-01", "name": n, "venue": "The Wiltern", "genre": "Rock", "support": "",
                 "spotifyMonthlyListeners": 0, "ticketUrl": "https://x/y?a=1&b=2", "ticketVendor": "Ticketmaster",
                 "onSaleDate": "", "presaleDate": "", "tmId": f"id{i}", "artists": [n], "firstSeen": "2026-10-26"}
                for i, n in enumerate(HARD_NAMES)]
        js = "[\n" + "\n".join(rc.render_row(r) for r in rows) + "\n]"
        parsed = wd._js_array_to_python(js)
        self.assertEqual(parsed, rows)

    def test_e0_legacy_style_still_parses(self):
        js = "[\n  // ── APRIL 2026 ──\n  { date: '2026-04-01', name: 'Aries', venue: 'The Fonda Theatre', genre: 'Pop', support: \"Tiffany Day\", spotifyMonthlyListeners: 3400000, ticketUrl: 'https://www.ticketmaster.com/search?q=aries', ticketVendor: 'Ticketmaster', onSaleDate: '', presaleDate: '' },\n]"
        parsed = wd._js_array_to_python(js)
        self.assertEqual(parsed[0]["name"], "Aries")
        self.assertEqual(parsed[0]["ticketUrl"], "https://www.ticketmaster.com/search?q=aries")


def row(date_: str, name: str, venue: str, **extra) -> dict:
    base = {"date": date_, "name": name, "venue": venue, "genre": "Rock", "support": "",
            "spotifyMonthlyListeners": 0, "ticketUrl": "", "ticketVendor": "", "onSaleDate": "", "presaleDate": ""}
    base.update(extra)
    return base


class TestMergeRows(unittest.TestCase):
    def setUp(self):
        self.past = [row("2026-04-01", "Aries", "The Fonda Theatre"),
                     row("2026-06-02", "Old Show", "Kia Forum", tmId="OLD1", artists=["Old Show"], firstSeen="2026-05-01"),
                     row("2026-10-25", "Yesterday", "The Wiltern")]
        self.ghost = row("2026-11-14", "Tame Impala", "Kia Forum")  # no tmId
        self.known = row("2026-12-01", "Kept Band", "Kia Forum", tmId="K1", artists=["Kept Band"], firstSeen="2026-09-01")
        self.fonda_future = row("2026-11-30", "Fonda Act", "The Fonda Theatre")
        self.existing = self.past + [self.ghost, self.known, self.fonda_future]

    def test_e6_past_rows_preserved(self):
        out = rc.merge_rows(self.existing, {"Kia Forum": [], "The Fonda Theatre": []}, set(), set(), TODAY)
        self.assertEqual(out[:3], self.past)

    def test_e7_ghost_row_dropped(self):
        out = rc.merge_rows(self.existing, {"Kia Forum": [], "The Fonda Theatre": []}, set(), set(), TODAY)
        self.assertNotIn("Tame Impala", [r["name"] for r in out])

    def test_e8_first_seen_carried_or_set(self):
        fetched_known = row("2026-12-01", "Kept Band", "Kia Forum", tmId="K1", artists=["Kept Band"], firstSeen=TODAY.isoformat())
        fetched_new = row("2026-12-05", "New Band", "Kia Forum", tmId="N1", artists=["New Band"], firstSeen=TODAY.isoformat())
        out = rc.merge_rows(self.existing, {"Kia Forum": [fetched_known, fetched_new], "The Fonda Theatre": []}, set(), set(), TODAY)
        by_id = {r.get("tmId"): r for r in out if r.get("tmId")}
        self.assertEqual(by_id["K1"]["firstSeen"], "2026-09-01")
        self.assertEqual(by_id["N1"]["firstSeen"], "2026-10-26")

    def test_e9_failed_venue_keeps_future_rows(self):
        out = rc.merge_rows(self.existing, {"Kia Forum": []}, failed={"The Fonda Theatre"}, uncovered=set(), today=TODAY)
        self.assertIn(self.fonda_future, out)
        self.assertNotIn(self.known, out)  # Kia Forum was fetched (empty) so its future rows are replaced

    def test_e9b_uncovered_venue_keeps_future_rows(self):
        out = rc.merge_rows(self.existing, {"Kia Forum": []}, failed=set(), uncovered={"The Fonda Theatre"}, today=TODAY)
        self.assertIn(self.fonda_future, out)

    def test_e10_sorted(self):
        a = row("2026-12-05", "b band", "Kia Forum", tmId="A", artists=[], firstSeen="2026-10-26")
        b = row("2026-12-05", "A band", "Kia Forum", tmId="B", artists=[], firstSeen="2026-10-26")
        out = rc.merge_rows(self.existing, {"Kia Forum": [a, b], "The Fonda Theatre": []}, set(), set(), TODAY)
        self.assertEqual([r["date"] for r in out], sorted(r["date"] for r in out))
        tail = [r["name"] for r in out if r["date"] == "2026-12-05"]
        self.assertEqual(tail, ["A band", "b band"])


if __name__ == "__main__":
    unittest.main()
