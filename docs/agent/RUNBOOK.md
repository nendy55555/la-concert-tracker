# LA Concert Tracker — Runbook

Written for future-you with minimal or no Claude access.

## TL;DR — what lives where

- **Site:** `index.html` (single file). Deploys via GitHub Pages on every push to `main`.
- **Data:** `CONCERTS` and `WISHLIST_ARTISTS` arrays inside `index.html`.
- **Weekly digest:** `scripts/weekly_digest.py` (Python 3.11+ stdlib only).
- **Tests:** `tests/` — run with `bash tests/run_all.sh`.
- **Scheduled task:** `weekly-concert-email`, Sunday 09:03 PT. Runs the Python script and creates a Gmail draft.

## 1. Run the weekly digest manually

```bash
cd ~/Documents/Claude/Projects/"LA Concert Tracker"
python3 scripts/weekly_digest.py --horizon-days 180 --onsale-days 14 --text
```

Rough time: <1s.

Outputs written to `dist/`:
- `weekly_digest.html` — the full email body
- `weekly_digest.txt` — plain-text fallback
- `weekly_digest.json` — structured data (use `--html` or `--text` to print to stdout instead)

Flags worth knowing:
- `--as-of 2026-05-10` — simulate a specific date (testing)
- `--horizon-days 300` — widen the watchlist window (defaults 180)
- `--onsale-days 14` — on-sale window
- `--out-dir /path` — write to a custom directory

## 2. Run the tests

```bash
cd ~/Documents/Claude/Projects/"LA Concert Tracker"
bash tests/run_all.sh
```

Rough time: 1–2s. No network, no Claude API. If anything fails, fix it before pushing data changes.

## 3. Update concert data

Two paths:

**Path A — small manual fix (1–5 concerts):**
1. Open `index.html` in your editor.
2. Search for the `const CONCERTS = [` block (~line 1334).
3. Edit the row(s). Keep the same shape: `{ date: 'YYYY-MM-DD', name: '...', venue: '...', genre: '...', support: '...', spotifyMonthlyListeners: 0, ticketUrl: '...', ticketVendor: '...', onSaleDate: '', presaleDate: '' }`.
4. Run `bash tests/run_all.sh` — must pass.
5. `git add -A && git commit -m "data: ..." && git push`.

**Path B — bulk refresh:**
This still requires Claude (or a human with Firecrawl) because per-venue HTML parsers are not hardened. To do it without Claude:
1. Pick a venue (e.g. `https://www.hollywoodbowl.com/events/`).
2. Open in browser, copy the calendar data.
3. Paste into a scratch file and hand-transform to CONCERT row format.
4. Paste into `index.html` in the correct date order.
5. Run tests, commit, push.

This path is deliberately manual because Claude-driven scrapes failed in production (see DECISIONS.md and `docs/agent/archive/weekly-concert-email.prompt.v1.md`).

## 4. Deploy

```bash
git add -A && git commit -m "your message" && git push
```

Rough time: <30s to build, ~60s to go live on GitHub Pages.

Site URL: https://nendy55555.github.io/la-concert-tracker/ (unlisted — `noindex` + `robots.txt`).

## 5. Swap Claude tiers on the scheduled task

If the Haiku-tier scheduled task starts failing (e.g. it can't reliably call `create_draft`), escalate to Sonnet:

1. Open the scheduled-tasks UI in Claude desktop.
2. Edit `weekly-concert-email`.
3. The prompt body is tier-agnostic; the model tier is set on the task itself. Select Sonnet.
4. Click "Run now" once to confirm it works.

To go back down, reverse the steps. The prompt never needs changes — it's just "run the script and call `create_draft` once."

## 6. Gmail MCP auth

If `create_draft` starts returning auth errors, the Gmail MCP token has rotated out. Fix:

1. Open Claude desktop → Settings → Connectors.
2. Find Gmail, click Reconnect.
3. Grant the same scopes (read + draft).
4. Run `weekly-concert-email` manually ("Run now") to verify.

No code changes required.

## 7. Common failures and fixes

### Symptom: script exits with `ERROR: CONCERTS array is not parseable`
**Cause:** a data edit introduced malformed JS (unbalanced quote, stray character).
**Fix:** `git diff index.html | less` — find the bad row. Restore formatting. Re-run tests.

### Symptom: script runs but `watch_hits` is 0 even though you know shows exist
**Cause #1:** the shows are past `today`. Digest only returns future shows.
**Cause #2:** the horizon is too narrow. Try `--horizon-days 300`.
**Cause #3:** the wishlist name and concert name differ too much for the fuzzy matcher. Edit `WISHLIST_ARTISTS` in `index.html` to add a better variant (e.g. add 'J Cole' in addition to 'JCole').

### Symptom: scheduled task hangs for hours
**Cause:** `create_draft` can hang if Gmail MCP is partially degraded. The prompt has a 60s abort clause — if it hangs longer than that, the issue is in the harness, not the task.
**Fix:** in the scheduled-task UI, cancel the run. Disable the task. Reconnect Gmail. Re-enable.

### Symptom: site looks unstyled
**Cause:** Google Fonts blocked or slow. Fallback stack is already defined; page is still legible.
**Fix:** none required. If annoying, self-host fonts — see DECISIONS.md for why we don't by default.

### Symptom: test `test_venue_set_is_known` fails
**Cause:** a new venue was added to the data but not to the allowlist in `tests/test_index_html_integrity.py`.
**Fix:** add the new venue name to `KNOWN_VENUES` in that file.

### Symptom: tests pass locally but scheduled task fails
**Cause:** the task runs under a different Python (or none). Check the task's log output.
**Fix:** `which python3` — should be `/usr/bin/python3` or similar with 3.11+. If not, edit the prompt to use an absolute path to your Python.

## 8. Data shape — reference

```jsonc
{
  "date": "YYYY-MM-DD",           // concert date in PT
  "name": "Artist Name",
  "venue": "Hollywood Bowl",      // must match KNOWN_VENUES
  "genre": "Rock",                // must match KNOWN_GENRES
  "support": "Opener Name",       // "" if none
  "spotifyMonthlyListeners": 0,   // int, 0 if unknown
  "ticketUrl": "https://...",     // "" if unknown
  "ticketVendor": "Ticketmaster", // auto-inferred from venue if empty
  "onSaleDate": "YYYY-MM-DD" | "YYYY-MM-DDThh:mm" | "",
  "presaleDate": "YYYY-MM-DD" | "YYYY-MM-DDThh:mm" | ""
}
```

## 9. Local dev

No build step. Open `index.html` in a browser or run `python3 -m http.server 8000` and visit `http://localhost:8000`.

localStorage keys used:
- `la_concert_watchlist` — JSON array of concertKey strings (`"date|name|venue"`).
- `la_tracked_artists` — JSON array of artist names.

## 10. Where to look next if things get weird

- `docs/agent/SESSION-STATE.md` — rolling log of what changed and known issues.
- `docs/agent/DECISIONS.md` — why things are the way they are.
- `docs/agent/AUDIT.md` — post-hardening audit of Claude dependencies.
- `docs/agent/archive/` — old behaviors preserved for reversibility.
- `git log --oneline` — full commit history.
