#!/usr/bin/env python3
"""
weekly_digest.py — deterministic LA concert digest generator.

Reads CONCERTS and WISHLIST_ARTISTS out of ../index.html, filters to upcoming
watchlist matches + near-term on-sale drops, renders an HTML email body plus a
plain-text fallback, and writes a small JSON summary to stdout.

Zero pip dependencies. Python 3.11+ stdlib only.

Network is only touched when `--email` is passed (Gmail SMTP).

Usage:
    python3 scripts/weekly_digest.py                         # stdout JSON, writes dist/
    python3 scripts/weekly_digest.py --html                  # stdout is HTML body
    python3 scripts/weekly_digest.py --as-of 2026-05-10      # override "today" for testing
    python3 scripts/weekly_digest.py --index path/to.html    # custom index.html path
    python3 scripts/weekly_digest.py --horizon-days 30       # shows within N days (default 30)
    python3 scripts/weekly_digest.py --onsale-days 14        # on-sales within N days (default 14)
    python3 scripts/weekly_digest.py --email                 # also send via Gmail SMTP

Email mode requires GMAIL_SENDER and GMAIL_APP_PASSWORD in the environment
(or in a .env file in the project root). EMAIL_TO defaults to GMAIL_SENDER.

Exit codes:
    0 success
    1 index.html not found or unparseable
    2 CONCERTS array could not be located/parsed
    3 WISHLIST_ARTISTS array could not be located/parsed
    4 SMTP send failed (only when --email)
"""

from __future__ import annotations

import argparse
import json
import os
import re
import smtplib
import ssl
import sys
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta, timezone
from email.message import EmailMessage
from html import escape
from pathlib import Path
from zoneinfo import ZoneInfo

TZ = ZoneInfo("America/Los_Angeles")
ROOT = Path(__file__).resolve().parent.parent
TRACKER_URL = "https://nendy55555.github.io/la-concert-tracker/"


# ─── 1. Parsing CONCERTS / WISHLIST_ARTISTS out of index.html ────────────────

CONCERTS_RE = re.compile(r"const\s+CONCERTS\s*=\s*\[", re.MULTILINE)
WISHLIST_RE = re.compile(r"const\s+WISHLIST_ARTISTS\s*=\s*\[", re.MULTILINE)


def _extract_array(src: str, open_index: int) -> str:
    """Return substring starting at `[` and ending at matching `]` (exclusive)."""
    depth = 0
    in_str = None  # quote char if inside a string
    prev = ""
    start = open_index
    assert src[start] == "["
    for i in range(start, len(src)):
        ch = src[i]
        if in_str:
            if ch == "\\" and prev != "\\":
                prev = ch
                continue
            if ch == in_str and prev != "\\":
                in_str = None
            prev = ch
            continue
        if ch in ("'", '"'):
            in_str = ch
            prev = ch
            continue
        if ch == "[":
            depth += 1
        elif ch == "]":
            depth -= 1
            if depth == 0:
                return src[start : i + 1]
        prev = ch
    raise ValueError("unterminated array")


