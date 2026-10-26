# Concert Feed Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the hand-pasted `CONCERTS` array with a weekly Ticketmaster Discovery pull for the 19 tracked venues, and make the Sunday digest lead with what is new and say how old its data is.

**Architecture:** A new stdlib script `scripts/refresh_concerts.py` fetches each venue's upcoming music events, maps them to the existing row shape plus `tmId`/`artists`/`firstSeen`, replaces future rows per venue inside `index.html` (past rows kept, ghost rows dropped, failed, zero-row or uncovered venues left alone), guards against a thin feed, writes atomically after a parse round-trip, and records `data/refresh_state.json`. `scripts/weekly_digest.py` reads that state to render a "New since" section and a data-age line that names failed venues, test failures and push failures, and writes `last_digest_date` after a successful send. `scripts/weekly_run.sh` chains refresh → tests → commit+push → digest, records test and push outcomes into the state file, and is the single command the Cowork task runs.

**Tech Stack:** Python 3.10+ stdlib (`urllib`, `json`, `zoneinfo`, `unittest`), Node for the JS parity check, bash, git. No pip, no npm.

## Global Constraints

- Python 3.10+ stdlib only, same floor as `scripts/weekly_digest.py` (uses `str | None`). `scripts/liveness.py` is a verbatim copy and stays 3.9-clean inside.
- Zero network in `tests/`. Every HTTP call goes through an injectable `http` callable.
- Never print, log or commit the value of `TM_DISCOVERY_API_KEY`, `GMAIL_APP_PASSWORD` or `EMAIL_TO`.
- `index.html` outside the `CONCERTS` block and the `<!--LAST_REFRESH:START-->…<!--LAST_REFRESH:END-->` markers must be byte-identical before and after a refresh.
- Writes to `index.html` and `data/refresh_state.json` are temp-file + `os.replace`, after `weekly_digest.load_data` has parsed the new content and the parsed rows equal the merged rows.
- Exit codes for `refresh_concerts.py`: 0 ok · 1 liveness failed after a successful write · 2 `CONCERTS` unparseable · 3 config or key missing · 4 every venue fetch failed · 5 thin-feed guard · 6 post-write verification failed (nothing written).
- No hardcoded year anywhere new. Tests derive bounds from `date.today()`.
- No em dashes in any text the user sees (email, page, docs). Use `·` or commas.
- Run the whole suite with `bash tests/run_all.sh` before every commit. It must stay under 5 seconds.
- Commit after every task with the message given, using explicit paths (never `git add -A`: the working tree holds unrelated uncommitted work until Task 9). Do not push until Task 9.

## File map

| File | Responsibility |
|---|---|
| `scripts/venues.json` | Venue registry: canonical name, TM venue ids, vendor, tier |
| `scripts/refresh_concerts.py` | Fetch, map, merge, guard, write, state |
| `scripts/liveness.py` | Copy of the liveness accelerator |
| `scripts/weekly_digest.py` | Existing digest; gains a string-aware parser, matcher precision, New-since, data-age, state write |
| `scripts/weekly_run.sh` | The one command the scheduled task runs |
| `data/refresh_state.json` | Committed run state |
| `index.html` | Data block rewritten by script; markers; year nav; matcher parity |
| `tests/test_refresh_concerts.py` | E0 to E17 |
| `tests/test_weekly_digest.py` | gains E18, E19, E21 to E25 |
| `tests/js_matcher_parity.js` | E20 |
| `tests/fixtures/mini_index_feed.html` | the refresh suite's own fixture (the digest suite rewrites `mini_index.html` from a constant, so it cannot be shared) |
| `tests/fixtures/tm_events_sample.json`, `tm_events_page2.json`, `matcher_cases.json` | fixtures |
| `tests/run_all.sh` | adds the new suites and E26/E27 |

Review log: `docs/agent/specs/concert-feed/REVIEW.md`.

---

### Task 0: Bring git into a known state before any commit

**Why first:** local `main` is one commit behind `origin/main` (`cce2523 Create CNAME`, 2026-05-14) and the working tree holds the never-committed 2026-06-02 data refresh and docs consolidation, some of it already staged. Committing Task 1 on top of that would both sweep June's data into a "venue registry" commit and make every later `git pull --ff-only` and `git push` fail as non-fast-forward (the tempting `--force` would delete the CNAME commit and the custom domain with it).

- [ ] **Step 1: Fast-forward while local is purely behind**

```bash
git branch -vv | head -1
git pull --ff-only
```

Expected: the first line says `[origin/main: behind 1]`; the pull succeeds and adds only `CNAME`.

- [ ] **Step 2: Commit the June work as its own commit, by name**

```bash
git add index.html scripts/weekly_digest.py tests/test_weekly_digest.py tests/_smoke_dist dist docs/agent/QUICKSTART.md docs/agent/RUNBOOK.md docs/agent/SESSION-STATE.md docs/agent/archive .gitignore
git add -u docs/agent
git commit -m "data+docs: 2026-06-02 refresh and docs consolidation (never pushed)"
git status --short
```

Expected after: only `__pycache__` noise, `tests/fixtures/_email_dist/`, `.env.example` and `docs/agent/specs/` remain unstaged. Leave them; Task 1 commits `.env.example` and the spec folder is committed in Task 8.

No push yet (Task 9 pushes everything together after the first live refresh).

---

### Task 1: Venue registry, API key, fixtures

**Files:**
- Create: `scripts/venues.json`
- Create: `tests/fixtures/tm_events_sample.json`, `tests/fixtures/tm_events_page2.json`, `tests/fixtures/matcher_cases.json`, `tests/fixtures/mini_index_feed.html`
- Create: `tests/test_refresh_concerts.py` (registry tests only for now)
- Modify: `.env` (append one line, by command)
- Modify: `.env.example`

**Interfaces:**
- Produces: `scripts/venues.json` as a JSON array of `{"name": str, "tmVenueIds": [str], "vendor": str, "tier": int}`. Names equal the 19 entries of `KNOWN_VENUES` in `tests/test_index_html_integrity.py`.
- Produces: `tests/fixtures/mini_index_feed.html`, a copy of `tests/fixtures/mini_index.html` with the refresh markers and one ghost row. Only `test_refresh_concerts.py` reads it.

- [ ] **Step 1: Write the registry**

`scripts/venues.json`:

```json
[
  {"name": "Hollywood Bowl",      "tmVenueIds": ["KovZpZAFFvJA"], "vendor": "Hollywood Bowl Box Office", "tier": 3},
  {"name": "Greek Theatre",       "tmVenueIds": ["KovZpa2Hxe"],   "vendor": "Ticketmaster", "tier": 3},
  {"name": "Kia Forum",           "tmVenueIds": ["KovZpZAEkn6A"], "vendor": "Ticketmaster", "tier": 3},
  {"name": "Crypto.com Arena",    "tmVenueIds": ["KovZpZAEdntA"], "vendor": "AXS", "tier": 4},
  {"name": "SoFi Stadium",        "tmVenueIds": ["KovZ917ACh0"],  "vendor": "Ticketmaster", "tier": 4},
  {"name": "The Wiltern",         "tmVenueIds": ["KovZpZAEAl6A"], "vendor": "Ticketmaster", "tier": 2},
  {"name": "The Fonda Theatre",   "tmVenueIds": ["KovZpZAFAkIA"], "vendor": "Ticketmaster", "tier": 2},
  {"name": "Troubadour",          "tmVenueIds": ["KovZpa4eIe"],   "vendor": "Troubadour Box Office", "tier": 1},
  {"name": "YouTube Theater",     "tmVenueIds": ["KovZ917AJue"],  "vendor": "Ticketmaster", "tier": 3},
  {"name": "The Regent Theater",  "tmVenueIds": ["KovZpZAJ6daA"], "vendor": "Ticketmaster", "tier": 1},
  {"name": "Rose Bowl",           "tmVenueIds": ["KovZpZAEA66A"], "vendor": "Ticketmaster", "tier": 4},
  {"name": "Hollywood Palladium", "tmVenueIds": ["KovZpZAEAlaA"], "vendor": "Ticketmaster", "tier": 2},
  {"name": "Academy LA",          "tmVenueIds": ["KovZpZAdIAtA"], "vendor": "Academy LA Box Office", "tier": 2},
  {"name": "El Rey Theatre",      "tmVenueIds": ["Z6r9jZkv7e"],   "vendor": "Ticketmaster", "tier": 1},
  {"name": "Intuit Dome",         "tmVenueIds": ["KovZ917Acq0"],  "vendor": "AXS", "tier": 4},
  {"name": "Shrine Auditorium",   "tmVenueIds": ["KovZpa3u7e", "KovZpZAdEanA"], "vendor": "AXS", "tier": 3},
  {"name": "The Novo",            "tmVenueIds": ["KovZ917A25f"],  "vendor": "AXS", "tier": 2},
  {"name": "The Roxy Theatre",    "tmVenueIds": ["KovZpZAFAIFA"], "vendor": "The Roxy Box Office", "tier": 1},
  {"name": "The Peppermint Club", "tmVenueIds": ["KovZ917A2k0"],  "vendor": "Peppermint Club Box Office", "tier": 1}
]
```

The ids were resolved against `venues.json?keyword=` on 2026-10-25. El Rey's live entity is named "El Rey Theatre - Los Angeles"; the `KovZpZAkJnnA` entity has zero events. Shrine gets the Expo Hall id too because the existing data files Expo Hall shows under "Shrine Auditorium".

- [ ] **Step 2: Copy the key into `.env` without echoing it**

From the project root (`~/Documents/Claude/Projects/LA Concert Tracker`). The leading `echo` guards against a file with no trailing newline:

```bash
grep -q '^TM_DISCOVERY_API_KEY=' .env || { echo; grep '^TM_DISCOVERY_API_KEY=' "../Row 5/scanner/.env"; } >> .env; grep -c '^TM_DISCOVERY_API_KEY=' .env
```

Expected output: `1`. Append to `.env.example`:

