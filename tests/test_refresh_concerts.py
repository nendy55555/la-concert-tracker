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


if __name__ == "__main__":
    unittest.main()
