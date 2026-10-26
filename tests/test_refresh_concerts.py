#!/usr/bin/env python3
"""Tests for scripts/refresh_concerts.py. Zero network: every HTTP call is injected."""
from __future__ import annotations

import contextlib
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


class TestRunEndToEnd(unittest.TestCase):
    """Drives run() against a copy of mini_index_feed.html with a fake HTTP layer."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.index = self.tmp / "index.html"
        shutil.copy(FEED_FIXTURE, self.index)
        self.venues = ROOT / "scripts" / "venues.json"
        self.state = self.tmp / "refresh_state.json"
        self.before = self.index.read_bytes()
        self.n_past = sum(1 for c in wd.load_data(FEED_FIXTURE)[0] if c["date"] < TODAY.isoformat())
        self.calls = 0

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def good_http(self, n_per_venue: int = 12, empty_venue_ids: set[str] = frozenset(), spread: int = 7):
        """Every venue id returns n distinct future music events on one page (0 for ids in empty_venue_ids)."""
        def http(url: str) -> dict:
            self.calls += 1
            vid = url.split("venueId=")[1].split("&")[0]
            n = 0 if vid in empty_venue_ids else n_per_venue
            evs = []
            for i in range(n):
                d = date.fromordinal(TODAY.toordinal() + 30 + spread * i)  # n=12 reaches +107 days, past the 60-day liveness horizon; n=1 stays at +30 and trips it (E17)
                evs.append({"name": f"Act {vid} {i}", "id": f"{vid}-{i}", "url": f"https://tm/{vid}/{i}",
                            "dates": {"start": {"localDate": d.isoformat(), "dateTBD": False, "dateTBA": False}, "status": {"code": "onsale"}},
                            "sales": {"public": {"startDateTime": "2026-10-01T17:00:00Z"}},
                            "classifications": [{"segment": {"name": "Music"}, "genre": {"name": "Rock"}}],
                            "_embedded": {"venues": [{"id": vid}], "attractions": [{"name": f"Act {vid} {i}"}]}})
            return {"_embedded": {"events": evs}, "page": {"totalPages": 1}}
        return http

    def run_quiet(self, *args, **kwargs):
        import io
        with contextlib.redirect_stderr(io.StringIO()), contextlib.redirect_stdout(io.StringIO()):
            return rc.run(*args, **kwargs)

    def test_e11_thin_feed_writes_nothing(self):
        self.state.write_text(json.dumps({"future_rows": 400, "last_success_at": "2026-10-19T09:00:00-07:00"}))
        code, summary = self.run_quiet(self.index, self.venues, self.state, "KEY", TODAY, NOW, http=self.good_http(2))
        self.assertEqual(code, 5)
        self.assertEqual(self.index.read_bytes(), self.before)
        st = json.loads(self.state.read_text())
        self.assertEqual(st["last_attempt_status"], "thin_feed")
        self.assertEqual(st["last_success_at"], "2026-10-19T09:00:00-07:00")

    def test_e12_all_failed_writes_nothing(self):
        def boom(url: str) -> dict:
            raise RuntimeError("down")
        code, summary = self.run_quiet(self.index, self.venues, self.state, "KEY", TODAY, NOW, http=boom)
        self.assertEqual(code, 4)
        self.assertEqual(self.index.read_bytes(), self.before)
        self.assertEqual(json.loads(self.state.read_text())["last_attempt_status"], "all_failed")

    def test_e12b_zero_rows_with_existing_future_rows_counts_as_failed_every_run(self):
        fixture_future_kia = [c for c in wd.load_data(FEED_FIXTURE)[0] if c["venue"] == "Kia Forum" and c["date"] >= TODAY.isoformat()]
        self.assertTrue(fixture_future_kia, "fixture must hold the Tame Impala ghost at Kia Forum")
        for run_no in (1, 2):  # no state on run 1; run 2 sees run 1's state with per_venue["Kia Forum"] == 0
            code, summary = self.run_quiet(self.index, self.venues, self.state, "KEY", TODAY, NOW,
                                           http=self.good_http(12, empty_venue_ids={"KovZpZAEkn6A"}))
            self.assertEqual(code, 0, (run_no, summary))
            self.assertEqual(summary["failed_venues"], ["Kia Forum (zero_rows)"], run_no)
            self.assertIn("Tame Impala", self.index.read_text(), run_no)  # kept both times
            self.assertEqual(json.loads(self.state.read_text())["failed_venues"], ["Kia Forum (zero_rows)"], run_no)

    def test_e12c_zero_rows_with_no_existing_future_rows_is_fine(self):
        # The Fonda has no future rows in the fixture, so an empty feed for it is a legitimate quiet calendar.
        code, summary = self.run_quiet(self.index, self.venues, self.state, "KEY", TODAY, NOW,
                                       http=self.good_http(12, empty_venue_ids={"KovZpZAFAkIA"}))
        self.assertEqual(code, 0, summary)
        self.assertEqual(summary["failed_venues"], [])
        self.assertEqual(summary["per_venue"]["The Fonda Theatre"], 0)

    def test_e11b_accept_thin_overrides_guard_once(self):
        self.state.write_text(json.dumps({"future_rows": 400, "last_success_at": "2026-10-19T09:00:00-07:00"}))
        # spread=40 puts the second event at +70 days so the liveness horizon passes; only the thin-feed guard is under test here
        code, summary = self.run_quiet(self.index, self.venues, self.state, "KEY", TODAY, NOW, http=self.good_http(2, spread=40), accept_thin=True)
        self.assertEqual(code, 0, summary)
        self.assertEqual(json.loads(self.state.read_text())["future_rows"], 40)

    def test_e13_missing_key_exits_3_before_fetch(self):
        code, summary = self.run_quiet(self.index, self.venues, self.state, "", TODAY, NOW, http=self.good_http())
        self.assertEqual(code, 3)
        self.assertEqual(self.calls, 0)

    def test_e14_round_trip_and_outside_bytes_identical(self):
        code, summary = self.run_quiet(self.index, self.venues, self.state, "KEY", TODAY, NOW, http=self.good_http(12))
        self.assertEqual(code, 0, summary)
        concerts, _ = wd.load_data(self.index)
        self.assertEqual(len(concerts), self.n_past + 12 * 20)  # 20 TM ids across 19 venues: Shrine has two
        before, after = self.before.decode(), self.index.read_text()
        self.assertEqual(before.split("const CONCERTS = [")[0].split("<!--LAST_REFRESH:START-->")[0],
                         after.split("const CONCERTS = [")[0].split("<!--LAST_REFRESH:START-->")[0])
        self.assertEqual(before.split("<!--LAST_REFRESH:END-->")[1].split("const CONCERTS = [")[0],
                         after.split("<!--LAST_REFRESH:END-->")[1].split("const CONCERTS = [")[0])
        self.assertEqual(before.split("const WISHLIST_ARTISTS")[1], after.split("const WISHLIST_ARTISTS")[1])
        self.assertNotIn("Tame Impala", after)
        self.assertFalse(list(self.tmp.glob("*.tmp")), "verify temp file must be removed")

    def test_e15_stamp_text(self):
        self.assertEqual(rc.stamp_text(TODAY, 212, 19), "Data refreshed: October 26, 2026 &bull; 212 upcoming shows across 19 venues")
        self.run_quiet(self.index, self.venues, self.state, "KEY", TODAY, NOW, http=self.good_http(12))
        after = self.index.read_text()
        inner = after.split("<!--LAST_REFRESH:START-->")[1].split("<!--LAST_REFRESH:END-->")[0]
        self.assertEqual(inner, rc.stamp_text(TODAY, 240, 19))

    def test_e16_state_on_success_preserves_foreign_keys(self):
        foreign = {"last_digest_at": "2026-10-19T09:10:00-07:00", "last_digest_covered_through": "2026-10-19T09:05:00-07:00",
                   "last_tests_status": "ok", "last_push_status": "ok", "last_refresh_rc": "0"}
        self.state.write_text(json.dumps(foreign))
        code, summary = self.run_quiet(self.index, self.venues, self.state, "KEY", TODAY, NOW, http=self.good_http(12))
        st = json.loads(self.state.read_text())
        self.assertEqual(st["last_attempt_status"], "ok")
        self.assertEqual(st["last_success_at"], NOW.isoformat(timespec="seconds"))
        self.assertEqual(st["last_attempt_at"], NOW.isoformat(timespec="seconds"))
        self.assertEqual(st["future_rows"], 240)
        self.assertEqual(len(st["per_venue"]), 19)
        self.assertEqual(st["failed_venues"], [])
        self.assertIn("venue_seen", summary)
        for k, v in foreign.items():
            self.assertEqual(st[k], v, k)

    def test_e17_liveness_floor_fails_loud_after_write(self):
        code, summary = self.run_quiet(self.index, self.venues, self.state, "KEY", TODAY, NOW, http=self.good_http(1))
        # 20 future rows total, newest date only 30 days out → liveness fails, data still written
        self.assertEqual(code, 1)
        self.assertNotEqual(self.index.read_bytes(), self.before)
        self.assertEqual(json.loads(self.state.read_text())["last_attempt_status"], "liveness_failed")

    def test_e14b_parse_failure_is_exit_2_not_systemexit(self):
        self.index.write_text(self.before.decode().replace("const CONCERTS = [", "const CONCERTS = [ {broken", 1))
        code, summary = self.run_quiet(self.index, self.venues, self.state, "KEY", TODAY, NOW, http=self.good_http(12))
        self.assertEqual(code, 2)
        self.assertEqual(json.loads(self.state.read_text())["last_attempt_status"], "parse")


if __name__ == "__main__":
    unittest.main()