```
# Ticketmaster Discovery API consumer key (public event metadata). Same key Row 5 uses.
TM_DISCOVERY_API_KEY=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

- [ ] **Step 3: Write the Ticketmaster fixtures**

`tests/fixtures/tm_events_sample.json` (shape copied from a real page; four events):

```json
{
  "_embedded": {"events": [
    {
      "name": "Headliner Name: The Big Tour",
      "id": "vvG1TEST0001",
      "url": "https://www.ticketmaster.com/headliner-name-los-angeles-11-20-2026/event/vvG1TEST0001",
      "dates": {"start": {"localDate": "2026-11-20", "localTime": "20:00:00", "dateTime": "2026-11-21T04:00:00Z", "dateTBD": false, "dateTBA": false},
                "timezone": "America/Los_Angeles", "status": {"code": "onsale"}},
      "sales": {"public": {"startDateTime": "2026-05-29T17:00:00Z", "startTBD": false},
                "presales": [{"startDateTime": "2026-05-28T17:00:00Z", "endDateTime": "2026-05-29T05:00:00Z", "name": "Venue Presale"},
                             {"startDateTime": "2026-05-28T19:00:00Z", "endDateTime": "2026-05-29T05:00:00Z", "name": "Artist Presale"}]},
      "classifications": [{"primary": true, "segment": {"name": "Music"}, "genre": {"name": "Hip-Hop/Rap"}, "subGenre": {"name": "Rap"}}],
      "_embedded": {"venues": [{"name": "The Novo by Microsoft", "id": "KovZ917A25f"}],
                    "attractions": [{"name": "Headliner Name"}, {"name": "Opener Name"}]}
    },
    {
      "name": "Los Angeles Lakers vs. Phoenix Suns",
      "id": "vvG1TEST0002",
      "url": "https://www.ticketmaster.com/lakers/event/vvG1TEST0002",
      "dates": {"start": {"localDate": "2026-11-21", "dateTBD": false, "dateTBA": false}, "status": {"code": "onsale"}},
      "classifications": [{"primary": true, "segment": {"name": "Sports"}, "genre": {"name": "Basketball"}}],
      "_embedded": {"venues": [{"name": "Crypto.com Arena", "id": "KovZpZAEdntA"}], "attractions": [{"name": "Los Angeles Lakers"}]}
    },
    {
      "name": "Cancelled Band",
      "id": "vvG1TEST0003",
      "url": "https://www.ticketmaster.com/cancelled/event/vvG1TEST0003",
      "dates": {"start": {"localDate": "2026-12-01", "dateTBD": false, "dateTBA": false}, "status": {"code": "cancelled"}},
      "classifications": [{"primary": true, "segment": {"name": "Music"}, "genre": {"name": "Rock"}}],
      "_embedded": {"venues": [{"name": "The Wiltern", "id": "KovZpZAEAl6A"}], "attractions": [{"name": "Cancelled Band"}]}
    },
    {
      "name": "TBD Act",
      "id": "vvG1TEST0004",
      "url": "https://www.ticketmaster.com/tbd/event/vvG1TEST0004",
      "dates": {"start": {"dateTBD": true, "dateTBA": false}, "status": {"code": "onsale"}},
      "classifications": [{"primary": true, "segment": {"name": "Music"}, "genre": {"name": "Pop"}}],
      "_embedded": {"venues": [{"name": "Troubadour", "id": "KovZpa4eIe"}], "attractions": [{"name": "TBD Act"}]}
    }
  ]},
  "page": {"size": 200, "totalElements": 5, "totalPages": 2, "number": 0}
}
```

`tests/fixtures/tm_events_page2.json`:

```json
{
  "_embedded": {"events": [
    {
      "name": "Page Two Artist",
      "id": "vvG1TEST0005",
      "url": "https://www.ticketmaster.com/p2/event/vvG1TEST0005",
      "dates": {"start": {"localDate": "2027-01-15", "localTime": "21:00:00", "dateTBD": false, "dateTBA": false}, "status": {"code": "onsale"}},
      "sales": {"public": {"startDateTime": "2026-10-23T17:00:00Z"}},
      "classifications": [{"primary": true, "segment": {"name": "Music"}, "genre": {"name": "Jazz"}}],
      "_embedded": {"venues": [{"name": "The Novo by Microsoft", "id": "KovZ917A25f"}], "attractions": [{"name": "Page Two Artist"}]}
    },
    {
      "name": "Headliner Name: The Big Tour",
      "id": "vvG1TEST0001",
      "url": "https://www.ticketmaster.com/headliner-name-los-angeles-11-20-2026/event/vvG1TEST0001",
      "dates": {"start": {"localDate": "2026-11-20", "dateTBD": false, "dateTBA": false}, "status": {"code": "onsale"}},
      "classifications": [{"primary": true, "segment": {"name": "Music"}, "genre": {"name": "Hip-Hop/Rap"}}],
      "_embedded": {"venues": [{"name": "The Novo by Microsoft", "id": "KovZ917A25f"}], "attractions": [{"name": "Headliner Name"}]}
    }
  ]},
  "page": {"size": 200, "totalElements": 5, "totalPages": 2, "number": 1}
}
```

The duplicate `vvG1TEST0001` on page 2 is deliberate (E5 dedupe).

`tests/fixtures/matcher_cases.json`:

```json
[
  {"watch": "Dave",          "artists": ["Dave Hause & The Mermaid"], "name": "Dave Hause & The Mermaid", "expect": false},
  {"watch": "Dave",          "artists": ["Dave"],                     "name": "Dave",                     "expect": true},
  {"watch": "Fred Again",    "artists": ["Fred again.."],             "name": "Fred again..",             "expect": true},
  {"watch": "JCole",         "artists": ["J. Cole"],                  "name": "J. Cole",                  "expect": true},
  {"watch": "Odesza",        "artists": ["ODESZA"],                   "name": "ODESZA: The Last Goodbye", "expect": true},
  {"watch": "Jungle",        "artists": ["Jungle Brothers"],          "name": "Jungle Brothers",          "expect": false},
  {"watch": "Polo & Pan",    "artists": ["Empire of the Sun", "Polo & Pan"], "name": "Empire of the Sun", "expect": true},
  {"watch": "Kendrick Lamar","artists": [],                           "name": "Kendrick Lamar - Grand National Tour", "expect": true},
  {"watch": "Dave",          "artists": [],                           "name": "Dave Koz Christmas Tour", "expect": false},
  {"watch": "Notion",        "artists": [],                           "name": "Notion",                   "expect": true},
  {"watch": "Chris Lake",    "artists": [],                           "name": "Chris Lake b2b Fisher",    "expect": true}
]
```

- [ ] **Step 4: Create the refresh suite's own fixture**

```bash
cp tests/fixtures/mini_index.html tests/fixtures/mini_index_feed.html
```

Then edit `tests/fixtures/mini_index_feed.html` by hand: inside `<body>`, before the `<script>`, add

```html
<div class="last-updated"><!--LAST_REFRESH:START-->Data refreshed: June 2, 2026 &bull; 3 upcoming shows across 19 venues<!--LAST_REFRESH:END--></div>
```

and inside its `CONCERTS` array add one future row with no `tmId`:

```js
  { date: '2026-11-14', name: 'Tame Impala', venue: 'Kia Forum', genre: 'Rock', support: '', spotifyMonthlyListeners: 0, ticketUrl: '', ticketVendor: 'Ticketmaster', onSaleDate: '', presaleDate: '' },
```

Do not touch `tests/fixtures/mini_index.html`: `tests/test_weekly_digest.py` rewrites it from its `MINI_INDEX_HTML` constant in several tests.

Record how many rows in `mini_index_feed.html` are dated before 2026-10-26: `python3 -c "import sys; sys.path.insert(0,'scripts'); import weekly_digest as w; c,_=w.load_data(__import__('pathlib').Path('tests/fixtures/mini_index_feed.html')); print(sum(1 for r in c if r['date']<'2026-10-26'))"`. E14 derives this number at runtime, so this is only to know the fixture is sane (expect a small number, at least 1).

- [ ] **Step 5: Write the registry tests**

`tests/test_refresh_concerts.py` (start of file; later tasks append):

```python
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
```

- [ ] **Step 6: Run to verify it fails**

Run: `python3 -m unittest tests.test_refresh_concerts -v`
Expected: `ModuleNotFoundError: No module named 'refresh_concerts'`

- [ ] **Step 7: Create the module skeleton with `load_venues` only**

`scripts/refresh_concerts.py`:

```python
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
from liveness import Result, check_max_date, run_checks  # noqa: E402  (copied accelerator, Task 4)


def load_venues(path: Path) -> list[dict]:
    venues = json.loads(path.read_text(encoding="utf-8"))
    for v in venues:
        for key in ("name", "tmVenueIds", "vendor", "tier"):
            if key not in v:
                raise ValueError(f"venues.json entry missing {key!r}: {v}")
    return venues
