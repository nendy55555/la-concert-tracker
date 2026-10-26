#!/usr/bin/env python3
"""
test_weekly_digest.py — unit + integration tests for the hardened digest pipeline.

Runs on Python 3.11+ stdlib only (unittest). Zero Claude API calls. Zero
network. Zero third-party deps.

Run:
    python3 -m unittest tests.test_weekly_digest -v
    # or
    python3 tests/test_weekly_digest.py
"""

from __future__ import annotations

import json
import sys
import unittest
from datetime import date
from pathlib import Path

# Make scripts/ importable
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import weekly_digest as wd  # noqa: E402


# ─── Fixtures ────────────────────────────────────────────────────────────────

FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures"

MINI_INDEX_HTML = """<!DOCTYPE html>
<html><head></head><body>
<script>
// ── CONCERT DATA ──
const CONCERTS = [
  { date: '2026-04-25', name: 'Jack Harlow', venue: 'The Wiltern', genre: 'Hip-Hop/R&B', support: '', spotifyMonthlyListeners: 22000000, ticketUrl: 'https://www.ticketmaster.com/jack', ticketVendor: 'Ticketmaster', onSaleDate: '2026-04-22T10:00', presaleDate: '2026-04-20T10:00' },
  { date: '2026-05-02', name: "Barry Can't Swim", venue: 'Academy LA', genre: 'Electronic/EDM', support: '', spotifyMonthlyListeners: 3000000, ticketUrl: '', ticketVendor: '', onSaleDate: '', presaleDate: '' },
  { date: '2026-06-15', name: 'Kendrick Lamar', venue: 'SoFi Stadium', genre: 'Hip-Hop/R&B', support: 'SZA', spotifyMonthlyListeners: 80000000, ticketUrl: 'https://www.ticketmaster.com/k', ticketVendor: 'Ticketmaster', onSaleDate: '', presaleDate: '' },
  { date: '2026-04-10', name: 'Past Show', venue: 'Troubadour', genre: 'Rock', support: '', spotifyMonthlyListeners: 0, ticketUrl: '', ticketVendor: '', onSaleDate: '', presaleDate: '' },
  { date: '2026-04-22', name: 'Random Artist', venue: 'The Roxy Theatre', genre: 'Pop', support: '', spotifyMonthlyListeners: 100000, ticketUrl: '', ticketVendor: '', onSaleDate: '2026-04-28T12:00', presaleDate: '' },
];
const WISHLIST_ARTISTS = [
  'Jack Harlow',"Barry Can't Swim",'Kendrick Lamar','JCole',
];
</script>
</body></html>
"""


# ─── Parser tests ────────────────────────────────────────────────────────────


class TestParser(unittest.TestCase):
    def test_mini_fixture_parses(self):
        fx = FIXTURE_DIR / "mini_index.html"
        fx.parent.mkdir(parents=True, exist_ok=True)
        fx.write_text(MINI_INDEX_HTML, encoding="utf-8")
        concerts, wishlist = wd.load_data(fx)
        self.assertEqual(len(concerts), 5)
        self.assertEqual(len(wishlist), 4)
        self.assertEqual(wishlist, ["Jack Harlow", "Barry Can't Swim", "Kendrick Lamar", "JCole"])

    def test_parser_does_not_strip_urls(self):
        # Regression: `//` inside strings used to be stripped as a comment.
        fx = FIXTURE_DIR / "mini_index.html"
        concerts, _ = wd.load_data(fx)
        jack = [c for c in concerts if c["name"] == "Jack Harlow"][0]
        self.assertIn("ticketmaster.com", jack["ticketUrl"])
        self.assertTrue(jack["ticketUrl"].startswith("https://"))

    def test_parser_handles_apostrophes(self):
        fx = FIXTURE_DIR / "mini_index.html"
        concerts, _ = wd.load_data(fx)
        barry = [c for c in concerts if "Barry" in c["name"]][0]
        self.assertEqual(barry["name"], "Barry Can't Swim")

    def test_parser_handles_real_index(self):
        real = ROOT / "index.html"
        if not real.exists():
            self.skipTest("real index.html not found")
        concerts, wishlist = wd.load_data(real)
        # Sanity: production data should have lots of concerts and the original wishlist
        self.assertGreater(len(concerts), 300)
        self.assertGreater(len(wishlist), 20)
        # Every concert has at minimum a date and name
        for c in concerts:
            self.assertIn("date", c)
            self.assertIn("name", c)
            self.assertRegex(c["date"], r"^\d{4}-\d{2}-\d{2}$")