def _js_array_to_python(js: str) -> list:
    """
    Convert a JS array literal of objects (with unquoted keys, single/double
    quoted strings, trailing commas, line comments) into Python via JSON.

    Uses a string-aware pass so `//` inside string literals (e.g. `https://...`)
    is NOT treated as a comment, and so single-quote string bodies are
    re-escaped correctly for JSON.
    """
    # Each entry is ("s", string-literal-as-JSON) or ("c", non-string text); the
    # post-passes below run on the "c" segments only.
    out: list[tuple[str, str]] = []
    i = 0
    n = len(js)
    while i < n:
        ch = js[i]
        # Double-quoted string — pass through as-is
        if ch == '"':
            j = i + 1
            while j < n:
                if js[j] == "\\" and j + 1 < n:
                    j += 2
                    continue
                if js[j] == '"':
                    break
                j += 1
            out.append(("s", js[i : j + 1]))
            i = j + 1
            continue
        # Single-quoted string — convert to JSON double-quoted
        if ch == "'":
            j = i + 1
            body = []
            while j < n:
                c = js[j]
                if c == "\\" and j + 1 < n:
                    nxt = js[j + 1]
                    if nxt == "'":
                        body.append("'")  # unescape \' → '
                    elif nxt == "\\":
                        body.append("\\\\")
                    elif nxt in ('"', "n", "t", "r", "/", "b", "f"):
                        body.append("\\" + nxt)
                    else:
                        body.append("\\\\" + nxt)
                    j += 2
                    continue
                if c == "'":
                    break
                if c == '"':
                    body.append('\\"')
                elif c == "\\":
                    body.append("\\\\")
                elif c == "\n":
                    body.append("\\n")
                elif c == "\r":
                    body.append("\\r")
                elif c == "\t":
                    body.append("\\t")
                else:
                    body.append(c)
                j += 1
            out.append(("s", '"' + "".join(body) + '"'))
            i = j + 1
            continue
        # Line comment `//…\n` (only outside strings)
        if ch == "/" and i + 1 < n and js[i + 1] == "/":
            j = i + 2
            while j < n and js[j] != "\n":
                j += 1
            # Skip the comment but keep the newline so downstream regex/line numbers survive
            i = j
            continue
        # Block comment /* … */
        if ch == "/" and i + 1 < n and js[i + 1] == "*":
            j = js.find("*/", i + 2)
            if j == -1:
                raise ValueError("unterminated block comment")
            i = j + 2
            continue
        out.append(("c", ch))
        i += 1

    # Post-passes run on NON-STRING segments only. A string literal (already JSON
    # double-quoted at this point) is passed through untouched, so a name such as
    # 'Dawes, Live: An Evening' can never be mistaken for an object key, and curly
    # quotes inside a name are never turned into raw double quotes.
    def _fix(segment: str) -> str:
        # Quote unquoted object keys: `key:` → `"key":` (only after `{` or `,`).
        segment = re.sub(r"([{,]\s*)([A-Za-z_][A-Za-z0-9_]*)\s*:", r'\1"\2":', segment)
        # Drop trailing commas before ] or }
        segment = re.sub(r",(\s*[}\]])", r"\1", segment)
        # Smart quotes → straight (occasional stragglers)
        return segment.translate(
            str.maketrans({"\u2019": "'", "\u2018": "'", "\u201c": '"', "\u201d": '"'})
        )

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


def load_data(index_path: Path) -> tuple[list[dict], list[str]]:
    if not index_path.exists():
        print(f"ERROR: index.html not found at {index_path}", file=sys.stderr)
        sys.exit(1)
    src = index_path.read_text(encoding="utf-8")

    m = CONCERTS_RE.search(src)
    if not m:
        print("ERROR: could not find 'const CONCERTS = [' in index.html", file=sys.stderr)
        sys.exit(2)
    concerts_js = _extract_array(src, m.end() - 1)
    try:
        concerts = _js_array_to_python(concerts_js)
    except Exception as e:
        print(f"ERROR: CONCERTS array is not parseable: {e}", file=sys.stderr)
        sys.exit(2)

    m = WISHLIST_RE.search(src)
    if not m:
        print("ERROR: could not find 'const WISHLIST_ARTISTS = [' in index.html", file=sys.stderr)
        sys.exit(3)
    wishlist_js = _extract_array(src, m.end() - 1)
    try:
        wishlist = _js_array_to_python(wishlist_js)
    except Exception as e:
        print(f"ERROR: WISHLIST_ARTISTS array is not parseable: {e}", file=sys.stderr)
        sys.exit(3)

    return concerts, wishlist


# ─── 2. Fuzzy matcher (must match index.html's normalizeForMatch) ────────────

# index.html: s.toLowerCase().replace(/[\s\.\-&''']/g, '').replace(/[^a-z0-9]/g, '')
_STRIP_CHARS = set(" .-&''’\t\n\r")