```

Until Task 4 copies `scripts/liveness.py`, comment out the `from liveness import ...` line; Task 4 uncomments it.

- [ ] **Step 8: Run to verify it passes**

Run: `python3 -m unittest tests.test_refresh_concerts -v`
Expected: 3 tests OK.

- [ ] **Step 9: Commit**

```bash
git add scripts/venues.json scripts/refresh_concerts.py tests/test_refresh_concerts.py tests/fixtures/tm_events_sample.json tests/fixtures/tm_events_page2.json tests/fixtures/matcher_cases.json tests/fixtures/mini_index_feed.html .env.example
git commit -m "feed: venue registry with Ticketmaster ids, fixtures, key template"
```

---

### Task 2: Event mapping and venue fetch

**Files:**
- Modify: `scripts/refresh_concerts.py`
- Modify: `tests/test_refresh_concerts.py`

**Interfaces:**
- Produces:
  - `map_genre(tm_genre: str | None) -> str`
  - `to_pt(iso_utc: str | None) -> str` returning `"YYYY-MM-DDTHH:MM"` in America/Los_Angeles, or `""`.
  - `event_to_row(ev: dict, venue: dict, now: datetime) -> dict | None`. `firstSeen` is `now.isoformat(timespec="seconds")`, a full timestamp, so a refresh run later the same day as a digest still produces rows the next digest can tell apart. An event whose venue carries `state.stateCode` other than `"CA"` returns `None` (a wrong venue id in another state can then never masquerade as an LA room).
  - `fetch_venue_events(venue: dict, key: str, today: date, now: datetime, http: Callable[[str], dict], seen: dict | None = None) -> list[dict]`, querying `startDateTime = today` and `endDateTime = today + HORIZON_DAYS`. When `seen` is a dict, it records `seen[venue_id] = "<TM venue name>, <city>"` from the first event returned for that id, so a dry run can show which room each id really is.
  - `urlopen_json(url: str) -> dict` (the default `http`, with retries)

- [ ] **Step 0: Add `Other` to the genre allowlist**

In `tests/test_index_html_integrity.py` add `"Other"` to `KNOWN_GENRES`. E4 below asserts every mapped genre is in that set.

- [ ] **Step 1: Write the failing tests (E1 to E5)**

Append to `tests/test_refresh_concerts.py` above the `if __name__` block:

```python
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
```

- [ ] **Step 2: Run to verify they fail**

Run: `python3 -m unittest tests.test_refresh_concerts -v`
Expected: 6 failures with `AttributeError: module 'refresh_concerts' has no attribute ...`

- [ ] **Step 3: Implement mapping and fetch**

Add to `scripts/refresh_concerts.py` after `load_venues`:

```python
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
```

The `time.sleep(0.25)` between pages keeps under Ticketmaster's 5 requests/second; tests pass because the fixture has only two pages.

- [ ] **Step 4: Run to verify they pass**

Run: `python3 -m unittest tests.test_refresh_concerts -v`
Expected: 9 tests OK.

- [ ] **Step 5: Commit**

```bash
git add scripts/refresh_concerts.py tests/test_refresh_concerts.py tests/test_index_html_integrity.py
git commit -m "feed: Ticketmaster event mapping and per-venue fetch with pagination"
```

---

### Task 2a: Make the JS-to-JSON parser string-aware, and render rows it can read

**Files:**
- Modify: `scripts/weekly_digest.py:90-181` (`_js_array_to_python`)
- Modify: `scripts/refresh_concerts.py` (add `render_row`)
- Modify: `tests/test_refresh_concerts.py`

**Why this task exists:** the parser's three post-passes (key quoting, trailing-comma removal, smart-quote translation) run as regexes over the whole cleaned text, including string bodies. A name like `Dawes, Live: An Evening` gets `"Live":` injected; `Tyler, The Creator “CHROMAKOPIA” Tour` gets its curly quotes turned into raw `"`. Real Ticketmaster names hit both. The fix is to apply those passes only to the non-string segments the tokenizer already separates.

**Interfaces:**
- Produces: `render_row(r: dict) -> str` in `refresh_concerts.py`, one JS object literal per row with `json.dumps(..., ensure_ascii=True)` values, so non-ASCII reaches the file as `\uXXXX` escapes.
- `_js_array_to_python` keeps its signature and behaviour for every existing test.

- [ ] **Step 1: Write the failing tests (E0)**

Append to `tests/test_refresh_concerts.py`:

```python
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
```

- [ ] **Step 2: Run to verify they fail**

Run: `python3 -m unittest tests.test_refresh_concerts.TestParserRoundTrip -v`
Expected: `test_e0_hard_names_round_trip` errors (`AttributeError: render_row` first; after adding `render_row` in Step 3 it must still FAIL with `JSONDecodeError` until Step 4 lands, which proves the parser change is the fix).

- [ ] **Step 3: Add `render_row`**

In `scripts/refresh_concerts.py`:

```python
ROW_KEYS = ["date", "name", "venue", "genre", "support", "spotifyMonthlyListeners", "ticketUrl",
            "ticketVendor", "onSaleDate", "presaleDate", "tmId", "artists", "firstSeen"]


def _js(v) -> str:
    # ensure_ascii=True: curly quotes, accents and dashes become \uXXXX escapes, which the
    # digest parser passes through untouched and JSON decodes back to the original text.
    return json.dumps(v, ensure_ascii=True)


def render_row(r: dict) -> str:
    parts = [f"{k}: {_js(r[k])}" for k in ROW_KEYS if k in r]
    return "  { " + ", ".join(parts) + " },"
```

- [ ] **Step 4: Make the parser's post-passes string-aware**

In `scripts/weekly_digest.py`, `_js_array_to_python` builds `out: list[str]` by appending string literals and non-string characters. Change it to track which segments are strings, run the three post-passes only on the non-string text, and translate smart quotes only there as well. Concretely, replace the tail of the function (from `cleaned = "".join(out)` to `return json.loads(cleaned)`) with:

```python
    # Post-passes run on NON-STRING segments only. A string literal (already JSON
    # double-quoted at this point) is passed through untouched, so a name such as
    # 'Dawes, Live: An Evening' can never be mistaken for an object key, and curly
    # quotes inside a name are never turned into raw double quotes.
    def _fix(segment: str) -> str:
        segment = re.sub(r"([{,]\s*)([A-Za-z_][A-Za-z0-9_]*)\s*:", r'\1"\2":', segment)
        segment = re.sub(r",(\s*[}\]])", r"\1", segment)
        return segment.translate(str.maketrans({"’": "'", "‘": "'", "“": '"', "”": '"'}))

    pieces: list[str] = []
    buf: list[str] = []
    for item in out:
        if len(item) >= 2 and item[0] == '"' and item[-1] == '"' and item is not None and _is_string_token(item):
            pieces.append(_fix("".join(buf)))
            buf = []
            pieces.append(item)
        else:
            buf.append(item)
    pieces.append(_fix("".join(buf)))
    return json.loads("".join(pieces))
```

That test on `item` is clumsy because `out` mixes whole string literals with single characters. The cleaner change, and the one to make: where the function does `out.append(js[i : j + 1])` (double-quoted literal) and `out.append('"' + "".join(body) + '"')` (converted single-quoted literal), append a tuple `("s", text)` instead; where it does `out.append(ch)`, append `("c", ch)`. Then the tail becomes:

```python
    def _fix(segment: str) -> str:
        segment = re.sub(r"([{,]\s*)([A-Za-z_][A-Za-z0-9_]*)\s*:", r'\1"\2":', segment)
        segment = re.sub(r",(\s*[}\]])", r"\1", segment)
        return segment.translate(str.maketrans({"’": "'", "‘": "'", "“": '"', "”": '"'}))

    pieces: list[str] = []
    buf: list[str] = []
    for kind, text in out:
        if kind == "s":
            pieces.append(_fix("".join(buf)))
            buf = []
            pieces.append(text)
        else:
            buf.append(text)
    pieces.append(_fix("".join(buf)))
    return json.loads("".join(pieces))
```

Delete the first (clumsy) version; it is shown only so the reader sees why the tuple form is needed. One more guard in the double-quoted branch: the existing loop `while j < n: if js[j] == "\\" ...` handles backslashes; a double-quoted literal produced by `json.dumps` is always valid JSON, so it is appended as-is.

The trailing-comma regex `,(\s*[}\]])` now never sees a string body, so a name like `"Lists], [More"` is safe too.

- [ ] **Step 5: Run everything**

Run: `bash tests/run_all.sh`
Expected: `TestParserRoundTrip` 2 OK, all 43 existing digest tests still OK (the mini fixture and the real `index.html` both parse), smoke ok.

- [ ] **Step 6: Commit**

```bash
git add scripts/weekly_digest.py scripts/refresh_concerts.py tests/test_refresh_concerts.py
git commit -m "parser: post-passes skip string bodies; feed rows render ASCII-safe"
```

---

### Task 3: Merge policy

**Files:**
- Modify: `scripts/refresh_concerts.py`
- Modify: `tests/test_refresh_concerts.py`

**Interfaces:**
- Produces: `merge_rows(existing: list[dict], fetched: dict[str, list[dict]], failed: set[str], uncovered: set[str], today: date) -> list[dict]`. `fetched` is keyed by canonical venue name and holds the rows the feed returned for that venue (possibly empty). `failed` and `uncovered` are venue names whose existing future rows must be kept.

- [ ] **Step 1: Write the failing tests (E6 to E10)**

Append to `tests/test_refresh_concerts.py`:

```python
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
```

- [ ] **Step 2: Run to verify they fail**

Run: `python3 -m unittest tests.test_refresh_concerts.TestMergeRows -v`
Expected: 6 errors, `AttributeError: ... 'merge_rows'`

- [ ] **Step 3: Implement**

Add to `scripts/refresh_concerts.py`:

```python
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
```

Note the second branch: a future row at a venue that is neither in `fetched` nor flagged is kept. That covers a venue missing from `venues.json` entirely, so a registry edit can never silently delete data.

- [ ] **Step 4: Run to verify they pass**

Run: `python3 -m unittest tests.test_refresh_concerts -v`
Expected: 17 tests OK.

- [ ] **Step 5: Commit**

```bash
git add scripts/refresh_concerts.py tests/test_refresh_concerts.py
git commit -m "feed: merge policy, past kept, future replaced per venue, ghosts dropped"
```

---

### Task 4: Guards, atomic write, state, liveness, `main`

**Files:**
- Create: `scripts/liveness.py` (copy), `data/refresh_state.json`
- Modify: `scripts/refresh_concerts.py`, `index.html` (markers only), `tests/test_index_html_integrity.py`, `tests/test_refresh_concerts.py`

**Interfaces:**
- Produces:
  - `render_concerts_block(rows: list[dict]) -> str` returning the text from `[` to `]` inclusive, rows grouped under `// ── MONTH YYYY ──` comments.
  - `rewrite_index(src: str, rows: list[dict], stamp: str) -> str`
  - `stamp_text(today: date, future_rows: int, venue_count: int) -> str`
  - `load_state(path: Path) -> dict`, `save_state(path: Path, state: dict) -> None`
  - `run(index_path, venues_path, state_path, key, today, now, http, dry_run=False, accept_thin=False) -> tuple[int, dict]` returning exit code and summary. The summary carries `venue_seen` (`{tm_venue_id: "<name>, <city>"}`) for the dry run.
  - `main(argv) -> int`, flags `--dry-run`, `--as-of`, `--accept-thin` (skips the thin-feed guard once, for a legitimate drop such as a venue leaving Ticketmaster).
- State keys written here: `last_success_at`, `last_attempt_at`, `last_attempt_status` (`ok | thin_feed | all_failed | verify_failed | liveness_failed | config | parse`), `future_rows`, `per_venue` (name → count or null), `failed_venues` (list of `"Name (reason)"`). Keys owned by others and preserved untouched: `last_digest_at`, `last_digest_covered_through` (digest), `last_tests_status`, `last_push_status`, `last_refresh_rc` (wrapper).
- Zero-rows rule, keyed on the data and not on last week's count: a covered venue that returns 0 rows while `index.html` still holds future rows for it is treated as failed with reason `zero_rows`. Its existing future rows are kept and it is named. This protects a dead id on the very first run and on every run after, until the rows age out or the id is fixed.

