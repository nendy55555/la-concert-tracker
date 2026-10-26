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
from liveness import Result, check_max_date, run_checks  # noqa: E402  (copied accelerator)


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