def normalize_for_match(s: str) -> str:
    s = s.lower()
    out = []
    for ch in s:
        if ch in _STRIP_CHARS:
            continue
        if "a" <= ch <= "z" or "0" <= ch <= "9":
            out.append(ch)
    return "".join(out)


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


# ─── 3. Date helpers ─────────────────────────────────────────────────────────


def today_local(as_of: str | None = None) -> date:
    if as_of:
        return date.fromisoformat(as_of)
    return datetime.now(TZ).date()


def parse_sale_date(s: str) -> datetime | None:
    """Accept YYYY-MM-DD or YYYY-MM-DDThh:mm. Return None if empty/unparseable."""
    if not s:
        return None
    try:
        if "T" in s:
            # e.g. 2026-05-10T10:00
            return datetime.fromisoformat(s).replace(tzinfo=TZ)
        return datetime.fromisoformat(s + "T00:00:00").replace(tzinfo=TZ)
    except ValueError:
        return None


# ─── 4. Digest building ──────────────────────────────────────────────────────


@dataclass
class WatchHit:
    watchlist_artist: str
    name: str
    date: str
    venue: str
    genre: str
    support: str
    ticket_url: str
    ticket_vendor: str
    on_sale_date: str
    presale_date: str
    days_until: int


@dataclass
class OnSaleHit:
    name: str
    date: str
    venue: str
    sale_kind: str  # "onsale" or "presale"
    sale_at: str   # YYYY-MM-DDThh:mm or YYYY-MM-DD
    days_until: int
    ticket_vendor: str
    ticket_url: str
    is_watched: bool


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
        loaded = f"{rows} upcoming shows loaded" if rows is not None else "upcoming shows loaded"
        line += f" Feed connected {ok_at[:10]}: {loaded}."
    return {"status": status, "age_days": age, "line": line}