- [ ] **Step 1: Copy liveness, add markers, create empty state**

```bash
cp ../../Accelerators/packages/liveness/src/liveness.py scripts/liveness.py
mkdir -p data && printf '{}\n' > data/refresh_state.json
```

Uncomment the `from liveness import Result, check_max_date, run_checks` line in `refresh_concerts.py`.

In `index.html` line 1321 change

```html
  <div class="last-updated">Data refreshed: March 31, 2026 &bull; 399 shows across 19 venues</div>
```
to
```html
  <div class="last-updated"><!--LAST_REFRESH:START-->Data refreshed: June 2, 2026 &bull; 23 upcoming shows across 19 venues<!--LAST_REFRESH:END--></div>
```

In `tests/test_index_html_integrity.py`:
- add `"Other"` to `KNOWN_GENRES`;
- in `test_dates_in_expected_range`, replace the literal upper bound (`assertLessEqual(d.year, 2027)`) with `assertLessEqual(d.year, date.today().year + 2)` (import `date` if the module does not already), and leave the lower bound as it is;
- add:

```python
    def test_refresh_markers_present_once(self):
        src = (ROOT / "index.html").read_text(encoding="utf-8")
        self.assertEqual(src.count("<!--LAST_REFRESH:START-->"), 1)
        self.assertEqual(src.count("<!--LAST_REFRESH:END-->"), 1)
```

- [ ] **Step 2: Write the failing tests (E11 to E17, E12b)**

Append to `tests/test_refresh_concerts.py`:

```python
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
```

Add `import contextlib` to the test file's imports.

- [ ] **Step 3: Run to verify they fail**

Run: `python3 -m unittest tests.test_refresh_concerts.TestRunEndToEnd -v`
Expected: 11 errors (`run`, `stamp_text` missing).

- [ ] **Step 4: Implement render, rewrite, state, run, main**

Add to `scripts/refresh_concerts.py`:

```python
STATE_PATH = ROOT / "data" / "refresh_state.json"
VENUES_PATH = ROOT / "scripts" / "venues.json"
INDEX_PATH = ROOT / "index.html"
MARK_START = "<!--LAST_REFRESH:START-->"
MARK_END = "<!--LAST_REFRESH:END-->"
THIN_FEED_RATIO = 0.5
MIN_FUTURE_ROWS = 20
MIN_HORIZON_DAYS = 60


def render_concerts_block(rows: list[dict]) -> str:
    lines = ["["]
    current = None
    for r in rows:
        ym = r["date"][:7]
        if ym != current:
            y, m = ym.split("-")
            lines.append(f"  // ── {calendar.month_name[int(m)].upper()} {y} ──")
            current = ym
        lines.append(render_row(r))
    lines.append("]")
    return "\n".join(lines)


def stamp_text(today: date, future_rows: int, venue_count: int) -> str:
    return f"Data refreshed: {today.strftime('%B')} {today.day}, {today.year} &bull; {future_rows} upcoming shows across {venue_count} venues"


def rewrite_index(src: str, rows: list[dict], stamp: str) -> str:
    m = wd.CONCERTS_RE.search(src)
    if not m:
        raise ValueError("const CONCERTS = [ not found")
    open_idx = m.end() - 1
    old = wd._extract_array(src, open_idx)
    out = src[:open_idx] + render_concerts_block(rows) + src[open_idx + len(old):]
    if out.count(MARK_START) != 1 or out.count(MARK_END) != 1:
        raise ValueError("refresh markers missing or duplicated")
    pre, rest = out.split(MARK_START)
    _, post = rest.split(MARK_END)
    return pre + MARK_START + stamp + MARK_END + post


def load_state(path: Path) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8") or "{}")


def _atomic_write(path: Path, text: str) -> None:
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=path.name, suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, path)


def save_state(path: Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write(path, json.dumps(state, indent=2, sort_keys=True) + "\n")


def _load_rows(path: Path) -> list[dict]:
    """weekly_digest.load_data exits the process on a parse failure; turn that into ValueError."""
    try:
        rows, _ = wd.load_data(path)
    except SystemExit as e:
        raise ValueError(f"load_data exited {e.code}") from None
    return rows


def run(index_path: Path, venues_path: Path, state_path: Path, key: str, today: date, now: datetime,
        http: Callable[[str], dict] = urlopen_json, dry_run: bool = False, accept_thin: bool = False) -> tuple[int, dict]:
    try:
        state = load_state(state_path)
    except (OSError, json.JSONDecodeError) as e:
        state = {}
        print(f"WARN: state file unreadable, starting from empty: {e}", file=sys.stderr)
    stamp_now = now.isoformat(timespec="seconds")
    today_iso = today.isoformat()
    summary: dict = {"today": today_iso, "per_venue": {}, "failed_venues": [], "uncovered_venues": [], "venue_seen": {}}

    def fail(code: int, status: str, msg: str) -> tuple[int, dict]:
        state.update(last_attempt_at=stamp_now, last_attempt_status=status)
        if not dry_run:
            save_state(state_path, state)
        summary.update(exit_code=code, status=status, error=msg)
        print(f"ERROR: {msg}", file=sys.stderr)
        return code, summary

    if not key:
        return fail(3, "config", "TM_DISCOVERY_API_KEY missing (set it in .env)")
    if not index_path.exists():
        return fail(1, "config", f"{index_path} missing")
    try:
        venues = load_venues(venues_path)
    except (OSError, ValueError, json.JSONDecodeError) as e:
        return fail(3, "config", f"venues.json unreadable: {e}")
    try:
        existing = _load_rows(index_path)
    except (ValueError, json.JSONDecodeError) as e:
        return fail(2, "parse", f"CONCERTS unparseable: {e}")

    existing_future_venues = {r["venue"] for r in existing if r["date"] >= today_iso}
    fetched: dict[str, list[dict]] = {}
    failed: dict[str, str] = {}  # venue → reason
    uncovered = {v["name"] for v in venues if not v["tmVenueIds"]}
    for v in venues:
        if v["name"] in uncovered:
            continue
        try:
            rows = fetch_venue_events(v, key, today, now, http=http, seen=summary["venue_seen"])
        except Exception as e:  # any fetch error isolates to this venue
            failed[v["name"]] = "fetch"
            summary["per_venue"][v["name"]] = None
            print(f"WARN: {v['name']} fetch failed: {e}", file=sys.stderr)
            continue
        if not rows and v["name"] in existing_future_venues:
            # The feed says "nothing upcoming" for a room that index.html still lists shows at.
            # A dead or renamed venue id looks exactly like this; keep the rows and say so, every run.
            failed[v["name"]] = "zero_rows"
            summary["per_venue"][v["name"]] = 0
            print(f"WARN: {v['name']} returned 0 rows but index.html has future rows there; keeping them", file=sys.stderr)
            continue
        fetched[v["name"]] = rows
        summary["per_venue"][v["name"]] = len(rows)
    summary["failed_venues"] = [f"{n} ({r})" for n, r in sorted(failed.items())]
    summary["uncovered_venues"] = sorted(uncovered)
    if not fetched:
        return fail(4, "all_failed", "every venue fetch failed")

    future_fetched = sum(len(r) for r in fetched.values())
    prev = int(state.get("future_rows") or 0)
    if prev and future_fetched < THIN_FEED_RATIO * prev and not accept_thin:
        return fail(5, "thin_feed", f"feed returned {future_fetched} future rows, previous run had {prev}; rerun with --accept-thin if this drop is real")

    merged = merge_rows(existing, fetched, set(failed), uncovered, today)
    future_rows = sum(1 for r in merged if r["date"] >= today.isoformat())
    stamp = stamp_text(today, future_rows, len(venues))
    src = index_path.read_text(encoding="utf-8")
    try:
        new_src = rewrite_index(src, merged, stamp)
    except ValueError as e:
        return fail(6, "verify_failed", str(e))

    # Verify before replacing: parse the new text exactly the way the digest will.
    verify_path = index_path.with_suffix(".verify.tmp")
    try:
        verify_path.write_text(new_src, encoding="utf-8")
        parsed = _load_rows(verify_path)
    except (ValueError, json.JSONDecodeError) as e:
        return fail(6, "verify_failed", f"rewritten index.html does not parse: {e}")
    finally:
        verify_path.unlink(missing_ok=True)
    if parsed != merged:
        return fail(6, "verify_failed", "rewritten rows differ from merged rows after a parse round-trip")

    summary.update(future_rows=future_rows, rows_total=len(merged), stamp=stamp)
    if dry_run:
        summary.update(exit_code=0, status="dry_run")
        return 0, summary

    _atomic_write(index_path, new_src)
    state.update(last_success_at=stamp_now, last_attempt_at=stamp_now, last_attempt_status="ok",
                 future_rows=future_rows, per_venue=summary["per_venue"], failed_venues=summary["failed_venues"])
    save_state(state_path, state)

    future_dates = [r["date"] for r in merged if r["date"] >= today.isoformat()]
    with contextlib.redirect_stdout(sys.stderr):  # liveness prints PASS/FAIL lines; keep stdout for the JSON summary
        code = run_checks([
            lambda: check_max_date(future_dates, -MIN_HORIZON_DAYS, today=today),
            lambda: _check_floor(future_rows),
        ])
    if code != 0:
        state.update(last_attempt_status="liveness_failed")
        save_state(state_path, state)
        summary.update(exit_code=1, status="liveness_failed")
        return 1, summary
    summary.update(exit_code=0, status="ok")
    return 0, summary


def _check_floor(future_rows: int) -> Result:
    ok = future_rows >= MIN_FUTURE_ROWS
    return Result(ok, "future_rows_floor", f"{future_rows} >= {MIN_FUTURE_ROWS}" if ok else f"only {future_rows} future rows")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Refresh CONCERTS from the Ticketmaster Discovery API")
    p.add_argument("--dry-run", action="store_true", help="fetch and report, write nothing")
    p.add_argument("--as-of", default=None, help="override today (YYYY-MM-DD)")
    p.add_argument("--accept-thin", action="store_true", help="skip the thin-feed guard once (a real drop, e.g. a venue left Ticketmaster)")
    args = p.parse_args(argv)
    wd.load_env_file(ROOT / ".env")
    key = os.environ.get("TM_DISCOVERY_API_KEY", "").strip()
    now = datetime.now(TZ)
    today = date.fromisoformat(args.as_of) if args.as_of else now.date()
    code, summary = run(INDEX_PATH, VENUES_PATH, STATE_PATH, key, today, now, dry_run=args.dry_run, accept_thin=args.accept_thin)
    print(json.dumps(summary, indent=2, sort_keys=True))
    return code


if __name__ == "__main__":
    sys.exit(main())
```

