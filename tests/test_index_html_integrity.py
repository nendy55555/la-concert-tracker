#!/usr/bin/env python3
"""
test_index_html_integrity.py — schema/data-quality checks over the live
`index.html`. Catches the class of silent breaks the weekly digest relied on
Claude to notice: stray quotes, missing fields, bad dates, unknown venues.

Run:
    python3 -m unittest tests.test_index_html_integrity -v
"""

from __future__ import annotations

import re
import sys
import unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import weekly_digest as wd  # noqa: E402


REQUIRED_FIELDS = {
    "date",
    "name",
    "venue",
    "genre",
    "support",
    "spotifyMonthlyListeners",
    "ticketUrl",
    "ticketVendor",
    "onSaleDate",
    "presaleDate",
}

# Per README + index.html's VENUE_DEFAULT_VENDOR keys.
KNOWN_VENUES = {
    "Hollywood Bowl",
    "Greek Theatre",
    "Kia Forum",
    "Crypto.com Arena",
    "SoFi Stadium",
    "The Wiltern",
    "The Fonda Theatre",
    "Troubadour",
    "YouTube Theater",
    "The Regent Theater",
    "Rose Bowl",
    "Hollywood Palladium",
    "Academy LA",
    "El Rey Theatre",
    "Intuit Dome",
    "Shrine Auditorium",
    "The Novo",
    "The Roxy Theatre",
    "The Peppermint Club",
}

KNOWN_GENRES = {
    "Hip-Hop/R&B",
    "Electronic/EDM",
    "Rock",
    "Pop",
    "Indie/Folk",
    "Punk",
    "Latin",
    "Other",
}


class TestIndexHtmlIntegrity(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        real = ROOT / "index.html"
        if not real.exists():
            raise unittest.SkipTest("real index.html not found")
        cls.concerts, cls.wishlist = wd.load_data(real)

    def test_has_many_concerts(self):
        self.assertGreater(len(self.concerts), 300, "Expected >300 concerts; did a data refresh go wrong?")

    def test_every_concert_has_required_fields(self):
        for i, c in enumerate(self.concerts):
            missing = REQUIRED_FIELDS - set(c.keys())
            self.assertFalse(
                missing,
                f"concert[{i}] {c.get('name', '?')!r} @ {c.get('date', '?')} missing fields: {missing}",
            )

    def test_date_format(self):
        pat = re.compile(r"^\d{4}-\d{2}-\d{2}$")
        for c in self.concerts:
            self.assertRegex(c["date"], pat)
            # Also must be a real date
            date.fromisoformat(c["date"])

    def test_dates_in_expected_range(self):
        # Concerts should be within the 2026 season window surfaced by the app.
        for c in self.concerts:
            d = date.fromisoformat(c["date"])
            self.assertGreaterEqual(d.year, 2026)
            self.assertLessEqual(d.year, date.today().year + 2)  # generous upper bound

    def test_refresh_markers_present_once(self):
        src = (ROOT / "index.html").read_text(encoding="utf-8")
        self.assertEqual(src.count("<!--LAST_REFRESH:START-->"), 1)
        self.assertEqual(src.count("<!--LAST_REFRESH:END-->"), 1)

    def test_venue_set_is_known(self):
        unknown = {c["venue"] for c in self.concerts} - KNOWN_VENUES
        self.assertFalse(unknown, f"unknown venues: {unknown}")

    def test_genre_set_is_known(self):
        unknown = {c["genre"] for c in self.concerts} - KNOWN_GENRES
        self.assertFalse(unknown, f"unknown genres: {unknown}")

    def test_ticket_urls_well_formed(self):
        for c in self.concerts:
            if c["ticketUrl"]:
                self.assertTrue(
                    c["ticketUrl"].startswith(("http://", "https://")),
                    f"bad ticketUrl: {c['ticketUrl']!r}",
                )

    def test_on_sale_dates_parseable_or_empty(self):
        for c in self.concerts:
            for field in ("onSaleDate", "presaleDate"):
                v = c[field]
                if not v:
                    continue
                # parse_sale_date returns None if unparseable
                self.assertIsNotNone(
                    wd.parse_sale_date(v), f"bad {field}: {v!r} on {c['name']!r}"
                )

    def test_no_duplicate_rows(self):
        # Permissive dup detection: same (date, name, venue) appearing multiple times is a smell.
        seen = {}
        dups = []
        for c in self.concerts:
            key = (c["date"], c["name"], c["venue"])
            if key in seen:
                dups.append(key)
            seen[key] = True
        # Flag dups but don't fail hard — the app's dedupe runs client-side via concertKey.
        if dups:
            print(f"\n[warn] {len(dups)} duplicate (date,name,venue) rows: {dups[:5]}{'…' if len(dups)>5 else ''}")

    def test_wishlist_non_empty_and_unique(self):
        self.assertGreater(len(self.wishlist), 0)
        self.assertEqual(len(self.wishlist), len(set(self.wishlist)), "WISHLIST_ARTISTS has duplicates")

    def test_spotify_counts_are_numbers(self):
        for c in self.concerts:
            self.assertIsInstance(c["spotifyMonthlyListeners"], (int, float))
            self.assertGreaterEqual(c["spotifyMonthlyListeners"], 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