# ─── Normalizer / fuzzy matcher tests ────────────────────────────────────────


class TestNormalizer(unittest.TestCase):
    def test_normalize_strips_whitespace_and_punct(self):
        self.assertEqual(wd.normalize_for_match("J. Cole"), "jcole")
        self.assertEqual(wd.normalize_for_match("Barry Can't Swim"), "barrycantswim")
        self.assertEqual(wd.normalize_for_match("A$AP Rocky"), "aaprocky")

    def test_normalize_empty(self):
        self.assertEqual(wd.normalize_for_match(""), "")
        self.assertEqual(wd.normalize_for_match("   .."), "")

    def test_watch_match_direct(self):
        wl = [wd.normalize_for_match("Jack Harlow")]
        self.assertTrue(wd.is_watched_artist("Jack Harlow", wl))

    def test_watch_match_substring_either_direction(self):
        # Substring either direction — per index.html's fuzzy matcher.
        wl_short = [wd.normalize_for_match("Jungle")]
        self.assertTrue(wd.is_watched_artist("Jungle (UK)", wl_short))  # wishlist ⊂ concert
        wl_long = [wd.normalize_for_match("Fred Again..")]
        self.assertTrue(wd.is_watched_artist("Fred Again", wl_long))  # concert ⊂ wishlist

    def test_watch_match_jcole_variants(self):
        # Wishlist has 'JCole' (no dot/space). Concert is 'J. Cole'.
        wl = [wd.normalize_for_match("JCole")]
        self.assertTrue(wd.is_watched_artist("J. Cole", wl))
        self.assertTrue(wd.is_watched_artist("J Cole", wl))

    def test_no_false_positive_dave_vs_david(self):
        # Wishlist has 'Dave' (British rapper). Normalized: 'dave'.
        # 'David Bowie' normalizes to 'davidbowie' — 'dave' is NOT a substring of 'davidbowie'
        # (the sequence is d-a-v-i-d, not d-a-v-e). Confirms we don't get cross-name bleed.
        wl = [wd.normalize_for_match("Dave")]
        self.assertFalse(wd.is_watched_artist("David Bowie", wl))
        # But the legitimate match still works
        self.assertTrue(wd.is_watched_artist("Dave", wl))

    def test_empty_wishlist_no_match(self):
        self.assertFalse(wd.is_watched_artist("Any Artist", []))


# ─── Date helper tests ───────────────────────────────────────────────────────


class TestDates(unittest.TestCase):
    def test_parse_sale_date_datetime_form(self):
        dt = wd.parse_sale_date("2026-05-10T14:30")
        self.assertIsNotNone(dt)
        self.assertEqual(dt.year, 2026)
        self.assertEqual(dt.hour, 14)

    def test_parse_sale_date_date_only(self):
        dt = wd.parse_sale_date("2026-05-10")
        self.assertIsNotNone(dt)
        self.assertEqual(dt.date().isoformat(), "2026-05-10")

    def test_parse_sale_date_empty(self):
        self.assertIsNone(wd.parse_sale_date(""))
        self.assertIsNone(wd.parse_sale_date("not-a-date"))


# ─── Digest building tests ──────────────────────────────────────────────────