`check_max_date(dates, max_age_days, today)` computes `age = today - newest` and passes when `age <= max_age_days`. With `-60`, it passes only when the newest date is at least 60 days out. Confirmed against `scripts/liveness.py:101-111`.

- [ ] **Step 5: Run to verify they pass**

Run: `python3 -m unittest tests.test_refresh_concerts -v && python3 -m unittest tests.test_index_html_integrity -v`
Expected: 28 refresh tests OK; integrity suite OK including `test_refresh_markers_present_once`.

- [ ] **Step 6: Dry run against the live API once, and check every id is an LA room**

Run: `python3 scripts/refresh_concerts.py --dry-run 2>/tmp/refresh_err.txt | python3 -c "import json,sys; d=json.load(sys.stdin); print(d['status'], d['future_rows'], d['failed_venues']); print(d['per_venue']); [print(k, '->', v) for k, v in d['venue_seen'].items()]"; cat /tmp/refresh_err.txt`
Expected: `dry_run <150..700> []`, 19 venue counts, and 20 `venue_seen` lines whose city is one of Los Angeles, Hollywood, West Hollywood, Inglewood, Pasadena. Any other city (Berkeley, Chico, Albuquerque) means a mis-resolved id: fix it in `venues.json` before continuing. Takes 10 to 20 seconds. On this first dry run `zero_rows` can legitimately appear for a venue whose June rows are in the future but whose Ticketmaster calendar is empty (the Hollywood Bowl in winter is the likely one); that is the guard working, not a bug, and it clears as those rows pass.

- [ ] **Step 7: Commit**

```bash
git add scripts/refresh_concerts.py scripts/liveness.py data/refresh_state.json index.html tests/test_index_html_integrity.py tests/test_refresh_concerts.py
git commit -m "feed: guards, zero-rows rule, atomic verified write, state file, liveness, CLI"
```

---

### Task 5: Matcher precision, Python and JS

**Files:**
- Modify: `scripts/weekly_digest.py:231-257` and the three call sites at lines 333, 370 and 391
- Modify: `index.html:2305-2306`, every `isWatchedArtist(` call site (six, all `isWatchedArtist(ev.name)`), and `getMatchingConcerts` at line 2450
- Rewrite: `tests/js_matcher_parity.js`
- Modify: `tests/test_weekly_digest.py`

**Interfaces:**
- Produces (Python): `is_watched_artist(name: str, watchlist_normalized: list[str], artists: list[str] | None = None) -> bool`, `matched_watchlist_names(name: str, watchlist: list[str], artists: list[str] | None = None) -> list[str]`.
- Produces (JS): `function artistMatches(name, artists, watchTerms)` pure; `isWatchedArtist(n, artists)` delegates to it with `trackedArtists`; `getMatchingConcerts` uses it.
- Rule: with non-empty `artists`, exact normalized equality against any attraction. Otherwise substring either way, only for watch terms of 5+ normalized chars.

- [ ] **Step 1: Write the failing Python tests (E18, E19)**

Append to `tests/test_weekly_digest.py`:

```python
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
        self.assertIn("Polo & Pan", d["per_artist"])
        self.assertIn("Empire of the Sun", d["per_artist"])
        self.assertNotIn("Flume", d["per_artist"])
        self.assertEqual(d["totals"]["artists_with_shows"], 2)
```

Check the real key name for the roster in `build_digest`'s return (`grep -n "artists_with_shows\|per_artist\|roster" scripts/weekly_digest.py`) and use it in the test.

- [ ] **Step 2: Run to verify it fails**

Run: `python3 -m unittest tests.test_weekly_digest.TestMatcherPrecision -v`
Expected: FAIL on the `Dave` / `Dave Hause` case and on the roster test.

- [ ] **Step 3: Implement in Python**

Replace `is_watched_artist` and `matched_watchlist_names` in `scripts/weekly_digest.py`:

```python
MIN_LEGACY_TERM = 5  # substring matching on bare names needs 5+ normalized chars ("dave" is 4)


def _term_hits(cn: str, an: str, artists_normalized: list[str]) -> bool:
    if artists_normalized:
        return an in artists_normalized
    if len(an) < MIN_LEGACY_TERM:
        return cn == an
    return cn == an or an in cn or cn in an


def is_watched_artist(name: str, watchlist_normalized: list[str], artists: list[str] | None = None) -> bool:
    cn = normalize_for_match(name)
    arts = [normalize_for_match(a) for a in (artists or []) if normalize_for_match(a)]
    if not cn and not arts:
        return False
    return any(an and _term_hits(cn, an, arts) for an in watchlist_normalized)


def matched_watchlist_names(name: str, watchlist: list[str], artists: list[str] | None = None) -> list[str]:
    cn = normalize_for_match(name)
    arts = [normalize_for_match(a) for a in (artists or []) if normalize_for_match(a)]
    if not cn and not arts:
        return []
    return [a for a in watchlist if normalize_for_match(a) and _term_hits(cn, normalize_for_match(a), arts)]
```

Then fix the three call sites in `build_digest`:
- line 333 `matched_watchlist_names(name, wishlist)` → `matched_watchlist_names(name, wishlist, artists=c.get("artists"))`
- line 370 `is_watched_artist(name, watchlist_norm)` → `is_watched_artist(name, watchlist_norm, artists=c.get("artists"))`
- line 391 `matched_watchlist_names(h.name, wishlist)` re-matches on the event name alone and loses `artists`. Replace that loop so the roster is built from the names already matched on the hits **before** deduplication: `watch_hits` (line 335) holds one `WatchHit` per (concert, matched artist) and `dedup_watch` collapses them per show, keeping only the first artist. Iterate `watch_hits`, not `dedup_watch`, and credit `h.watchlist_artist` (check the dataclass field name at line 283). A show matching two watched artists (Empire of the Sun with Polo & Pan) must credit both.

- [ ] **Step 4: Run Python tests**

Run: `python3 -m unittest tests.test_weekly_digest -v`
Expected: all OK.

- [ ] **Step 5: Implement in JS**

Replace `index.html` lines 2305-2306 with:

```js
function normalizeForMatch(s) { return s.toLowerCase().replace(/[\s\.\-&''']/g, '').replace(/[^a-z0-9]/g, ''); }
var MIN_LEGACY_TERM = 5;
function artistMatches(name, artists, watchTerms) {
  var cn = normalizeForMatch(name || '');
  var arts = (artists || []).map(normalizeForMatch).filter(Boolean);
  if (!cn && !arts.length) return false;
  return watchTerms.some(function(a) {
    var an = normalizeForMatch(a);
    if (!an) return false;
    if (arts.length) return arts.indexOf(an) !== -1;
    if (an.length < MIN_LEGACY_TERM) return cn === an;
    return cn === an || cn.includes(an) || an.includes(cn);
  });
}
function isWatchedArtist(n, artists) { return artistMatches(n, artists, trackedArtists); }
```

Then `grep -n "isWatchedArtist(" index.html` and change each of the six `isWatchedArtist(ev.name)` to `isWatchedArtist(ev.name, ev.artists)`.

Then `grep -n "includes(an)" index.html`: the remaining hit is inside `getMatchingConcerts` (line 2450), which filters concerts for one artist `a` with an inline `cn===an||cn.includes(an)||an.includes(cn)`. Replace that expression with `artistMatches(c.name, c.artists, [a])` where `c` is the concert variable in that function. After the edit, `grep -c "includes(an)" index.html` must print `1` (the one inside `artistMatches`).

- [ ] **Step 6: Rewrite the parity test (E20)**

`tests/js_matcher_parity.js` currently mirrors `normalizeForMatch` by hand and checks nine strings. Replace it with a version that extracts the real functions from `index.html` and runs both the nine normalizer cases and the shared matcher cases:

```js
#!/usr/bin/env node
// Parity: the matcher in index.html must agree with Python on tests/fixtures/matcher_cases.json.
// Also keeps the original normalizer parity cases. Functions are extracted from index.html itself.
'use strict';
const fs = require('fs');
const path = require('path');
const ROOT = path.resolve(__dirname, '..');
const html = fs.readFileSync(path.join(ROOT, 'index.html'), 'utf8');

function extract(fnName) {
  const start = html.indexOf('function ' + fnName + '(');
  if (start === -1) { console.error('could not find ' + fnName); process.exit(1); }
  let depth = 0, i = html.indexOf('{', start);
  for (; i < html.length; i++) {
    if (html[i] === '{') depth++;
    else if (html[i] === '}') { depth--; if (depth === 0) break; }
  }
  return html.slice(start, i + 1);
}
const lib = new Function(extract('normalizeForMatch') + '\nvar MIN_LEGACY_TERM = 5;\n' + extract('artistMatches') +
  '\nreturn {normalizeForMatch: normalizeForMatch, artistMatches: artistMatches};')();

const normCases = [
  ['J. Cole', 'jcole'], ["Barry Can't Swim", 'barrycantswim'], ['A$AP Rocky', 'aaprocky'],
  ['Jack Harlow', 'jackharlow'], ['JUNGLE', 'jungle'], ['Tame Impala', 'tameimpala'],
  ['Fred Again..', 'fredagain'], ['', ''], ['   ..', ''],
];
let ok = 0, total = 0;
for (const [input, want] of normCases) {
  total++; const got = lib.normalizeForMatch(input);
  if (got === want) ok++; else console.error('normalizer mismatch', JSON.stringify(input), got, want);
}
const cases = JSON.parse(fs.readFileSync(path.join(__dirname, 'fixtures', 'matcher_cases.json'), 'utf8'));
for (const c of cases) {
  total++; const got = lib.artistMatches(c.name, c.artists, [c.watch]);
  if (got === c.expect) ok++; else console.error('matcher mismatch', JSON.stringify(c), 'got', got);
}
console.log(`JS/Python matcher parity: ${ok}/${total} cases match.`);
process.exit(ok === total ? 0 : 1);
```

