# LA Concert Tracker — Quickstart

## What Is This
Single-file HTML concert tracker for LA. 399 concerts across 18 venues, April–November 2026. Cyberpunk neon design (Orbitron + IBM Plex Mono).

## Hardened state (as of 2026-04-20)
- Static site has **zero Claude runtime dependency**.
- Weekly digest (`weekly-concert-email` scheduled task) runs a **pure Python script** — no WebSearch, no Firecrawl, no Chrome. Claude's only job is calling `create_draft` once.
- Full test suite in `tests/`. Run `bash tests/run_all.sh` before any data push.
- Target model tier for scheduled task: **Haiku**.
- See `RUNBOOK.md` for "how do I…" answers.

## Architecture
Everything lives in `index.html`. No build system. CSS + JS inline. Data is a `CONCERTS` array of objects at the top of the `<script>` block (~line 1334).

## Key Data Fields
```
{ date, name, venue, genre, support, spotifyMonthlyListeners, ticketUrl, ticketVendor, onSaleDate, presaleDate }
```

## Features
Calendar / List / My Artists views · watchlist (localStorage) · artist tracking with fuzzy match · venue + genre filters · Google Calendar export · vendor + on-sale badges with countdown · Upcoming Ticket Drops banner · artist search.

## Current State
- 399 concerts, 18 venues (+ Peppermint Club defensively).
- Deployed: https://nendy55555.github.io/la-concert-tracker/ (unlisted).
- In-flight: nothing (clean state, hardened).
- Tests: 38 Python + 9 JS parity, all pass in <2s.

## Running the digest manually
```bash
cd ~/Documents/Claude/Projects/"LA Concert Tracker"
python3 scripts/weekly_digest.py --horizon-days 180 --text
```

## Running the tests
```bash
bash tests/run_all.sh
```

## Deploy
```bash
git add -A && git commit -m "msg" && git push
```
GitHub Pages auto-publishes in ~60s.

## File Routing (line numbers)
- Styles: 11–1092
- HTML structure: 1093–1331
- Concert data: 1334–1743
- Wishlist: 1745–1754
- Venue tables: 1756–1806
- JS logic: 1808–2230
- Scripts: `scripts/weekly_digest.py`
- Tests: `tests/`
- Docs: `docs/agent/` (SESSION-STATE, QUICKSTART, AUDIT, DECISIONS, RUNBOOK, HARDENING-INVENTORY)

## When something breaks
See `RUNBOOK.md` §7 — common failures and fixes. Most symptoms can be resolved without Claude.