class TestBuildDigest(unittest.TestCase):
    def setUp(self):
        fx = FIXTURE_DIR / "mini_index.html"
        fx.parent.mkdir(parents=True, exist_ok=True)
        fx.write_text(MINI_INDEX_HTML, encoding="utf-8")
        self.concerts, self.wishlist = wd.load_data(fx)

    def test_builds_watch_hits_for_upcoming(self):
        d = wd.build_digest(self.concerts, self.wishlist, date(2026, 4, 20), 180, 14)
        names = {h["name"] for h in d["watch_hits"]}
        # Jack Harlow is on 4/25 → in horizon. Past Show is before today → excluded.
        self.assertIn("Jack Harlow", names)
        self.assertIn("Barry Can't Swim", names)
        self.assertIn("Kendrick Lamar", names)
        self.assertNotIn("Past Show", names)

    def test_excludes_past_shows(self):
        d = wd.build_digest(self.concerts, self.wishlist, date(2026, 4, 20), 180, 14)
        for h in d["watch_hits"]:
            self.assertGreaterEqual(h["date"], "2026-04-20")

    def test_horizon_clips(self):
        d = wd.build_digest(self.concerts, self.wishlist, date(2026, 4, 20), 7, 14)
        # Only Jack Harlow (4/25) fits in a 7-day window.
        names = {h["name"] for h in d["watch_hits"]}
        self.assertEqual(names, {"Jack Harlow"})

    def test_onsale_hits_in_window(self):
        d = wd.build_digest(self.concerts, self.wishlist, date(2026, 4, 20), 180, 14)
        # Jack Harlow: presale 4/20 (today), on-sale 4/22 — both in window. Random Artist: on-sale 4/28 — in window.
        kinds = sorted([(h["name"], h["sale_kind"]) for h in d["onsale_hits"]])
        self.assertIn(("Jack Harlow", "presale"), kinds)
        self.assertIn(("Jack Harlow", "onsale"), kinds)
        self.assertIn(("Random Artist", "onsale"), kinds)

    def test_onsale_window_excludes_far_future(self):
        d = wd.build_digest(self.concerts, self.wishlist, date(2026, 4, 20), 180, 1)
        # onsale_days=1 → only events with sale date today or tomorrow
        for h in d["onsale_hits"]:
            self.assertLessEqual(h["days_until"], 1)

    def test_onsale_hits_flag_watched(self):
        d = wd.build_digest(self.concerts, self.wishlist, date(2026, 4, 20), 180, 14)
        jack_hits = [h for h in d["onsale_hits"] if h["name"] == "Jack Harlow"]
        self.assertTrue(all(h["is_watched"] for h in jack_hits))
        rnd_hits = [h for h in d["onsale_hits"] if h["name"] == "Random Artist"]
        self.assertTrue(all(not h["is_watched"] for h in rnd_hits))

    def test_per_artist_roster_includes_every_wishlist_name(self):
        d = wd.build_digest(self.concerts, self.wishlist, date(2026, 4, 20), 180, 14)
        self.assertEqual(set(d["per_artist"].keys()), set(self.wishlist))

    def test_totals_consistent(self):
        d = wd.build_digest(self.concerts, self.wishlist, date(2026, 4, 20), 180, 14)
        self.assertEqual(d["totals"]["concerts"], len(self.concerts))
        self.assertEqual(d["totals"]["watchlist_artists"], len(self.wishlist))
        self.assertEqual(d["totals"]["watch_hits"], len(d["watch_hits"]))
        self.assertEqual(d["totals"]["onsale_hits"], len(d["onsale_hits"]))


# ─── Renderer tests ─────────────────────────────────────────────────────────


class TestRenderers(unittest.TestCase):
    def setUp(self):
        fx = FIXTURE_DIR / "mini_index.html"
        fx.parent.mkdir(parents=True, exist_ok=True)
        fx.write_text(MINI_INDEX_HTML, encoding="utf-8")
        self.concerts, self.wishlist = wd.load_data(fx)
        self.digest = wd.build_digest(self.concerts, self.wishlist, date(2026, 4, 20), 180, 14)

    def test_text_contains_expected_sections(self):
        txt = wd.render_text(self.digest)
        self.assertIn("WATCHLIST", txt)
        self.assertIn("ON-SALE DROPS", txt)
        self.assertIn("FULL WATCHLIST ROSTER", txt)
        self.assertIn("Jack Harlow", txt)

    def test_html_escapes_content(self):
        # Insert an artist with an HTML-injection attempt.
        self.digest["watch_hits"].append(
            {
                "watchlist_artist": "Evil",
                "name": "<script>alert(1)</script>",
                "date": "2026-05-01",
                "venue": "Nowhere",
                "genre": "Pop",
                "support": "",
                "ticket_url": "",
                "ticket_vendor": "",
                "on_sale_date": "",
                "presale_date": "",
                "days_until": 11,
            }
        )
        html = wd.render_html(self.digest)
        # The raw <script> tag should not appear un-escaped inside the body.
        self.assertNotIn("<script>alert(1)</script>", html)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", html)

    def test_html_self_contained(self):
        html = wd.render_html(self.digest)
        self.assertTrue(html.startswith("<!DOCTYPE html>"))
        self.assertIn("</html>", html)
        self.assertIn("<style>", html)  # inline styles for email clients

    def test_text_empty_sections_graceful(self):
        # No watchlist matches in a narrow window.
        d = wd.build_digest(self.concerts, self.wishlist, date(2026, 4, 20), 1, 0)
        txt = wd.render_text(d)
        self.assertIn("None in the horizon window.", txt)
        html = wd.render_html(d)
        self.assertIn("None in the horizon window.", html)


