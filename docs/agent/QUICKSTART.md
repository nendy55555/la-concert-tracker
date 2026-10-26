# LA Concert Tracker — Quickstart

Single-file HTML tracker. 440 concerts, 18 venues (+Peppermint Club defensively), Apr–Dec 2026. GitHub Pages: https://nendy55555.github.io/la-concert-tracker/ (301s to http://concerts.thomasnendick.com, https on that domain is not provisioned yet) (unlisted).

## Architecture
- `index.html` (about 2,620 lines, grows with the feed): everything. No build step.
- CSS: 11–1307 · HTML: 1308–1444 · JS+data: 1445–2615.
- `CONCERTS` @ 1447 (refresh data appended near end, before `];`) · `WISHLIST_ARTISTS` @ 1907 (40 artists) · `VENUE_PRICE` @ 1924 · `VENUE_DEFAULT_VENDOR` @ 1947.

## Data freshness
- Data comes from `scripts/refresh_concerts.py` (Ticketmaster Discovery,
  19 venues in `scripts/venues.json`).
- It runs inside `scripts/weekly_run.sh` every Sunday.
- State lives in `data/refresh_state.json`.

## Data row shape
`{ date, name, venue, genre, support, spotifyMonthlyListeners, ticketUrl, ticketVendor, onSaleDate, presaleDate, tmId, artists, firstSeen }`

## Features
Calendar/List/My Artists views · watchlist (localStorage + optional Gist sync) · fuzzy artist match · venue+genre filters · GCal export · vendor+on-sale badges · Upcoming Ticket Drops banner · artist search.

## Weekly digest
- `scripts/weekly_digest.py` — Python stdlib only. Reads `CONCERTS` from `index.html` and `data/refresh_state.json`, leads with "New since" and a data-age line that names every failure class, renders HTML/text/JSON, sends via Gmail SMTP, then records which refresh it covered.
- Creds: `.env` (gitignored) with `GMAIL_SENDER`, `GMAIL_APP_PASSWORD`, `TM_DISCOVERY_API_KEY`. Template at `.env.example`.
- Scheduled task `weekly-concert-email` (a Cowork task, Sun 09:03 PT, **Haiku**) runs one command: `bash scripts/weekly_run.sh`, which refreshes, tests, pushes, then sends. Zero Claude reasoning in the path. Prompt mirrored at `Scheduled/weekly-concert-email/SKILL.md`.

## Common commands
```bash
cd ~/Documents/Claude/Projects/"LA Concert Tracker"
bash tests/run_all.sh                                              # 43 py + 9 js, <2s
python3 scripts/weekly_digest.py --horizon-days 180 --text         # preview
python3 scripts/weekly_digest.py --horizon-days 180 --email        # send
python3 scripts/refresh_concerts.py --dry-run                      # fetch feed, write nothing
bash scripts/weekly_run.sh                                         # refresh, test, push, send
git add -A && git commit -m "msg" && git push                      # deploy (~60s)
```

## Watchlist sync
Optional GitHub Gist backend. Gear icon in header. See `SETUP-GIST-SYNC.md`.

## Where to look
- `specs/concert-feed/` — spec, evals, build plan and review for the
  Ticketmaster feed.
- `SESSION-STATE.md` — current state, last session's work, known issues, next-session entry points.
- `DECISIONS.md` — why things are the way they are.
- `RUNBOOK.md` — common failures, data-edit recipe, tier swaps, auth rotation.
- `SETUP-GIST-SYNC.md` — gist-sync setup walkthrough.
- `archive/` — one-time hardening reports (2026-04-20). Don't read unless investigating that pass.
