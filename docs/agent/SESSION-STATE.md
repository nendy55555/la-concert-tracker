# Session State

**Last updated:** 2026-10-25 (diagnosis + build gate for the Ticketmaster feed)

## Current state
- **440 concerts**, 18 canonical venues (+Peppermint Club defensive entry), Apr 2026 – Dec 2026.
- Data last refreshed 2026-06-02 and never pushed. Local HEAD is 2026-04-24. origin/main has one extra commit, "Create CNAME" (2026-05-14). The June data lives only in the working tree.
- Live site serves the April data (399 shows): http://concerts.thomasnendick.com. HTTPS on that domain returns nothing. GitHub Pages never provisioned a cert.
- Also deployed at https://nendy55555.github.io/la-concert-tracker/.
- Weekly email sends every Sunday from the Cowork task `weekly-concert-email` (09:03 PT, Haiku). It is not in Claude Code's scheduled-task list. It landed every week since June except 2026-09-13 and 2026-09-20.
- 23 future rows remain. 39 of 40 watchlist artists have no LA show in the array.
- The one watchlist hit, Tame Impala at Kia Forum on 2026-11-14, does not exist. Slayer plays the Forum that night.
- Static site: zero Claude runtime dependency.
- Watchlist persistence: localStorage + optional GitHub Gist sync (gear icon in header).
- Tests: 43 Python + 9 JS parity. `bash tests/run_all.sh` < 2s.

## In-flight
**Concert-feed build: gate passed, not yet built.**
- Spec, eval set (33 code-graded cases), plan (Tasks 0 to 9) and two blind reviews with adjudication live in `docs/agent/specs/concert-feed/` (SPEC.md, EVALS.md, PLAN.md, REVIEW.md).
- The build runs in a fresh session, per the gate.
- Decisions from the 2026-10-25 interview:
  - Only the 19 current venues.
  - The email leads with "new since last week".
  - The refresh folds into the Sunday Cowork task.

## Known issues
- **No auto-refresh of `CONCERTS`** — data is hardcoded in `index.html` and only updates when a human (or scheduled scraper) edits it. Manually refreshed 2026-06-02; will go stale again.
- ~435 events have empty `onSaleDate`/`presaleDate`.
- Fonda Theatre and Troubadour data thin (JS-rendered, Firecrawl scraped poorly).
- ~320 entries have `spotifyMonthlyListeners: 0`.
- Many watchlist artists (Disco Lines, Chris Lake, Mau P, Cloonee, Wes Mills, ATRIP) play untracked venues — LA State Historic Park, Sound Nightclub, Echoplex, Time Nightclub. Consider expanding venue list.
- Possible stale entry: Tame Impala 2026-11-14 may actually be a 2025 show (Deadbeat tour ends Sep 2026). Worth verifying. Verified 2026-10-25: no such show at the Kia Forum. See the 2026-10-25 session.
- `weekly_digest.py` doesn't fetch the user's gist — UI-added artists don't flow into the weekly email yet.
- **Matcher over-fires.** The digest and the UI both match watchlist names by substring in either direction. "Dave" hits Dave Hause and Dave Koz. Fix is in the plan, Task 5.
- **Header date is hardcoded.** `index.html` header still says "Data refreshed: March 31, 2026".
- **Calendar cannot reach 2027.** `prevMonth`/`nextMonth` clamp to one year, and `currentYear = 2026` is hardcoded.
- **Digest parser breaks on certain names (latent).** The digest's JS-to-JSON parser fails on names containing `, Word:` or curly quotes. No current row hits it. Task 2a.

## Recent sessions (newest first)

### 2026-10-25: Diagnosis and build gate (Thomas: "haven't heard of new concerts in months")
- The send path was fine. The data was the problem.
- Probed the Ticketmaster Discovery API live with Row 5's key. Every tracked venue is covered: Wiltern 72 upcoming music events, Regent 88, Fonda 53, Troubadour 25, Palladium 44, Novo 35, Kia Forum 36, Roxy 31, El Rey 15, Bowl 14, Intuit 70, Crypto.com 106 (includes non-music).
- All 19 venue ids resolved. El Rey's live entity is `Z6r9jZkv7e`.
- Watchlist artists with LA dates on Ticketmaster in the next 8 months: 5 of 40. Most are festivals at NOS Events Center. Mau P plays BMO Stadium on 2027-01-30, outside the 19 venues by Thomas's choice.
- Gate artifacts written. Critic round 1 found 3 blocking issues: the parser breaks on real names and `SystemExit` fires in the verify path; rollback erased the failure evidence; the tests hardcode 2027. Round 2 found 2 blocking issues: the zero-rows guard protected a venue for one week only; a refresh crash never reached the email.
- All blocking findings accepted and folded into the plan. Stopped at two rounds.

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
1. **Build the concert-feed plan in a fresh session.** Start with Task 0 (git fast-forward, then commit the June work). End with Task 9: the first live refresh, a push, and a test send to Thomas only.
2. **After the build, swap the Cowork task prompt** (Thomas does this). Open the `weekly-concert-email` task in the Cowork app and replace the prompt with this single line:
   ```
   bash "/Users/thomasnendick/Documents/Claude/Projects/LA Concert Tracker/scripts/weekly_run.sh"
   ```
3. **Enable HTTPS for the custom domain** (Thomas does this). Open github.com/nendy55555/la-concert-tracker, then Settings → Pages, and tick "Enforce HTTPS". The custom domain gets a cert once the box is ticked.
4. **Carry-overs:** Hollywood Bowl LA Phil season check May 2027, `watchlistAnywhere` flag, Gist wiring (`weekly_digest.py` fetches the gist via `GIST_PAT` + `GIST_ID`).