# ─── Smoke / pipeline test ──────────────────────────────────────────────────


class TestPipeline(unittest.TestCase):
    def test_main_runs_on_real_index(self):
        real = ROOT / "index.html"
        if not real.exists():
            self.skipTest("real index.html not found")
        out_dir = ROOT / "tests" / "_smoke_dist"
        out_dir.mkdir(parents=True, exist_ok=True)
        rc = wd.main(
            [
                "--index",
                str(real),
                "--as-of",
                "2026-04-20",
                "--horizon-days",
                "300",
                "--onsale-days",
                "14",
                "--out-dir",
                str(out_dir),
            ]
        )
        self.assertEqual(rc, 0)
        self.assertTrue((out_dir / "weekly_digest.html").exists())
        self.assertTrue((out_dir / "weekly_digest.txt").exists())
        self.assertTrue((out_dir / "weekly_digest.json").exists())
        data = json.loads((out_dir / "weekly_digest.json").read_text())
        # At horizon=300 the full historical-match set (5 shows) should appear.
        self.assertGreaterEqual(data["totals"]["watch_hits"], 4)
        # HTML body has at least one of the expected watchlist names.
        html = (out_dir / "weekly_digest.html").read_text()
        self.assertTrue(
            any(n in html for n in ("J. Cole", "Jack Harlow", "JUNGLE", "Tame Impala"))
        )


# ─── Email tests (mocked SMTP) ──────────────────────────────────────────────


class _MockSMTP:
    """Minimal SMTP stand-in for testing send_via_smtp without network."""

    instances: list["_MockSMTP"] = []

    def __init__(self, host, port):
        self.host = host
        self.port = port
        self.logged_in_as = None
        self.sent_messages = []
        _MockSMTP.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def login(self, user, password):
        self.logged_in_as = (user, password)

    def send_message(self, msg):
        self.sent_messages.append(msg)


class TestEmail(unittest.TestCase):
    def setUp(self):
        _MockSMTP.instances = []

    def test_build_email_message_has_html_and_text(self):
        msg = wd.build_email_message(
            "from@example.com",
            "to@example.com",
            "Subject Line",
            "<p>Hi</p>",
            "Hi",
        )
        self.assertEqual(msg["From"], "from@example.com")
        self.assertEqual(msg["To"], "to@example.com")
        self.assertEqual(msg["Subject"], "Subject Line")
        self.assertTrue(msg.is_multipart())
        parts = list(msg.iter_parts())
        types = sorted(p.get_content_type() for p in parts)
        self.assertEqual(types, ["text/html", "text/plain"])

    def test_send_via_smtp_uses_factory(self):
        msg = wd.build_email_message("a@b.com", "c@d.com", "S", "<i>x</i>", "x")
        wd.send_via_smtp(
            msg,
            sender="a@b.com",
            app_password="abcd1234",
            smtp_factory=_MockSMTP,
        )
        self.assertEqual(len(_MockSMTP.instances), 1)
        smtp = _MockSMTP.instances[0]
        self.assertEqual(smtp.host, "smtp.gmail.com")
        self.assertEqual(smtp.port, 465)
        self.assertEqual(smtp.logged_in_as, ("a@b.com", "abcd1234"))
        self.assertEqual(len(smtp.sent_messages), 1)
        self.assertEqual(smtp.sent_messages[0]["Subject"], "S")

    def test_load_env_file_parses_basic_kv(self):
        import os
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            env_path = Path(td) / ".env"
            env_path.write_text(
                "# comment\n"
                "FOO=bar\n"
                'QUOTED="hello world"\n'
                "BLANK=\n"
                "\n",
                encoding="utf-8",
            )
            # Clear any leftovers
            for k in ("FOO", "QUOTED", "BLANK"):
                os.environ.pop(k, None)
            wd.load_env_file(env_path)
            self.assertEqual(os.environ.get("FOO"), "bar")
            self.assertEqual(os.environ.get("QUOTED"), "hello world")
            # Cleanup
            for k in ("FOO", "QUOTED", "BLANK"):
                os.environ.pop(k, None)

    def test_load_env_file_does_not_overwrite(self):
        import os
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            env_path = Path(td) / ".env"
            env_path.write_text("ALREADY_SET=fromfile\n", encoding="utf-8")
            os.environ["ALREADY_SET"] = "fromenv"
            wd.load_env_file(env_path)
            self.assertEqual(os.environ.get("ALREADY_SET"), "fromenv")
            os.environ.pop("ALREADY_SET", None)

    def test_main_email_flag_missing_creds_returns_4(self):
        import os

        # Ensure no .env interference: write fixture and point at a temp out dir.
        fx = FIXTURE_DIR / "mini_index.html"
        fx.parent.mkdir(parents=True, exist_ok=True)
        fx.write_text(MINI_INDEX_HTML, encoding="utf-8")
        # Strip env vars so the missing-creds branch fires.
        saved = {
            k: os.environ.pop(k, None)
            for k in ("GMAIL_SENDER", "GMAIL_APP_PASSWORD", "EMAIL_TO")
        }
        try:
            rc = wd.main(
                [
                    "--index",
                    str(fx),
                    "--as-of",
                    "2026-04-20",
                    "--horizon-days",
                    "30",
                    "--onsale-days",
                    "14",
                    "--out-dir",
                    str(FIXTURE_DIR / "_email_dist"),
                    "--email",
                ]
            )
            self.assertEqual(rc, 4)
        finally:
            for k, v in saved.items():
                if v is not None:
                    os.environ[k] = v