def build_digest(
    concerts: list[dict],
    wishlist: list[str],
    today: date,
    horizon_days: int,
    onsale_days: int,
    state: dict | None = None,
    tiers: dict[str, int] | None = None,
) -> dict:
    watchlist_norm = [normalize_for_match(a) for a in wishlist]
    horizon_end = today + timedelta(days=horizon_days)
    onsale_end = today + timedelta(days=onsale_days)

    watch_hits: list[WatchHit] = []
    onsale_hits: list[OnSaleHit] = []

    for c in concerts:
        try:
            d = date.fromisoformat(c["date"])
        except (KeyError, ValueError):
            continue
        name = c.get("name", "")

        # Watchlist matches within horizon
        if d >= today and d <= horizon_end:
            hits = matched_watchlist_names(name, wishlist, artists=c.get("artists"))
            for artist in hits:
                watch_hits.append(
                    WatchHit(
                        watchlist_artist=artist,
                        name=name,
                        date=c["date"],
                        venue=c.get("venue", ""),
                        genre=c.get("genre", ""),
                        support=c.get("support", ""),
                        ticket_url=c.get("ticketUrl", ""),
                        ticket_vendor=c.get("ticketVendor", ""),
                        on_sale_date=c.get("onSaleDate", ""),
                        presale_date=c.get("presaleDate", ""),
                        days_until=(d - today).days,
                    )
                )

        # On-sale drops within onsale window
        for kind, field in (("presale", "presaleDate"), ("onsale", "onSaleDate")):
            raw = c.get(field, "")
            sd = parse_sale_date(raw)
            if not sd:
                continue
            sd_date = sd.date()
            if sd_date < today or sd_date > onsale_end:
                continue
            onsale_hits.append(
                OnSaleHit(
                    name=name,
                    date=c.get("date", ""),
                    venue=c.get("venue", ""),
                    sale_kind=kind,
                    sale_at=raw,
                    days_until=(sd_date - today).days,
                    ticket_vendor=c.get("ticketVendor", ""),
                    ticket_url=c.get("ticketUrl", ""),
                    is_watched=is_watched_artist(name, watchlist_norm, artists=c.get("artists")),
                )
            )

    # Sort / dedupe
    watch_hits.sort(key=lambda h: (h.date, h.name.lower()))
    # Deduplicate: same (name, date, venue) can match multiple wishlist entries — collapse
    seen = set()
    dedup_watch: list[WatchHit] = []
    for h in watch_hits:
        k = (h.name, h.date, h.venue)
        if k in seen:
            continue
        seen.add(k)
        dedup_watch.append(h)

    onsale_hits.sort(key=lambda h: (h.days_until, h.name.lower()))

    # Per-artist roster (every wishlist artist + their upcoming LA shows, or no-shows)
    per_artist: dict[str, list[WatchHit]] = {a: [] for a in wishlist}
    # Built from pre-dedup watch_hits so a show matching two watched artists credits both.
    credited: set[tuple[str, str, str, str]] = set()
    for h in watch_hits:
        k = (h.watchlist_artist, h.name, h.date, h.venue)
        if k in credited:
            continue
        credited.add(k)
        per_artist.setdefault(h.watchlist_artist, []).append(h)

    feed = _feed_status(state, today)
    new_since = None
    since = (state or {}).get("last_digest_covered_through")  # ISO timestamp of the refresh the last digest showed
    if since:
        tiers = tiers or {}
        shows, onsales = [], []
        for c in concerts:
            try:
                d = date.fromisoformat(c["date"])
            except (KeyError, ValueError):
                continue
            if d < today:
                continue
            watched = is_watched_artist(c.get("name", ""), watchlist_norm, artists=c.get("artists"))
            entry = {"date": c["date"], "name": c.get("name", ""), "venue": c.get("venue", ""),
                     "support": c.get("support", ""), "ticket_url": c.get("ticketUrl", ""),
                     "on_sale_date": c.get("onSaleDate", ""), "presale_date": c.get("presaleDate", ""),
                     "watched": watched}
            fs = c.get("firstSeen") or ""
            if fs > since and (watched or tiers.get(entry["venue"], 0) >= NOTABLE_TIER_MIN):
                shows.append(entry)
            os_dt = parse_sale_date(c.get("onSaleDate", ""))
            if os_dt and since[:10] < os_dt.date().isoformat() <= today.isoformat():
                onsales.append(entry)
        key = lambda e: (not e["watched"], e["date"], e["name"].lower())
        shows.sort(key=key)
        onsales.sort(key=key)
        shows = [s for s in shows if s["watched"]] + [s for s in shows if not s["watched"]][:NEW_SHOWS_CAP]
        new_since = {"since": since, "shows": shows, "onsales": onsales}

    return {
        "generated_at": datetime.now(TZ).isoformat(timespec="seconds"),
        "as_of": today.isoformat(),
        "feed": feed,
        "new_since": new_since,
        "horizon_days": horizon_days,
        "onsale_days": onsale_days,
        "watch_hits": [asdict(h) for h in dedup_watch],
        "onsale_hits": [asdict(h) for h in onsale_hits],
        "per_artist": {a: [asdict(h) for h in hits] for a, hits in per_artist.items()},
        "totals": {
            "concerts": len(concerts),
            "watchlist_artists": len(wishlist),
            "watch_hits": len(dedup_watch),
            "onsale_hits": len(onsale_hits),
            "artists_with_shows": sum(1 for hits in per_artist.values() if hits),
        },
    }


# ─── 5. Rendering ────────────────────────────────────────────────────────────


def _fmt_date(iso: str) -> str:
    try:
        d = date.fromisoformat(iso)
        return d.strftime("%a %b %-d, %Y")
    except ValueError:
        return iso


def _fmt_sale(s: str) -> str:
    dt = parse_sale_date(s)
    if not dt:
        return s
    if "T" in s:
        return dt.strftime("%a %b %-d @ %-I:%M %p")
    return dt.strftime("%a %b %-d")