The brace-counting extractor is fine here because neither function contains a `{` or `}` inside a string or regex literal; the `normalizeForMatch` regex uses character classes only.

- [ ] **Step 7: Run everything**

Run: `bash tests/run_all.sh`
Expected: Python suites OK, smoke ok, `JS/Python matcher parity: 20/20 cases match.`, `All tests passed.`

- [ ] **Step 8: Commit**

```bash
git add scripts/weekly_digest.py index.html tests/js_matcher_parity.js tests/test_weekly_digest.py
git commit -m "matcher: exact on Ticketmaster attractions, 5-char floor on legacy substring rule, all call sites"
```

---

### Task 6: Digest: New since, data age, state write

**Files:**
- Modify: `scripts/weekly_digest.py` (`build_digest`, `render_text`, `render_html`, `main`)
- Modify: `tests/test_weekly_digest.py`

**Interfaces:**
- Consumes: `data/refresh_state.json` via a new `load_refresh_state(path: Path) -> dict | None` (None when missing), `scripts/venues.json` via `load_venue_tiers(path: Path) -> dict[str, int]`.
- Produces: `build_digest(concerts, wishlist, today, horizon_days, onsale_days, state: dict | None = None, tiers: dict[str, int] | None = None)` adds two keys to the digest dict:
  - `"feed": {"status": "ok"|"stale"|"failed"|"missing"|"bootstrap", "age_days": int | None, "line": str}`
  - `"new_since": None | {"since": "<ISO timestamp>", "shows": [dicts with date, name, venue, support, ticket_url, on_sale_date, presale_date, watched], "onsales": [same]}`
- The cutoff for "new" is `state["last_digest_covered_through"]`: the `last_success_at` of the refresh whose rows the previous digest showed. A row is new when `firstSeen > covered_through` (both ISO timestamps with the same offset, so string comparison is time order). A refresh run by hand on a Sunday afternoon therefore still counts as new the following week. Bootstrap means the key is absent.
- The feed line names, whenever present: STALE (10+ days), a failed last attempt, non-empty `failed_venues`, `last_tests_status != "ok"`, `last_push_status != "ok"`, `last_refresh_rc` not `"0"` (the refresh script crashed or exited non-zero without recording an attempt), and `last_attempt_at` older than 2 days (no refresh ran this week, which is what the Cowork task still on the old prompt looks like).
- `main` gains `--state` (default `data/refresh_state.json`) and `--venues` (default `scripts/venues.json`), and after a successful `--email` send writes `state["last_digest_at"] = now` and `state["last_digest_covered_through"] = state.get("last_success_at", "")`.
- Text section header: `── NEW SINCE Oct 19 ──` (the date part of the cutoff). Feed line is the first line under the title block in both text and HTML.

- [ ] **Step 1: Write the failing tests (E21 to E25)**

Append to `tests/test_weekly_digest.py`:

```python
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
```

Before running, print the current text render once to pin the line index in E24: `python3 scripts/weekly_digest.py --text | head -6`. Today the title is line 1, the `===` rule line 2, a blank line 3, so the feed line goes on the fourth line (index 3). Adjust the index if the header differs.

- [ ] **Step 2: Run to verify they fail**

Run: `python3 -m unittest tests.test_weekly_digest.TestNewSinceAndFeedLine -v`
Expected: 5 errors (`build_digest() got an unexpected keyword argument 'state'`).

- [ ] **Step 3: Implement**

In `scripts/weekly_digest.py`:

```python
STALE_AFTER_DAYS = 10
NOTABLE_TIER_MIN = 3
NEW_SHOWS_CAP = 15


def load_refresh_state(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8") or "{}")
    except json.JSONDecodeError:
        return None


def load_venue_tiers(path: Path) -> dict[str, int]:
    try:
        return {v["name"]: int(v["tier"]) for v in json.loads(path.read_text(encoding="utf-8"))}
    except (OSError, ValueError, KeyError):
        return {}


def _feed_status(state: dict | None, today: date) -> dict:
    if state is None:
        return {"status": "missing", "age_days": None,
                "line": "Data refresh state missing: this digest ran on whatever index.html holds."}
    ok_at = state.get("last_success_at")
    if not ok_at:
        return {"status": "failed", "age_days": None,
                "line": "No successful data refresh recorded yet; last refresh attempt failed "
                        f"({state.get('last_attempt_status', 'unknown')})."}
    age = (today - datetime.fromisoformat(ok_at).date()).days
    rows = state.get("future_rows")
    rows_txt = f" ({rows} upcoming shows)" if rows is not None else ""
    if age >= STALE_AFTER_DAYS:
        status, line = "stale", f"STALE: data refreshed {age} days ago{rows_txt}."
    else:
        unit = "day" if age == 1 else "days"
        status, line = "ok", f"Data refreshed {age} {unit} ago{rows_txt}."
    notes = []
    if state.get("last_attempt_status", "ok") != "ok":
        notes.append(f"last refresh attempt failed ({state.get('last_attempt_status')})")
    if str(state.get("last_refresh_rc", "0")) != "0":
        notes.append(f"refresh exited {state['last_refresh_rc']} without recording a result")
    attempt_at = state.get("last_attempt_at")
    if attempt_at and (today - datetime.fromisoformat(attempt_at).date()).days > 2:
        notes.append("no refresh attempt in the last 2 days")
    if state.get("failed_venues"):
        notes.append("venues not refreshed: " + ", ".join(state["failed_venues"]))
    if state.get("last_tests_status", "ok") != "ok":
        notes.append("tests failed after the last refresh, data rolled back to the previous week")
    if state.get("last_push_status", "ok") not in ("ok", "skipped"):
        notes.append("site push failed, the web page may be behind this email")
    if notes:
        status = "failed"
        line += " Note: " + "; ".join(notes) + "."
    if not state.get("last_digest_covered_through"):
        status = "bootstrap"
        line += f" Feed connected {ok_at[:10]}: {rows} upcoming shows loaded."
    return {"status": status, "age_days": age, "line": line}
```

Inside `build_digest`, dates are parsed inline with `date.fromisoformat(c["date"])` (line 326). After `watch_hits` are computed and before the return, add:

```python
    feed = _feed_status(state, today)
    new_since = None
    since = (state or {}).get("last_digest_covered_through")  # ISO timestamp of the refresh the last digest showed
    if since:
        wl_norm = [normalize_for_match(a) for a in wishlist]
        tiers = tiers or {}
        shows, onsales = [], []
        for c in concerts:
            try:
                d = date.fromisoformat(c["date"])
            except ValueError:
                continue
            if d < today:
                continue
            watched = is_watched_artist(c["name"], wl_norm, artists=c.get("artists"))
            entry = {"date": c["date"], "name": c["name"], "venue": c["venue"], "support": c.get("support", ""),
                     "ticket_url": c.get("ticketUrl", ""), "on_sale_date": c.get("onSaleDate", ""),
                     "presale_date": c.get("presaleDate", ""), "watched": watched}
            fs = c.get("firstSeen") or ""
            if fs > since and (watched or tiers.get(c["venue"], 0) >= NOTABLE_TIER_MIN):
                shows.append(entry)
            os_dt = parse_sale_date(c.get("onSaleDate", ""))
            if os_dt and since[:10] < os_dt.date().isoformat() <= today.isoformat():
                onsales.append(entry)
        key = lambda e: (not e["watched"], e["date"], e["name"].lower())
        shows.sort(key=key); onsales.sort(key=key)
        shows = [s for s in shows if s["watched"]] + [s for s in shows if not s["watched"]][:NEW_SHOWS_CAP]
        new_since = {"since": since, "shows": shows, "onsales": onsales}
```

Add `"feed": feed, "new_since": new_since` to the returned dict and `state: dict | None = None, tiers: dict[str, int] | None = None` to the signature.

In `render_text`, after the title and `===` line and the blank line, insert `out.append(digest["feed"]["line"])`, then before the WATCHLIST section:

```python
    ns = digest.get("new_since")
    if ns and (ns["shows"] or ns["onsales"]):
        since_label = date.fromisoformat(ns["since"][:10]).strftime("%b %-d")  # 'Oct 19'
        out.append(f"── NEW SINCE {since_label} ──")
        for s in ns["shows"]:
            tag = "★ " if s["watched"] else "  "
            out.append(f"  {tag}{_fmt_date(s['date'])} — {s['name']} @ {s['venue']}")
        for s in ns["onsales"]:
            out.append(f"  {'★ ' if s['watched'] else '  '}ON SALE {_fmt_sale(s['on_sale_date'])}: {s['name']} @ {s['venue']} ({_fmt_date(s['date'])})")
        out.append("")
```

`%-d` is the glibc/macOS no-padding day flag and matches the existing `main` subject line (`%B %-d, %Y`). The `—` inside list lines is the existing digest row style; the no-em-dash rule applies to prose.

In `render_html`, add `<div class='feed'>{escape(digest['feed']['line'])}</div>` right after the `<div class='sub'>` line, with inline style `color:#b00020;font-weight:600` when `digest['feed']['status'] in ('stale', 'failed')`, and a `<h2>New since {since_label}</h2>` section mirroring the text version (★ as a `pill` for watched), placed before the Watchlist `<h2>`.

In `main`: add `p.add_argument("--state", default=str(ROOT / "data" / "refresh_state.json"))` and `p.add_argument("--venues", default=str(ROOT / "scripts" / "venues.json"))` (define `ROOT = Path(__file__).resolve().parent.parent` near the top if the file does not already have it); load both with `load_refresh_state` / `load_venue_tiers` and pass them to `build_digest`. After the SMTP send succeeds (`email["sent"] is True`):

```python
        st = load_refresh_state(Path(args.state)) or {}
        st["last_digest_at"] = datetime.now(TZ).isoformat(timespec="seconds")
        st["last_digest_covered_through"] = st.get("last_success_at", "")
        Path(args.state).parent.mkdir(parents=True, exist_ok=True)
        Path(args.state).write_text(json.dumps(st, indent=2, sort_keys=True) + "\n", encoding="utf-8")
```

`last_digest_covered_through` records which refresh this email showed, so next week's "new" is everything the feed first saw after that refresh, including a hand-run refresh later the same Sunday.