class TestMatcherPrecision(unittest.TestCase):
    def setUp(self):
        self.cases = json.loads((FIXTURE_DIR / "matcher_cases.json").read_text())

    def test_e18_e19_shared_cases(self):
        for c in self.cases:
            wl = [wd.normalize_for_match(c["watch"])]
            got = wd.is_watched_artist(c["name"], wl, artists=c["artists"])
            self.assertEqual(got, c["expect"], c)
            names = wd.matched_watchlist_names(c["name"], [c["watch"]], artists=c["artists"])
            self.assertEqual(bool(names), c["expect"], c)

    def test_roster_agrees_with_watchlist_section_for_every_matched_artist(self):
        concerts = [{"date": "2026-12-01", "name": "Empire of the Sun", "venue": "Hollywood Bowl", "genre": "Pop",
                     "support": "Polo & Pan", "spotifyMonthlyListeners": 0, "ticketUrl": "", "ticketVendor": "",
                     "onSaleDate": "", "presaleDate": "", "tmId": "X", "artists": ["Empire of the Sun", "Polo & Pan"],
                     "firstSeen": "2026-10-01T09:00:00-07:00"}]
        d = wd.build_digest(concerts, ["Polo & Pan", "Empire of the Sun", "Flume"], date(2026, 10, 26), 180, 14)
        self.assertEqual(len(d["watch_hits"]), 1)  # one show, deduplicated
        # per_artist lists every wishlist artist; unmatched ones map to an empty list
        self.assertTrue(d["per_artist"]["Polo & Pan"])
        self.assertTrue(d["per_artist"]["Empire of the Sun"])
        self.assertEqual(d["per_artist"]["Flume"], [])
        self.assertEqual(d["totals"]["artists_with_shows"], 2)


TIERS = {"Kia Forum": 3, "SoFi Stadium": 4, "The Wiltern": 2, "Troubadour": 1, "Academy LA": 2}


def feed_row(date_, name, venue, first_seen, on_sale="", artists=None):
    return {"date": date_, "name": name, "venue": venue, "genre": "Rock", "support": "",
            "spotifyMonthlyListeners": 0, "ticketUrl": "", "ticketVendor": "", "onSaleDate": on_sale,
            "presaleDate": "", "tmId": name.replace(" ", ""), "artists": artists if artists is not None else [name],
            "firstSeen": first_seen}