def render_text(digest: dict) -> str:
    out = []
    out.append(f"LA Concert Weekly — {digest['as_of']}")
    out.append("=" * 60)
    out.append("")
    out.append(digest["feed"]["line"])
    out.append("")
    out.append(
        f"{digest['totals']['watch_hits']} watchlist shows in the next "
        f"{digest['horizon_days']} days · "
        f"{digest['totals']['onsale_hits']} on-sale drops in the next "
        f"{digest['onsale_days']} days"
    )
    out.append("")
    out.append(f"Full tracker: {TRACKER_URL}")
    out.append("")

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

    out.append("── WATCHLIST — upcoming LA shows ──")
    if not digest["watch_hits"]:
        out.append("None in the horizon window.")
    for h in digest["watch_hits"]:
        support = f"  w/ {h['support']}" if h["support"] else ""
        on_sale = ""
        if h["on_sale_date"]:
            on_sale = f"  · on sale {_fmt_sale(h['on_sale_date'])}"
        elif h["presale_date"]:
            on_sale = f"  · presale {_fmt_sale(h['presale_date'])}"
        out.append(
            f"  • {_fmt_date(h['date'])} — {h['name']} @ {h['venue']}{support}"
            f"  ({h['days_until']}d){on_sale}"
        )
        if h["ticket_url"]:
            out.append(f"    {h['ticket_url']}")
    out.append("")

    out.append("── ON-SALE DROPS — next 14 days ──")
    if not digest["onsale_hits"]:
        out.append("None.")
    for h in digest["onsale_hits"]:
        flag = "★ " if h["is_watched"] else "  "
        label = "PRESALE" if h["sale_kind"] == "presale" else "ON SALE"
        out.append(
            f"{flag}{label}  {_fmt_sale(h['sale_at'])}  —  "
            f"{h['name']} @ {h['venue']} on {_fmt_date(h['date'])}"
        )
    out.append("")

    out.append("── FULL WATCHLIST ROSTER ──")
    artists_with = [a for a, hits in digest["per_artist"].items() if hits]
    artists_without = [a for a, hits in digest["per_artist"].items() if not hits]
    out.append(f"With LA shows ({len(artists_with)}): {', '.join(artists_with) or '—'}")
    out.append(f"No LA shows in tracker ({len(artists_without)}): {', '.join(artists_without) or '—'}")
    out.append("")
    out.append(f"Generated {digest['generated_at']} · {digest['totals']['concerts']} concerts in source")
    return "\n".join(out)