- [ ] **Step 4: Run all tests**

Run: `bash tests/run_all.sh`
Expected: all OK. The smoke run (`--as-of 2026-04-20`) now reads the real `data/refresh_state.json`; with `{}` it reports "No successful data refresh recorded yet", which is correct until Task 9.

- [ ] **Step 5: Commit**

```bash
git add scripts/weekly_digest.py tests/test_weekly_digest.py
git commit -m "digest: New since section, data-age line naming every failure class, digest coverage state"
```

---

### Task 7: UI: year navigation and header year

**Files:**
- Modify: `index.html:7`, `index.html:1318`, `index.html:1986`, `index.html:2481-2482`, `renderCalendar` (around 2462)

**Interfaces:** none new. Behaviour: the calendar opens on the current month, `prevMonth`/`nextMonth` cross year boundaries, the header year follows the displayed month.

- [ ] **Step 1: Make the start month dynamic**

Line 1986 `let currentMonth = 3, currentYear = 2026, currentView = 'calendar';` becomes:

```js
var _today = new Date();
let currentMonth = _today.getMonth(), currentYear = _today.getFullYear(), currentView = 'calendar';
```

- [ ] **Step 2: Cross years**

Lines 2481-2482 become:

```js
function prevMonth(){ if(currentMonth===0){currentMonth=11;currentYear--;} else {currentMonth--;} renderCalendar(); }
function nextMonth(){ if(currentMonth===11){currentMonth=0;currentYear++;} else {currentMonth++;} renderCalendar(); }
```

- [ ] **Step 3: Header year follows the month**

Give the header span an id: `<span class="header-year" id="headerYear">2026</span>`. In `renderCalendar`, as its first statement: `var hy=document.getElementById('headerYear'); if(hy) hy.textContent=currentYear;`. Change `<title>LA Concerts 2026</title>` to `<title>LA Concerts</title>`.

- [ ] **Step 4: Verify in the browser**

Run: `python3 -m http.server 8011` from the project root, open `http://localhost:8011/`, click next-month past December. Expected: January 2027 renders, header year reads 2027, no console errors. Stop the server.

- [ ] **Step 5: Run tests and commit**

```bash
bash tests/run_all.sh && git add index.html && git commit -m "ui: calendar crosses years, header year follows the view"
```

---

### Task 8: Wrapper script, scheduled-task prompt, docs

**Files:**
- Create: `scripts/weekly_run.sh`
- Modify: `tests/run_all.sh`, `.gitignore` (add `logs/`)
- Modify: `../../Scheduled/weekly-concert-email/SKILL.md`
- Modify: `docs/agent/QUICKSTART.md`, `docs/agent/RUNBOOK.md`, `docs/agent/DECISIONS.md`

**Interfaces:**
- `scripts/weekly_run.sh` env overrides for tests: `REFRESH_CMD`, `TESTS_CMD`, `DIGEST_CMD`, `DIGEST_ARGS`, `SKIP_GIT=1`. Exit code = the digest's exit code.
- Log lines on stdout and appended to `logs/weekly_run.log`: `refresh: ok|failed(N)|skipped`, `tests: ok|failed`, `git: pushed|nothing to commit|failed|skipped`, `digest: exit N`.
- State keys the wrapper writes into `data/refresh_state.json`: `last_refresh_rc` (the refresh script's exit code as a string, every run, so a crash that never reached `run()`'s own state write is still visible), `last_tests_status` (`ok | tests_failed`), `last_push_status` (`ok | failed | skipped`). On a test failure it restores `index.html` from HEAD and rebuilds the state as: HEAD's state, plus the working tree's `last_digest_at` and `last_digest_covered_through`, plus `last_tests_status: "tests_failed"` and the refresh rc. It never restores the state file wholesale.

- [ ] **Step 1: Write the wrapper**

`scripts/weekly_run.sh`:

```bash
#!/usr/bin/env bash
# Weekly LA Concert run: refresh data from Ticketmaster, test, commit+push, send the digest.
# The digest ALWAYS runs. A refresh, test or push failure is recorded in data/refresh_state.json
# so the email names it; none of them is fatal.
# Env overrides (tests only): REFRESH_CMD, TESTS_CMD, DIGEST_CMD, DIGEST_ARGS, SKIP_GIT=1
set -u
cd "$(dirname "$0")/.."
mkdir -p logs
LOG="logs/weekly_run.log"
STATE="data/refresh_state.json"
log() { echo "$(date '+%Y-%m-%d %H:%M:%S') $*" | tee -a "$LOG"; }

# set_state KEY VALUE: merge one string key into the state file (creates it if missing).
set_state() {
  python3 - "$STATE" "$1" "$2" <<'PY'
import json, sys, pathlib
p = pathlib.Path(sys.argv[1]); st = json.loads(p.read_text() or "{}") if p.exists() else {}
st[sys.argv[2]] = sys.argv[3]
p.parent.mkdir(parents=True, exist_ok=True); p.write_text(json.dumps(st, indent=2, sort_keys=True) + "\n")
PY
}

log "run start · $(python3 --version 2>&1) · node $(node --version 2>&1 || echo missing) · $(git remote get-url origin 2>/dev/null || echo 'no remote')"

if [ "${SKIP_GIT:-0}" != "1" ]; then
  git pull --ff-only >>"$LOG" 2>&1 || log "git: pull failed (continuing on local data)"
fi

refresh_status="ok"
if eval "${REFRESH_CMD:-python3 scripts/refresh_concerts.py}" >>"$LOG" 2>&1; then
  log "refresh: ok"; set_state last_refresh_rc 0
else
  rc=$?; refresh_status="failed"; log "refresh: failed($rc)"; set_state last_refresh_rc "$rc"
fi

if [ "$refresh_status" = "ok" ]; then
  if eval "${TESTS_CMD:-bash tests/run_all.sh}" >>"$LOG" 2>&1; then
    log "tests: ok"; set_state last_tests_status ok
    if [ "${SKIP_GIT:-0}" != "1" ]; then
      git add index.html "$STATE" >>"$LOG" 2>&1
      if git diff --cached --quiet; then
        log "git: nothing to commit"; set_state last_push_status ok
      elif git commit -q -m "data: weekly refresh $(date '+%Y-%m-%d')" >>"$LOG" 2>&1 && git push -q >>"$LOG" 2>&1; then
        log "git: pushed"; set_state last_push_status ok
      else
        log "git: failed (site not updated; digest still sends)"; set_state last_push_status failed
      fi
    else
      set_state last_push_status skipped
    fi
  else
    log "tests: failed · restoring index.html from HEAD, keeping evidence in state"
    git checkout -- index.html 2>>"$LOG" || log "git: restore failed"
    # Rebuild state: HEAD's success fields + the working tree's last_digest_date + the failure flag.
    python3 - "$STATE" <<'PY' >>"$LOG" 2>&1 || log "state: rebuild failed"
import json, subprocess, sys, pathlib
p = pathlib.Path(sys.argv[1])
cur = json.loads(p.read_text() or "{}") if p.exists() else {}
try:
    head = json.loads(subprocess.check_output(["git", "show", f"HEAD:{p.as_posix()}"], text=True) or "{}")
except subprocess.CalledProcessError:
    head = {}
for k in ("last_digest_at", "last_digest_covered_through", "last_refresh_rc"):
    if cur.get(k):
        head[k] = cur[k]
head["last_tests_status"] = "tests_failed"
p.write_text(json.dumps(head, indent=2, sort_keys=True) + "\n")
PY
  fi
fi

eval "${DIGEST_CMD:-python3 scripts/weekly_digest.py --horizon-days 180 --onsale-days 14 --email ${DIGEST_ARGS:-}}" >>"$LOG" 2>&1
drc=$?
log "digest: exit $drc"
exit $drc
```

`chmod +x scripts/weekly_run.sh`. Add `logs/` to `.gitignore`.

Why the state is rebuilt rather than restored: HEAD's state is always a week behind on the digest keys (the digest writes them after the commit), so a plain `git checkout` would make the next "New since" block repeat last week's items, and it would erase every trace of the failed run.

- [ ] **Step 2: Add E26 and E27 to `run_all.sh`**

Append before the final `echo "All tests passed."`:

```bash
echo ""
echo "== Wrapper: refresh failure never blocks the digest (E26) =="
scratch=$(mktemp -d); git clone -q . "$scratch/clone"; cp scripts/weekly_run.sh "$scratch/clone/scripts/weekly_run.sh"
out=$(cd "$scratch/clone" && REFRESH_CMD=false TESTS_CMD=true DIGEST_CMD="exit 7" SKIP_GIT=1 bash scripts/weekly_run.sh; echo "rc=$?")
echo "$out" | grep -q "refresh: failed" && echo "$out" | grep -q "rc=7" \
  && python3 -c "import json; s=json.load(open('$scratch/clone/data/refresh_state.json')); assert s['last_refresh_rc']=='1', s" \
  && echo "E26 ok" || { echo "E26 FAIL: $out"; exit 1; }

echo "== Wrapper: failed tests restore index.html and record the failure (E27) =="
( cd "$scratch/clone" \
  && printf '{"last_success_at":"2026-01-01T00:00:00-08:00","last_digest_covered_through":"2025-12-25T00:00:00-08:00"}\n' > data/refresh_state.json \
  && git -c user.email=t@t -c user.name=t commit -q -am "seed state" \
  && printf '{"last_success_at":"2026-01-01T00:00:00-08:00","last_digest_covered_through":"2026-01-01T00:00:00-08:00"}\n' > data/refresh_state.json \
  && REFRESH_CMD="echo x >> index.html" TESTS_CMD=false DIGEST_CMD=true SKIP_GIT=1 bash scripts/weekly_run.sh >/dev/null; rc=$? \
  && [ "$rc" = "0" ] && git diff --quiet index.html \
  && python3 -c "import json; s=json.load(open('data/refresh_state.json')); assert s['last_tests_status']=='tests_failed', s; assert s['last_digest_covered_through']=='2026-01-01T00:00:00-08:00', s; assert s['last_refresh_rc']=='0', s" ) \
  && echo "E27 ok" || { echo "E27 FAIL"; exit 1; }
rm -rf "$scratch"
```

The clone gets the working-tree wrapper copied in, so the test exercises the current file, not HEAD's. Run: `bash tests/run_all.sh`. Expected: `E26 ok`, `E27 ok`, `All tests passed.` under 5 seconds (the clone is local).