class TestNewSinceAndFeedLine(unittest.TestCase):
    TODAY = date(2026, 10, 26)
    COVERED = "2026-10-19T09:05:00-07:00"
    STATE = {"last_success_at": "2026-10-25T09:05:00-07:00", "last_attempt_at": "2026-10-25T09:05:00-07:00",
             "last_attempt_status": "ok", "future_rows": 212, "failed_venues": [],
             "last_digest_at": "2026-10-19T09:10:00-07:00", "last_digest_covered_through": COVERED,
             "last_tests_status": "ok", "last_push_status": "ok", "last_refresh_rc": "0"}

    def rows(self):
        return [
            feed_row("2026-12-01", "Flume", "Kia Forum", "2026-10-20T09:05:00-07:00"),                 # watchlist, new
            feed_row("2026-12-03", "Big Arena Act", "SoFi Stadium", "2026-10-23T09:05:00-07:00"),      # tier 4, new, not watchlist
            feed_row("2026-12-05", "Jungle", "The Wiltern", "2026-10-10T09:05:00-07:00"),               # watchlist, old
            feed_row("2026-12-07", "Small Club Act", "Troubadour", "2026-10-24T09:05:00-07:00"),       # tier 1, new, not notable
            feed_row("2026-12-09", "Same Day Later", "Kia Forum", "2026-10-19T15:30:00-07:00"),        # refreshed by hand after last digest: new
            feed_row("2027-01-10", "Odesza", "Kia Forum", "2026-09-01T09:05:00-07:00", on_sale="2026-10-22T10:00"),  # new on-sale
            feed_row("2027-01-12", "Moby", "The Wiltern", "2026-09-01T09:05:00-07:00", on_sale="2026-10-01T10:00"),  # old on-sale
        ]

    def digest(self, state, rows=None):
        return wd.build_digest(rows if rows is not None else self.rows(), ["Flume", "Jungle", "Odesza", "Moby"],
                               self.TODAY, 180, 14, state=state, tiers=TIERS)

    def test_e21_new_since_lists_new_rows_watchlist_first(self):
        d = self.digest(self.STATE)
        names = [s["name"] for s in d["new_since"]["shows"]]
        self.assertEqual(names, ["Flume", "Big Arena Act", "Same Day Later"])
        text = wd.render_text(d)
        self.assertIn("── NEW SINCE Oct 19 ──", text)
        self.assertNotIn("Small Club Act", text.split("── WATCHLIST")[0])

    def test_e22_new_onsales(self):
        d = self.digest(self.STATE)
        self.assertEqual([s["name"] for s in d["new_since"]["onsales"]], ["Odesza"])

    def test_e23_section_omitted_when_empty(self):
        rows = [feed_row("2026-12-05", "Jungle", "The Wiltern", "2026-10-10T09:05:00-07:00")]
        text = wd.render_text(self.digest(self.STATE, rows))
        self.assertNotIn("NEW SINCE", text)

    def test_e24_feed_line(self):
        d = self.digest(self.STATE)
        self.assertEqual(d["feed"]["age_days"], 1)
        self.assertIn("Data refreshed 1 day ago", d["feed"]["line"])
        stale = dict(self.STATE, last_success_at="2026-10-16T09:05:00-07:00", last_attempt_at="2026-10-16T09:05:00-07:00")
        self.assertIn("STALE", self.digest(stale)["feed"]["line"])
        failed = dict(self.STATE, last_attempt_at="2026-10-26T09:05:00-07:00", last_attempt_status="all_failed")
        self.assertIn("last refresh attempt failed", self.digest(failed)["feed"]["line"])
        partial = dict(self.STATE, failed_venues=["The Fonda Theatre (fetch)", "Kia Forum (zero_rows)"])
        self.assertIn("The Fonda Theatre (fetch)", self.digest(partial)["feed"]["line"])
        tests_failed = dict(self.STATE, last_tests_status="tests_failed")
        self.assertIn("tests failed", self.digest(tests_failed)["feed"]["line"])
        push_failed = dict(self.STATE, last_push_status="failed")
        self.assertIn("site push failed", self.digest(push_failed)["feed"]["line"])
        crashed = dict(self.STATE, last_refresh_rc="1")
        self.assertIn("refresh exited 1", self.digest(crashed)["feed"]["line"])
        no_attempt = dict(self.STATE, last_attempt_at="2026-10-18T09:05:00-07:00", last_success_at="2026-10-18T09:05:00-07:00")
        self.assertIn("no refresh attempt in the last 2 days", self.digest(no_attempt)["feed"]["line"])
        text = wd.render_text(d)
        self.assertEqual(text.splitlines()[3].strip(), d["feed"]["line"])  # first line under the title block

    def test_e25_bootstrap_and_missing_state(self):
        boot = {k: v for k, v in self.STATE.items() if k != "last_digest_covered_through"}
        d = self.digest(boot)
        self.assertIsNone(d["new_since"])
        self.assertIn("Feed connected", d["feed"]["line"])
        d2 = self.digest(None)
        self.assertIn("refresh state missing", d2["feed"]["line"])
        self.assertIsNone(d2["new_since"])
        wd.render_text(d2); wd.render_html(d2)  # must not raise


if __name__ == "__main__":
    unittest.main(verbosity=2)
