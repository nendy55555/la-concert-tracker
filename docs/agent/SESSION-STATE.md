# Session State

**Last updated:** 2026-10-25 (build shipped)

## Current state
- **Live feed.** `scripts/refresh_concerts.py` pulls upcoming music events
  from the Ticketmaster Discovery API for the venues in `scripts/venues.json`.
  `scripts/weekly_run.sh` runs refresh, tests, git push and digest. The
  Sunday Cowork task calls it once the prompt swap below is done.
- **443 upcoming shows** across 19 venues, 860 rows with history.
- Live at http://concerts.thomasnendick.com, header reads "Data refreshed:
  October 25, 2026 · 443 upcoming shows across 19 venues".
- First live refresh: exit 0, `failed_venues` empty, liveness passed (newest
  date 2027-10-16). Tame Impala ghost row gone.
- State in `data/refresh_state.json`: `last_refresh_rc: "0"`,
  `last_tests_status: ok`, `last_push_status: ok`, plus `last_digest_at` and
  `last_digest_covered_through`.
- Digest first line names every failure class. Current digest: 0 watchlist
  shows at the 19 venues in the next 180 days; 13 on-sale drops in the next
  14 days (System Of A Down at the Rose Bowl, QOTSA and 2hollis at Kia Forum,
  CHVRCHES and Two Door Cinema Club at the Palladium, Ashe at the Wiltern).
- Tests: 74 Python, JS parity 20/20, wrapper checks E26/E27.
  `bash tests/run_all.sh` runs green in about 3 seconds.
- Static site, zero Claude runtime dependency. Watchlist persistence:
  localStorage + optional GitHub Gist sync (gear icon in header).

## In-flight
Nothing in code.

### Waiting on Thomas
1. **Swap the Cowork prompt.** Open the `weekly-concert-email` task in the
   Cowork app and replace the prompt with this one line:
   ```
   bash "/Users/thomasnendick/Documents/Claude/Projects/LA Concert Tracker/scripts/weekly_run.sh"
   ```
   Until the swap, Sunday runs the old prompt. It sends the new-format digest
   on today's data but does not refresh.
2. **Enable HTTPS.** Open github.com/nendy55555/la-concert-tracker, then
   Settings, then Pages. Tick "Enforce HTTPS". Until then
   https://concerts.thomasnendick.com returns nothing.
3. **Verify the first Cowork run** on the new prompt. Read
   `/Users/thomasnendick/Documents/Claude/Projects/LA Concert Tracker/logs/weekly_run.log`
   for `refresh: ok`, `tests: ok` and `git: pushed`.

## Known issues
- **Hollywood Bowl duplicates (pre-existing, untouched).** `run_all.sh` warns
  about 2 duplicate rows in past data: Orville Peck 2026-09-18, Jon Bellion
  2026-09-24.
- **Gist wiring gap.** `weekly_digest.py` doesn't fetch the user's gist, so
  artists added in the UI don't reach the weekly email yet.
- **Hollywood Bowl LA Phil season.** Check it in May 2027.
- **`watchlistAnywhere` flag.** Idea only, not built.
- **Feed rows.** `spotifyMonthlyListeners` is 0 on feed rows.
- **Empty on-sale dates.** ~435 events have empty `onSaleDate`/`presaleDate`.
- **Thin venues.** Fonda Theatre and Troubadour data is thin (JS-rendered,
  Firecrawl scraped poorly).
- **Untracked venues.** Watchlist artists Disco Lines, Chris Lake, Mau P,
  Cloonee, Wes Mills and ATRIP play venues outside the 19 (LA State Historic
  Park, Sound, Echoplex, Time Nightclub). Mau P plays BMO Stadium on
  2027-01-30 by choice.

## Recent sessions (newest first)