- [ ] **Step 3: Update the scheduled-task prompt**

Rewrite `../../Scheduled/weekly-concert-email/SKILL.md`:

```markdown
---
name: weekly-concert-email
description: Weekly LA concert run. One command: refresh data from Ticketmaster, test, push, send the digest via Gmail SMTP. Haiku-tier. Updated 2026-10-26.
---

Run one command and report its last four log lines. The script refreshes the data, runs the tests, pushes the site, and sends the email itself.

Step 1 — run this:

```bash
bash "/Users/thomasnendick/Documents/Claude/Projects/LA Concert Tracker/scripts/weekly_run.sh"
```

Step 2 — report the lines that start with `refresh:`, `tests:`, `git:` and `digest:` verbatim, then the exit code.

Exit code is the digest's: 0 sent · 4 SMTP failed. A `refresh: failed`, `tests: failed` or `git: failed` line with exit 0 means the email went out and named the problem in its first line; report it, do not retry.

Rules:
- Do NOT call create_draft. Do NOT run WebSearch, Firecrawl, or Chrome.
- Do NOT modify any file. Do NOT retry on failure.
```

- [ ] **Step 4: Docs**

`docs/agent/QUICKSTART.md`: replace the "Data freshness" section with three lines: data comes from `scripts/refresh_concerts.py` (Ticketmaster Discovery, 19 venues in `scripts/venues.json`), runs inside `scripts/weekly_run.sh` every Sunday, state in `data/refresh_state.json`. Update the row shape line with `tmId, artists, firstSeen`. Add `python3 scripts/refresh_concerts.py --dry-run` and `bash scripts/weekly_run.sh` to common commands. Change the site URL to `https://concerts.thomasnendick.com/` (the `CNAME` on `origin/main` redirects the github.io address there). Point to `docs/agent/specs/concert-feed/`.

`scripts/weekly_digest.py`: change `TRACKER_URL` to `https://concerts.thomasnendick.com/` only after confirming it serves the page: `curl -sIL https://concerts.thomasnendick.com/ | grep -E "^HTTP"` must end in `200`. If it does not, leave the github.io URL and note the broken domain in SESSION-STATE.

`docs/agent/RUNBOOK.md`: replace section 3 "Update concert data" Path B with: run `python3 scripts/refresh_concerts.py`, then tests, commit, push; exit codes table from the script header; "a venue shows `(zero_rows)` or `(fetch)` in the email: its id in `venues.json` is wrong or TM renamed the entity; look it up with `venues.json?keyword=` and check `venue_seen` in a `--dry-run`"; "exit 5 (thin feed) every week after a real drop: `python3 scripts/refresh_concerts.py --accept-thin` once, then the guard re-baselines". Add to section 7: "Symptom: email first line says STALE or Note:" → run the refresh by hand, read stderr, read `logs/weekly_run.log`. Add the `.env` key to the credentials line.

`docs/agent/DECISIONS.md`, append:

```markdown
## 2026-10-26 — Ticketmaster Discovery API replaces the static array

**Decision:** `CONCERTS` future rows come from the Discovery API for the 19 tracked venues, weekly, inside the Sunday task. Past rows stay. Future rows without a Ticketmaster id at a covered venue are dropped. A venue that fails to fetch, or returns zero rows after having rows, keeps its rows and is named in the email.

**Why:** No scraper existed; the data went stale twice (2026-06, 2026-10) and the one remaining watchlist row was a show that did not exist. The API is public, keyed, covers every tracked venue, and returns on-sale and presale times. Scraping-decay route 1: find the real source.

**Tradeoffs:** Only Ticketmaster-listed shows appear. The Hollywood Bowl's LA Phil season may be partly missing (check May 2027). Watchlist artists at untracked venues stay invisible by Thomas's choice (2026-10-25 interview).

**Reversibility:** Delete `scripts/refresh_concerts.py` from `weekly_run.sh`; the array is still a plain literal in `index.html`.

## 2026-10-26 — Matcher: exact on attractions, 5-char floor on substrings

**Decision:** With `artists` present, a watch term matches only by exact normalized equality. Legacy rows keep the substring rule for terms of 5+ normalized characters.

**Why:** "Dave" matched Dave Hause and Dave Koz in the first API probe. Precision over recall: a false hit in the weekly email costs trust, a miss costs one show.

## 2026-10-26 — The email names every failure class

**Decision:** The first line of every digest states data age and appends any of: failed refresh attempt, refresh exited non-zero without recording a result, no refresh attempt in the last 2 days, venues not refreshed, tests failed (data rolled back), site push failed. The wrapper writes the refresh exit code, test and push outcomes into `data/refresh_state.json`; it never restores that file wholesale.

**Why:** The June and October incidents were both "the email kept looking healthy". A rollback that erased its own evidence would recreate that.
```

- [ ] **Step 5: Commit**

```bash
bash tests/run_all.sh && git add scripts/weekly_run.sh scripts/weekly_digest.py tests/run_all.sh .gitignore docs/agent/QUICKSTART.md docs/agent/RUNBOOK.md docs/agent/DECISIONS.md && git commit -m "run: weekly wrapper (refresh, test, push, send) with failure evidence in state; docs"
```

`Scheduled/weekly-concert-email/SKILL.md` lives outside this git repo (the workspace root is not a repository); it is saved, not committed.

---

### Task 9: End-to-end: first real refresh, push, test send

This is the spec's verification step. Network and email are involved; run it by hand, read every output.

- [ ] **Step 0: Confirm git is clean and ahead only**

Task 0 already fast-forwarded and committed the June work. Confirm: `git branch -vv | head -1` shows `[origin/main: ahead N]` with no `behind`, and `git status --short` shows nothing staged. If `behind` appears, someone pushed meanwhile: `git pull --rebase` and rerun `bash tests/run_all.sh` before continuing.

- [ ] **Step 1: First real refresh**

```bash
python3 scripts/refresh_concerts.py > /tmp/refresh_summary.json 2>/tmp/refresh_err.txt; echo "exit=$?"; python3 -c "import json; d=json.load(open('/tmp/refresh_summary.json')); print(d['status'], 'future_rows', d['future_rows'], 'failed', d['failed_venues']); print(d['per_venue']); [print(k, '->', v) for k, v in d['venue_seen'].items()]"; cat /tmp/refresh_err.txt
```

Expected: `exit=0`, `ok future_rows <150..700>`, 19 venue counts, `venue_seen` cities all in the LA set, stderr shows two `PASS` lines from liveness. `failed_venues` may legitimately hold `(zero_rows)` entries for venues whose June hand-entered rows are still in the future but whose Ticketmaster calendar is empty today; those rows are kept and named, and the entries clear as the rows pass. A `(fetch)` entry means a bad id: fix and rerun.

- [ ] **Step 2: Tests, inspect, commit, push (commit only if the suite passes)**

```bash
bash tests/run_all.sh && { echo "Tame Impala rows: $(grep -c 'Tame Impala' index.html || true)"; git diff --stat; git add index.html data/refresh_state.json dist tests/_smoke_dist && git commit -m "data: first Ticketmaster refresh" && git push; }
```

Expected: `Tame Impala rows: 0`; `git diff --stat` shows `index.html`, `data/refresh_state.json`, `dist/*`; the push is a plain fast-forward (Task 0 made local strictly ahead). Push takes under 10 seconds; GitHub Pages updates in about a minute. If the suite fails, nothing is committed: read the failure, fix, rerun.

- [ ] **Step 3: Check the site**

Open https://concerts.thomasnendick.com/ (falls back to https://nendy55555.github.io/la-concert-tracker/ if the domain does not resolve). Expected: the header line reads "Data refreshed: <today> · N upcoming shows across 19 venues", November shows a full calendar, next-month past December reaches January 2027.

- [ ] **Step 4: Preview, then send to Thomas only**

```bash
python3 scripts/weekly_digest.py --horizon-days 180 --onsale-days 14 --text | head -40
DIGEST_ARGS="--email-to tjnendick5@gmail.com" bash scripts/weekly_run.sh
```

Expected preview: line 4 says `Data refreshed 0 days ago (N upcoming shows). Feed connected 2026-10-26: N upcoming shows loaded.`, no `NEW SINCE`, no Tame Impala. Expected wrapper output: `refresh: ok`, `tests: ok`, `git: nothing to commit` (or `pushed`), `digest: exit 0`. One email arrives at Thomas's address; `data/refresh_state.json` now holds `last_digest_at`, `last_digest_covered_through`, `last_refresh_rc`, `last_tests_status`, `last_push_status`. Commit that: `git add data/refresh_state.json && git commit -m "state: first digest coverage" && git push`.

- [ ] **Step 5: Hand-off for the Cowork task**

Thomas swaps the Cowork task's command himself (Cowork UI → Scheduled → weekly-concert-email → prompt). Give him the exact paste block from Task 8 Step 3 and tell him to leave the schedule (Sunday 09:03 PT) and tier (Haiku) alone. Until he does, Sunday's run still sends the old-style digest on the now-fresh data, which is acceptable for one week.

- [ ] **Step 6: Verify the first Cowork run**

After the first Sunday run on the new prompt, read `logs/weekly_run.log` (or ask Thomas to paste its last ten lines). Expected: `refresh: ok`, `tests: ok`, `git: pushed`, `digest: exit 0`, and the email's first line reads `Data refreshed 0 days ago`. Any other outcome is a DEBUG.md entry with the log excerpt; the likeliest are `node missing` (then `tests: failed`, named in the email) and `git: failed` (push credentials in the VM, named in the email). Only after this check is the feature done.

- [ ] **Step 7: Close the loop**

Update `docs/agent/SESSION-STATE.md` (completed, known issues, next entry points: Hollywood Bowl May 2027 check, watchlistAnywhere flag, Gist wiring), `brain/projects/la-concert-tracker.md` (status, how it works, the open question is closed, the live URL), `brain/log.md`, and `brain/concepts/silent-failure.md` (the la-concert-tracker row: resolved 2026-10-26, feed + data-age line that names every failure class). Add a `tm-venue-feed` candidate row to `Accelerators/INDEX.md` only if Row 5 or Ticket Tracker would adopt it; otherwise note it in SESSION-STATE as a candidate and move on.
