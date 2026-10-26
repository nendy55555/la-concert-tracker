# LA Concert Tracker — Quickstart

Single-file HTML tracker. 440 concerts, 18 venues (+Peppermint Club defensively), Apr–Dec 2026. GitHub Pages: https://nendy55555.github.io/la-concert-tracker/ (unlisted).

## Architecture
- `index.html` (2617 lines) — everything. No build step.
- CSS: 11–1307 · HTML: 1308–1444 · JS+data: 1445–2615.
- `CONCERTS` @ 1447 (refresh data appended near end, before `];`) · `WISHLIST_ARTISTS` @ 1907 (40 artists) · `VENUE_PRICE` @ 1924 · `VENUE_DEFAULT_VENDOR` @ 1947.

## Data freshness
`CONCERTS` is a static JS array — no auto-scraper. To refresh, scrape venue calendars + watchlist artists and append rows. Last refresh: **2026-06-02**.

## Data row shape
`{ date, name, venue, genre, support, spotifyMonthlyListeners, ticketUrl, ticketVendor, onSaleDate, presaleDate }`

## Features
Calendar/List/My Artists views · watchlist (localStorage + optional Gist sync) · fuzzy artist match · venue+genre filters · GCal export · vendor+on-sale badges · Upcoming Ticket Drops banner · artist search.

## Weekly digest
- `scripts/weekly_digest.py` — Python stdlib only. Reads `CONCERTS` from `index.html`, renders HTML/text/JSON, sends via Gmail SMTP.
- Creds: `.env` (gitignored) with `GMAIL_SENDER` + `GMAIL_APP_PASSWORD`. Template at `.env.example`.
- Scheduled task `weekly-concert-email` runs Sun 09:03 PT on **Haiku**. Prompt = "run script with `--email`, report exit code". Zero Claude reasoning in the send path.

## Common commands
```bash
cd ~/Documents/Claude/Projects/"LA Concert Tracker"
bash tests/run_all.sh                                              # 43 py + 9 js, <2s
python3 scripts/weekly_digest.py --horizon-days 180 --text         # preview
python3 scripts/weekly_digest.py --horizon-days 180 --email        # send
git add -A && git commit -m "msg" && git push                      # deploy (~60s)
```

## Watchlist sync
Optional GitHub Gist backend. Gear icon in header. See `SETUP-GIST-SYNC.md`.

## Where to look
- `SESSION-STATE.md` — current state, last session's work, known issues, next-session entry points.
- `DECISIONS.md` — why things are the way they are.
- `RUNBOOK.md` — common failures, data-edit recipe, tier swaps, auth rotation.
- `SETUP-GIST-SYNC.md` — gist-sync setup walkthrough.
- `archive/` — one-time hardening reports (2026-04-20). Don't read unless investigating that pass.
