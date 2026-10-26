# LA Concert Tracker — Runbook

Written for future-you with minimal or no Claude access.

## TL;DR — what lives where

- **Site:** `index.html` (single file). Deploys via GitHub Pages on every push to `main`.
- **Data:** `CONCERTS` and `WISHLIST_ARTISTS` arrays inside `index.html`.
- **Weekly digest:** `scripts/weekly_digest.py` (Python 3.11+ stdlib only).
- **Tests:** `tests/` — run with `bash tests/run_all.sh`.
- **Scheduled task:** `weekly-concert-email`, Sunday 09:03 PT. Runs `bash scripts/weekly_run.sh` (refresh, tests, commit and push, then the digest send via Gmail SMTP). Claude does no reasoning in the send path.
- **Credentials:** `.env` in project root with `GMAIL_SENDER`, `GMAIL_APP_PASSWORD` and `TM_DISCOVERY_API_KEY` (gitignored). Template at `.env.example`.

## 1. Run the weekly digest manually

```bash
cd ~/Documents/Claude/Projects/"LA Concert Tracker"
python3 scripts/weekly_digest.py --horizon-days 180 --onsale-days 14 --text         # preview to stdout
python3 scripts/weekly_digest.py --horizon-days 180 --onsale-days 14 --email        # actually send via SMTP
```

Rough time: <1s.

Outputs written to `dist/`:
- `weekly_digest.html` — the full email body
- `weekly_digest.txt` — plain-text fallback
- `weekly_digest.json` — structured data + `email` field summarizing send result (when `--email`)

Flags worth knowing:
- `--as-of 2026-05-10` — simulate a specific date (testing)
- `--horizon-days 300` — widen the watchlist window (defaults 180)
- `--onsale-days 14` — on-sale window
- `--email` — actually send via Gmail SMTP (reads `.env`)
- `--email-to addr@x.com` — override recipient (defaults to `GMAIL_SENDER`)
- `--out-dir /path` — write to a custom directory

Exit codes: 0 ok · 2 parse failure · 3 render failure · 4 SMTP send failed.

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

**Path B — bulk refresh from Ticketmaster:**
1. `python3 scripts/refresh_concerts.py` (add `--dry-run` to fetch and report without writing).
2. `bash tests/run_all.sh`
3. `git add -A && git commit -m "data: refresh" && git push`

Exit codes, from the header of `scripts/refresh_concerts.py`:

| Code | Meaning |
|---|---|
| 0 | ok |
| 1 | liveness failed after a successful write |
| 2 | `CONCERTS` unparseable |
| 3 | config or key missing (`TM_DISCOVERY_API_KEY`) |
| 4 | every venue fetch failed |
| 5 | thin-feed guard (see the `--accept-thin` note) |
| 6 | post-write verification failed (nothing written) |

Notes:
- A venue shows `(zero_rows)` or `(fetch)` in the email: its id in
  `venues.json` is wrong, or Ticketmaster renamed the entity. Look it up
  with `venues.json?keyword=` and check `venue_seen` in a `--dry-run`.
- Exit 5 (thin feed) after a real drop, such as a venue leaving
  Ticketmaster: run `python3 scripts/refresh_concerts.py --accept-thin`
  once. The guard then re-baselines.

## 4. Deploy

```bash
git add -A && git commit -m "your message" && git push
```

Rough time: <30s to build, ~60s to go live on GitHub Pages.

Site URL: https://nendy55555.github.io/la-concert-tracker/ (unlisted — `noindex` + `robots.txt`).

## 5. Swap Claude tiers on the scheduled task

If the Haiku-tier scheduled task starts failing, escalate to Sonnet:

1. Open the scheduled-tasks UI in Claude desktop.
2. Edit `weekly-concert-email`.
3. The prompt body is tier-agnostic; the model tier is set on the task itself. Select Sonnet.
4. Click "Run now" once to confirm it works.

To go back down, reverse the steps. The prompt is just "run the script with `--email`, report exit code" — never needs editing.

## 6. Gmail SMTP auth

If the digest stops sending (exit code 4 / SMTP auth error), the Gmail App Password has likely rotated or been revoked. Fix:

1. https://myaccount.google.com → Security → 2-Step Verification → App Passwords.
2. Generate a new 16-char password (Google shows it as `xxxx xxxx xxxx xxxx` — the script strips spaces on login).
3. Update `.env` in project root: `GMAIL_APP_PASSWORD=<new-value>`.
4. Verify locally: `python3 scripts/weekly_digest.py --horizon-days 180 --email`.
5. The scheduled task picks up `.env` on its next run — no prompt changes needed.

Rotate every ~6 months as hygiene.

## 7. Common failures and fixes

### Symptom: script exits with `ERROR: CONCERTS array is not parseable`
**Cause:** a data edit introduced malformed JS (unbalanced quote, stray character).
**Fix:** `git diff index.html | less` — find the bad row. Restore formatting. Re-run tests.

### Symptom: script runs but `watch_hits` is 0 even though you know shows exist
**Cause #1:** the shows are past `today`. Digest only returns future shows.
**Cause #2:** the horizon is too narrow. Try `--horizon-days 300`.
**Cause #3:** the wishlist name and concert name differ too much for the fuzzy matcher. Edit `WISHLIST_ARTISTS` in `index.html` to add a better variant (e.g. add 'J Cole' in addition to 'JCole').

### Symptom: scheduled task hangs for hours
**Cause:** rare — the send path is now stdlib SMTP with no MCP/network retries beyond Python defaults. If it hangs, it's harness-level (Claude task runner stuck), not the script.
**Fix:** in the scheduled-task UI, cancel the run, disable the task, investigate next session. Run the script locally first to confirm it still sends — if local works, the issue is the runner, not the code.

### Symptom: site looks unstyled
**Cause:** Google Fonts blocked or slow. Fallback stack is already defined; page is still legible.
**Fix:** none required. If annoying, self-host fonts — see DECISIONS.md for why we don't by default.

### Symptom: test `test_venue_set_is_known` fails
**Cause:** a new venue was added to the data but not to the allowlist in `tests/test_index_html_integrity.py`.
**Fix:** add the new venue name to `KNOWN_VENUES` in that file.

### Symptom: tests pass locally but scheduled task fails
**Cause:** the task runs under a different Python (or none). Check the task's log output.
**Fix:** `which python3` — should be `/usr/bin/python3` or similar with 3.11+. If not, edit the prompt to use an absolute path to your Python.

### Symptom: email first line says `STALE` or `Note:`
**Cause:** the first line names the failure class (see DECISIONS.md,
2026-10-26 entry "The email names every failure class").
**Fix:** run `python3 scripts/refresh_concerts.py` by hand, read its stderr,
then read `logs/weekly_run.log`.

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
- `docs/agent/SETUP-GIST-SYNC.md` — watchlist sync setup.
- `docs/agent/archive/` — historical audit + hardening reports + old prompts (read only when investigating that pass).
- `git log --oneline` — full commit history.
