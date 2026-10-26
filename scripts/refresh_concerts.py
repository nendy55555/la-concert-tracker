#!/usr/bin/env python3
"""
refresh_concerts.py: pull upcoming music events for the tracked LA venues from the
Ticketmaster Discovery API and rewrite the CONCERTS array inside index.html.

Past rows are kept. Future rows are replaced per venue. A venue whose fetch fails,
that returns zero rows after having rows last run, or that has no Ticketmaster
ids, keeps its existing future rows. Nothing is written when the feed looks thin
or every fetch fails.

Exit codes:
  0 ok · 1 liveness failed after a successful write · 2 CONCERTS unparseable
  3 config or key missing · 4 every venue fetch failed · 5 thin-feed guard
  6 post-write verification failed (nothing written)

Usage:
  python3 scripts/refresh_concerts.py            # refresh, print JSON summary
  python3 scripts/refresh_concerts.py --dry-run  # fetch and report, write nothing
"""
from __future__ import annotations

import argparse
import calendar
import contextlib
import json
import os
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Callable
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import weekly_digest as wd  # noqa: E402  (parser + .env loader live there)
# from liveness import Result, check_max_date, run_checks  # noqa: E402  (copied accelerator, Task 4)


def load_venues(path: Path) -> list[dict]:
    venues = json.loads(path.read_text(encoding="utf-8"))
    for v in venues:
        for key in ("name", "tmVenueIds", "vendor", "tier"):
            if key not in v:
                raise ValueError(f"venues.json entry missing {key!r}: {v}")
    return venues