### 2026-10-25: Diagnosis, gate, build (Thomas: "haven't heard of new concerts in months")
- **Diagnosis.** The send path was fine. The data was the problem. Probed the
  Ticketmaster Discovery API with Row 5's key. Every tracked venue is covered.
  Watchlist artists with LA dates on Ticketmaster in the next 8 months: 5 of
  40, mostly festivals at NOS Events Center.
- **Gate.** SPEC, EVALS (33 code-graded cases) and PLAN (Tasks 0 to 9) written
  in `docs/agent/specs/concert-feed/`. Two blind reviews. 5 blocking findings
  in total, all accepted and folded into the plan. Round 1: the parser broke on
  real names and `SystemExit` fired in the verify path; rollback erased the
  failure evidence; tests hardcoded 2027. Round 2: the zero-rows guard
  protected a venue for one week only; a refresh crash never reached the
  email. Stopped at two rounds.
- **Build.** Tasks 0 to 9 are committed on `main` and pushed. Built through
  implementer subagents in this session, since the app refused to open a fresh
  one. Details in [[la-concert-tracker]] and the brain log.

### 2026-06-02 — Data refresh (user flagged stale emails)
- Diagnosed: weekly emails were sending fine but data hadn't moved in ~5.5 weeks. Root cause = no scraper; `CONCERTS` is a static JS array.
- Scraped The Wiltern's official 2026 calendar (Jul–Dec) + Hollywood Bowl + Hollywood Palladium for new announcements. Added **41 new shows** (39 Wiltern, 1 Hollywood Bowl, 1 Hollywood Palladium).
- New watchlist hit: Polo & Pan @ Hollywood Bowl 2026-10-08 (supporting Empire of the Sun).
- `index.html` 2567 → 2617 lines; CONCERTS 399 → 440 rows.
- All 43 Python + 9 JS tests pass. Digest run confirms 6 watch_hits (was 5).
- Also bundled the un-pushed 2026-05-12 docs consolidation + SMTP refactor that was sitting in the working tree.
- **Next time data feels stale**: scrape Greek Theatre, Kia Forum, Hollywood Palladium calendars + run a watchlist sweep on Songkick. Or build the automated scraper (option B from the chat).

### 2026-05-12 — Docs consolidation
- Archived AUDIT.md, HARDENING-INVENTORY.md, HARDENING-REPORT.md, POST-MAX-PLAYBOOK.md → `docs/agent/archive/`.
- Slimmed QUICKSTART.md, SESSION-STATE.md, RUNBOOK.md to current-state-only.
- Refreshed memory files.
- Goal: lower token cost on session startup.

### 2026-05-04 — Weekly digest sends via SMTP
- Replaced `create_draft` path with direct Gmail SMTP send (Python stdlib `smtplib`).
- New `.env` (gitignored) with `GMAIL_SENDER` + `GMAIL_APP_PASSWORD`; `.env.example` checked in.
- Scheduled task prompt updated: now runs script with `--email`, no LLM in the send path.
- Added 5 SMTP/env tests (43 total). Live send confirmed delivered.

### 2026-04-27 — Gist sync + WISHLIST union bugfix
- Fixed bug where `trackedArtists` init replaced hardcoded `WISHLIST_ARTISTS` on every load; now unions case-insensitively.
- Added GitHub Gist auto-sync for watchlist + tracked artists (gear icon → modal, PAT + gist ID, debounced PATCH, status indicator). Graceful fallback if no PAT.
- New doc: `SETUP-GIST-SYNC.md`.

### 2026-04-20 — Hardening pass (one-time)
- Moved weekly digest off Claude reasoning → pure Python script. ~98% reduction in Claude calls/run.
- Added test suite. Downgraded scheduled task tier Sonnet → Haiku.
- Full reports in `archive/AUDIT.md`, `archive/HARDENING-REPORT.md`, `archive/POST-MAX-PLAYBOOK.md`.

## Next-session entry points
1. **Verify the first Cowork run** on the new prompt (Waiting on Thomas, item 3).
2. **Optional:** `watchlistAnywhere` flag, Gist wiring.