def render_html(digest: dict) -> str:
    css = """
      body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; color: #111; background: #fff; max-width: 680px; margin: 0 auto; padding: 24px; }
      h1 { font-size: 20px; margin: 0 0 4px; }
      .sub { color: #555; font-size: 13px; margin-bottom: 20px; }
      h2 { font-size: 14px; text-transform: uppercase; letter-spacing: .05em; color: #0096d1; margin: 28px 0 10px; border-bottom: 1px solid #e5e5e5; padding-bottom: 4px; }
      .row { padding: 10px 0; border-bottom: 1px solid #f0f0f0; }
      .row:last-child { border-bottom: none; }
      .name { font-weight: 600; }
      .meta { color: #555; font-size: 13px; }
      .pill { display: inline-block; font-size: 11px; padding: 1px 6px; border-radius: 3px; margin-right: 4px; font-weight: 600; }
      .pill-onsale { background: #ffebee; color: #c62828; }
      .pill-presale { background: #e3f2fd; color: #1565c0; }
      .pill-watched { background: #fff8e1; color: #ff8f00; }
      a { color: #0077b6; text-decoration: none; }
      .empty { color: #888; font-style: italic; }
      .roster { font-size: 13px; color: #555; line-height: 1.6; }
      .roster b { color: #111; }
    """
    feed_style = (" style='color:#b00020;font-weight:600'"
                  if digest["feed"]["status"] in ("stale", "failed") else "")
    parts = [
        "<!DOCTYPE html><html><head><meta charset='utf-8'><style>",
        css,
        "</style></head><body>",
        f"<h1>LA Concert Weekly</h1>",
        f"<div class='sub'>As of {escape(digest['as_of'])} · "
        f"{digest['totals']['watch_hits']} watchlist shows in the next {digest['horizon_days']} days · "
        f"{digest['totals']['onsale_hits']} on-sale drops in the next {digest['onsale_days']} days</div>",
        f"<div class='feed'{feed_style}>{escape(digest['feed']['line'])}</div>",
        f"<div style='margin: 12px 0 20px; padding: 10px 14px; background: #f4faff; "
        f"border-left: 3px solid #0096d1; border-radius: 3px; font-size: 14px;'>"
        f"<a href='{escape(TRACKER_URL)}' style='color: #0077b6; font-weight: 600; text-decoration: none;'>"
        f"View the full LA Concert Tracker →</a>"
        f"</div>",
    ]

    ns = digest.get("new_since")
    if ns and (ns["shows"] or ns["onsales"]):
        since_label = date.fromisoformat(ns["since"][:10]).strftime("%b %-d")
        parts.append(f"<h2>New since {escape(since_label)}</h2>")
        for s in ns["shows"]:
            pill = "<span class='pill pill-watched'>★</span> " if s["watched"] else ""
            nm = f"<a href='{escape(s['ticket_url'])}'>{escape(s['name'])}</a>" if s["ticket_url"] else escape(s["name"])
            parts.append(
                f"<div class='row'>{pill}<span class='name'>{nm}</span> "
                f"<span class='meta'>· {escape(_fmt_date(s['date']))} · {escape(s['venue'])}</span></div>"
            )
        for s in ns["onsales"]:
            pill = "<span class='pill pill-watched'>★</span> " if s["watched"] else ""
            nm = f"<a href='{escape(s['ticket_url'])}'>{escape(s['name'])}</a>" if s["ticket_url"] else escape(s["name"])
            parts.append(
                f"<div class='row'><span class='pill pill-onsale'>ON SALE</span> {pill}"
                f"<b>{escape(_fmt_sale(s['on_sale_date']))}</b> "
                f"<span class='meta'>· {nm} @ {escape(s['venue'])} on {escape(_fmt_date(s['date']))}</span></div>"
            )

    parts.append("<h2>Watchlist — upcoming LA shows</h2>")
    if not digest["watch_hits"]:
        parts.append("<div class='empty'>None in the horizon window.</div>")
    for h in digest["watch_hits"]:
        support = f" <span class='meta'>w/ {escape(h['support'])}</span>" if h["support"] else ""
        on_sale_bits = []
        if h["on_sale_date"]:
            on_sale_bits.append(f"<span class='pill pill-onsale'>ON SALE {escape(_fmt_sale(h['on_sale_date']))}</span>")
        if h["presale_date"] and h["presale_date"] != h["on_sale_date"]:
            on_sale_bits.append(f"<span class='pill pill-presale'>PRESALE {escape(_fmt_sale(h['presale_date']))}</span>")
        link = ""
        if h["ticket_url"]:
            link = f" · <a href='{escape(h['ticket_url'])}'>tickets</a>"
        name_html = f"<a href='{escape(h['ticket_url'])}'>{escape(h['name'])}</a>" if h["ticket_url"] else escape(h["name"])
        parts.append(
            f"<div class='row'>"
            f"<div class='name'>{name_html}{support}</div>"
            f"<div class='meta'>{escape(_fmt_date(h['date']))} · {escape(h['venue'])} · "
            f"{h['days_until']}d away {' '.join(on_sale_bits)}</div>"
            f"</div>"
        )

    parts.append("<h2>On-sale drops — next 14 days</h2>")
    if not digest["onsale_hits"]:
        parts.append("<div class='empty'>None.</div>")
    for h in digest["onsale_hits"]:
        watched = "<span class='pill pill-watched'>WATCHING</span> " if h["is_watched"] else ""
        kind_pill = (
            "<span class='pill pill-presale'>PRESALE</span>"
            if h["sale_kind"] == "presale"
            else "<span class='pill pill-onsale'>ON SALE</span>"
        )
        link = f"<a href='{escape(h['ticket_url'])}'>{escape(h['name'])}</a>" if h["ticket_url"] else escape(h["name"])
        parts.append(
            f"<div class='row'>"
            f"{kind_pill} {watched}"
            f"<b>{escape(_fmt_sale(h['sale_at']))}</b> "
            f"<span class='meta'>· {link} @ {escape(h['venue'])} on {escape(_fmt_date(h['date']))}</span>"
            f"</div>"
        )

    parts.append("<h2>Full watchlist roster</h2>")
    with_shows = [a for a, hits in digest["per_artist"].items() if hits]
    without = [a for a, hits in digest["per_artist"].items() if not hits]
    parts.append(
        f"<div class='roster'><b>With LA shows ({len(with_shows)}):</b> "
        f"{escape(', '.join(with_shows)) or '—'}</div>"
    )
    parts.append(
        f"<div class='roster'><b>No LA shows in tracker ({len(without)}):</b> "
        f"{escape(', '.join(without)) or '—'}</div>"
    )

    parts.append(
        f"<div class='sub' style='margin-top:24px;'>Generated "
        f"{escape(digest['generated_at'])} · {digest['totals']['concerts']} concerts in source</div>"
    )
    parts.append("</body></html>")
    return "".join(parts)


