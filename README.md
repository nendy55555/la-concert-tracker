# LA Concert Tracker

Single-file web app that tracks concerts across 18 Los Angeles venues, flags shows matching a personal watchlist, and tracks on-sale dates.

Live site: https://nendy55555.github.io/la-concert-tracker/ (unlisted — not indexed)

## What it does

- Shows 400+ concerts across 18 LA venues, April–November 2026
- Three views: calendar, list, and "My Artists"
- Watchlist via star toggle (localStorage)
- Auto-match against a WISHLIST_ARTISTS list using fuzzy matching
- Filters by venue and genre
- On-sale date countdowns with vendor badges (Ticketmaster / AXS / Bowl)
- Google Calendar export per show
- "Hide past" toggle (default on)

## Venues tracked

Hollywood Bowl, Greek Theatre, Kia Forum, Crypto.com Arena, SoFi Stadium, The Wiltern, The Fonda Theatre, Troubadour, YouTube Theater, The Regent Theater, Rose Bowl, Hollywood Palladium, Academy LA, El Rey Theatre, Intuit Dome, Shrine Auditorium, The Novo, The Roxy Theatre.

## Stack

Single `index.html` file. No build step. Inline CSS + JS. Concert data lives as a `CONCERTS` array at the top of the `<script>` block.

## Updating data

Edit the `CONCERTS` array inside `index.html` directly. Run `bash tests/run_all.sh` before pushing — the tests catch malformed rows, unknown venues/genres, and bad date formats.

## Weekly digest

A scheduled task `weekly-concert-email` runs Sunday at 09:03 PT. It executes `scripts/weekly_digest.py` (pure Python, zero Claude reasoning), which reads `CONCERTS` + `WISHLIST_ARTISTS` from `index.html` and produces an HTML email. Claude's only remaining job is calling the Gmail `create_draft` MCP tool once. Runs fine on Haiku.

Manual run: `python3 scripts/weekly_digest.py --horizon-days 180 --text`

## Deploy

Pushed to `main` → GitHub Pages auto-publishes. No CI needed.

## Tests

`bash tests/run_all.sh` — 38 Python tests + 9 JS parity cases, <2s, no network, no Claude API.

## Project docs

Agent docs in `docs/agent/`:
- `QUICKSTART.md` — routing + file map
- `SESSION-STATE.md` — rolling what-changed log
- `AUDIT.md` — post-hardening Claude-call map
- `DECISIONS.md` — reasoning behind design choices
- `RUNBOOK.md` — "how do I…" for common ops
- `HARDENING-INVENTORY.md` — what was hardened and why
