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


TZ = ZoneInfo("America/Los_Angeles")
API_EVENTS = "https://app.ticketmaster.com/discovery/v2/events.json"
PAGE_SIZE = 200
MAX_PAGES = 10
HORIZON_DAYS = 365  # fetch window; also bounds the data so no year-bound test ever trips on a far-future row

# Ticketmaster genre name → the tracker's 8 genres. Anything unmapped is "Other".
GENRE_MAP = {
    "Hip-Hop/Rap": "Hip-Hop/R&B", "R&B": "Hip-Hop/R&B",
    "Dance/Electronic": "Electronic/EDM",
    "Rock": "Rock", "Metal": "Rock", "Alternative": "Rock",
    "Pop": "Pop", "Ballads/Romantic": "Pop", "Holiday": "Pop",
    "Folk": "Indie/Folk", "Country": "Indie/Folk", "Blues": "Indie/Folk",
    "Punk": "Punk",
    "Latin": "Latin",
}


def map_genre(tm_genre: str | None) -> str:
    return GENRE_MAP.get(tm_genre or "", "Other")


def to_pt(iso_utc: str | None) -> str:
    """'2026-05-29T17:00:00Z' → '2026-05-29T10:00' (America/Los_Angeles). '' when missing."""
    if not iso_utc:
        return ""
    try:
        dt = datetime.strptime(iso_utc, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        return ""
    return dt.astimezone(TZ).strftime("%Y-%m-%dT%H:%M")


def event_to_row(ev: dict, venue: dict, now: datetime) -> dict | None:
    cls = (ev.get("classifications") or [{}])[0]
    if (cls.get("segment") or {}).get("name") != "Music":
        return None
    start = (ev.get("dates") or {}).get("start") or {}
    status = ((ev.get("dates") or {}).get("status") or {}).get("code", "")
    if status == "cancelled" or start.get("dateTBD") or start.get("dateTBA") or not start.get("localDate"):
        return None
    emb = ev.get("_embedded") or {}
    tm_venue = (emb.get("venues") or [{}])[0]
    state_code = ((tm_venue.get("state") or {}).get("stateCode") or "").upper()
    if state_code and state_code != "CA":
        return None  # a mis-resolved id in another state must never be stamped with an LA venue name
    artists = [a.get("name", "").strip() for a in emb.get("attractions") or [] if a.get("name")]
    sales = ev.get("sales") or {}
    presales = [p.get("startDateTime") for p in sales.get("presales") or [] if p.get("startDateTime")]
    return {
        "date": start["localDate"],
        "name": (ev.get("name") or "").strip(),
        "venue": venue["name"],
        "genre": map_genre((cls.get("genre") or {}).get("name")),
        "support": ", ".join(artists[1:]),
        "spotifyMonthlyListeners": 0,
        "ticketUrl": ev.get("url") or "",
        "ticketVendor": venue["vendor"],
        "onSaleDate": to_pt((sales.get("public") or {}).get("startDateTime")),
        "presaleDate": to_pt(min(presales)) if presales else "",
        "tmId": ev.get("id") or "",
        "artists": artists,
        "firstSeen": now.isoformat(timespec="seconds"),
    }


def urlopen_json(url: str) -> dict:
    """GET with three attempts. Retries on network errors, 429 and 5xx."""
    last: Exception | None = None
    for attempt in range(3):
        try:
            with urllib.request.urlopen(url, timeout=30) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            last = e
            if e.code not in (429, 500, 502, 503, 504):
                raise
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
            last = e
        time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"fetch failed after 3 attempts: {last}")


def fetch_venue_events(venue: dict, key: str, today: date, now: datetime,
                       http: Callable[[str], dict] = urlopen_json, seen: dict | None = None) -> list[dict]:
    """All upcoming music events at every Ticketmaster id of `venue` within HORIZON_DAYS, deduped by tmId.
    When `seen` is given, records what room each id really is: seen[vid] = "<TM name>, <city>"."""
    start_iso = f"{today.isoformat()}T00:00:00Z"
    end_iso = f"{(today + timedelta(days=HORIZON_DAYS)).isoformat()}T23:59:59Z"
    rows: dict[str, dict] = {}
    for vid in venue["tmVenueIds"]:
        page = 0
        while page < MAX_PAGES:
            q = {"apikey": key, "venueId": vid, "classificationName": "music", "size": PAGE_SIZE,
                 "page": page, "sort": "date,asc", "startDateTime": start_iso, "endDateTime": end_iso}
            data = http(API_EVENTS + "?" + urllib.parse.urlencode(q))
            events = (data.get("_embedded") or {}).get("events") or []
            if seen is not None and events and vid not in seen:
                tv = ((events[0].get("_embedded") or {}).get("venues") or [{}])[0]
                seen[vid] = f"{tv.get('name', '?')}, {(tv.get('city') or {}).get('name', '?')}"
            for ev in events:
                row = event_to_row(ev, venue, now)
                if row and row["tmId"] not in rows:
                    rows[row["tmId"]] = row
            page += 1
            if page >= int((data.get("page") or {}).get("totalPages", 0)):
                break
            time.sleep(0.25)
    return list(rows.values())


ROW_KEYS = ["date", "name", "venue", "genre", "support", "spotifyMonthlyListeners", "ticketUrl",
            "ticketVendor", "onSaleDate", "presaleDate", "tmId", "artists", "firstSeen"]


def _js(v) -> str:
    # ensure_ascii=True: curly quotes, accents and dashes become \uXXXX escapes, which the
    # digest parser passes through untouched and JSON decodes back to the original text.
    return json.dumps(v, ensure_ascii=True)


def render_row(r: dict) -> str:
    parts = [f"{k}: {_js(r[k])}" for k in ROW_KEYS if k in r]
    return "  { " + ", ".join(parts) + " },"


def merge_rows(existing: list[dict], fetched: dict[str, list[dict]], failed: set[str],
               uncovered: set[str], today: date) -> list[dict]:
    """Past rows stay. Future rows are replaced per venue by `fetched`, except at
    venues in `failed` or `uncovered`, which keep their existing future rows.
    firstSeen is carried over for tmIds already present."""
    today_iso = today.isoformat()
    keep_future = failed | uncovered
    first_seen = {r["tmId"]: r.get("firstSeen", "") for r in existing if r.get("tmId")}

    out: list[dict] = []
    for r in existing:
        if r["date"] < today_iso:
            out.append(r)
        elif r["venue"] in keep_future or r["venue"] not in fetched:
            out.append(r)
    for venue_name, rows in fetched.items():
        if venue_name in keep_future:
            continue
        for r in rows:
            prev = first_seen.get(r["tmId"])
            if prev:
                r = dict(r, firstSeen=prev)
            out.append(r)
    out.sort(key=lambda r: (r["date"], r["name"].lower()))
    return out