# ─── 6. Email delivery (Gmail SMTP) ──────────────────────────────────────────


def load_env_file(path: Path) -> None:
    """
    Minimal .env loader: KEY=VALUE per line, # comments, optional quotes.
    Does not overwrite already-set environment variables.
    """
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        val = val.strip()
        if (val.startswith('"') and val.endswith('"')) or (
            val.startswith("'") and val.endswith("'")
        ):
            val = val[1:-1]
        if key and key not in os.environ:
            os.environ[key] = val


def build_email_message(
    sender: str,
    recipient: str | list[str],
    subject: str,
    html_body: str,
    text_body: str,
) -> EmailMessage:
    msg = EmailMessage()
    msg["From"] = sender
    if isinstance(recipient, list):
        msg["To"] = ", ".join(recipient)
    else:
        msg["To"] = recipient
    msg["Subject"] = subject
    msg.set_content(text_body)
    msg.add_alternative(html_body, subtype="html")
    return msg


def parse_recipients(raw: str) -> list[str]:
    """Split a comma/semicolon-separated address string into a clean list."""
    if not raw:
        return []
    out = []
    for chunk in re.split(r"[,;]", raw):
        addr = chunk.strip()
        if addr:
            out.append(addr)
    return out


def send_via_smtp(
    msg: EmailMessage,
    sender: str,
    app_password: str,
    host: str = "smtp.gmail.com",
    port: int = 465,
    smtp_factory=None,
) -> None:
    """
    Send `msg` through Gmail SMTP over SSL. Pass `smtp_factory` (a callable
    returning an SMTP-like object) for tests.
    """
    if smtp_factory is None:
        context = ssl.create_default_context()
        with smtplib.SMTP_SSL(host, port, context=context, timeout=30) as smtp:
            smtp.login(sender, app_password)
            smtp.send_message(msg)
    else:
        with smtp_factory(host, port) as smtp:
            smtp.login(sender, app_password)
            smtp.send_message(msg)


# ─── 7. CLI ──────────────────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="LA Concert weekly digest generator")
    p.add_argument(
        "--index",
        default=str(Path(__file__).resolve().parent.parent / "index.html"),
        help="Path to index.html (default: project root)",
    )
    p.add_argument("--as-of", default=None, help="Override today (YYYY-MM-DD) for testing")
    p.add_argument("--horizon-days", type=int, default=180, help="Upcoming-shows window (default 180)")
    p.add_argument("--onsale-days", type=int, default=14, help="On-sale window (default 14)")
    p.add_argument("--html", action="store_true", help="Print the HTML body to stdout instead of JSON")
    p.add_argument("--text", action="store_true", help="Print the plain-text body to stdout instead of JSON")
    p.add_argument("--out-dir", default=None, help="Write dist/ outputs (default: ../dist relative to script)")
    p.add_argument(
        "--email",
        action="store_true",
        help="Send the digest via Gmail SMTP. Requires GMAIL_SENDER + GMAIL_APP_PASSWORD env vars (or .env file).",
    )
    p.add_argument(
        "--email-to",
        default=None,
        help="Override recipient. Defaults to EMAIL_TO env var, then GMAIL_SENDER.",
    )
    p.add_argument("--state", default=str(ROOT / "data" / "refresh_state.json"),
                   help="Path to refresh_state.json (default: data/refresh_state.json)")
    p.add_argument("--venues", default=str(ROOT / "scripts" / "venues.json"),
                   help="Path to venues.json (default: scripts/venues.json)")
    args = p.parse_args(argv)

    index_path = Path(args.index).resolve()

    # Load .env from project root (next to index.html) before reading env vars.
    load_env_file(index_path.parent / ".env")

    concerts, wishlist = load_data(index_path)
    today = today_local(args.as_of)
    state_path = Path(args.state)
    state = load_refresh_state(state_path)
    tiers = load_venue_tiers(Path(args.venues))
    digest = build_digest(concerts, wishlist, today, args.horizon_days, args.onsale_days,
                          state=state, tiers=tiers)

    out_dir = Path(args.out_dir) if args.out_dir else index_path.parent / "dist"
    out_dir.mkdir(parents=True, exist_ok=True)
    html_body = render_html(digest)
    text_body = render_text(digest)
    (out_dir / "weekly_digest.html").write_text(html_body, encoding="utf-8")
    (out_dir / "weekly_digest.txt").write_text(text_body, encoding="utf-8")
    (out_dir / "weekly_digest.json").write_text(json.dumps(digest, indent=2), encoding="utf-8")

    subject = f"🎵 LA Concert Weekly — {today.strftime('%B %-d, %Y')}"

    email_status: dict | None = None
    if args.email:
        sender = os.environ.get("GMAIL_SENDER", "").strip()
        app_password = os.environ.get("GMAIL_APP_PASSWORD", "").strip()
        raw_to = (args.email_to or os.environ.get("EMAIL_TO") or sender).strip()
        recipients = parse_recipients(raw_to) or [sender]
        if not sender or not app_password:
            print(
                "ERROR: --email requires GMAIL_SENDER and GMAIL_APP_PASSWORD env vars "
                "(or a .env file in the project root).",
                file=sys.stderr,
            )
            return 4
        # App passwords are shown with spaces in Google's UI but SMTP wants them without.
        app_password_clean = app_password.replace(" ", "")
        msg = build_email_message(sender, recipients, subject, html_body, text_body)
        try:
            send_via_smtp(msg, sender, app_password_clean)
        except Exception as e:  # smtplib raises a variety of errors; catch all
            print(f"ERROR: SMTP send failed: {e}", file=sys.stderr)
            return 4
        email_status = {"sent": True, "to": recipients, "from": sender}
        st = load_refresh_state(state_path) or {}
        st["last_digest_at"] = datetime.now(TZ).isoformat(timespec="seconds")
        st["last_digest_covered_through"] = st.get("last_success_at", "")
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.write_text(json.dumps(st, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    if args.html:
        print(html_body)
    elif args.text:
        print(text_body)
    else:
        # Small JSON summary designed to be pasted into the scheduled-task prompt.
        summary = {
            "subject": subject,
            "totals": digest["totals"],
            "watch_hits_preview": digest["watch_hits"][:5],
            "onsale_hits_preview": digest["onsale_hits"][:5],
            "output_dir": str(out_dir),
            "html_path": str(out_dir / "weekly_digest.html"),
            "text_path": str(out_dir / "weekly_digest.txt"),
            "email": email_status,
        }
        print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
