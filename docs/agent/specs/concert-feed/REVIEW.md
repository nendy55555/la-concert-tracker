# Concert feed: review log

## Review 1, 2026-10-25

Reviewed blind by `critic` (paths only). Verdict: do not ship as written; three
blocking findings, each with a small fix. Adjudicated by the author below.

| # | Finding | Severity | Decision | Reason |
|---|---|---|---|---|
| B1 | `render_row` + the digest's JS-to-JSON parser break on realistic names (`Tyler, The Creator “CHROMAKOPIA” Tour`, `Dawes, Live: An Evening`); `load_data` exits via `sys.exit(2)` so `run()`'s verify step dies without writing state or cleaning its temp file | BLOCKING | ACCEPT | Reproduced locally: `_js_array_to_python('[{ name: "A, B: C" }]')` raises. New Task 2a makes the parser's key-quoting, trailing-comma and smart-quote passes string-aware (a latent digest bug too), `render_row` uses `ensure_ascii=True`, `run()` catches `SystemExit` around both `load_data` calls, compares `parsed == merged`, and removes the temp file in `finally`. New eval E0 with the three names. |
| B2 | On test failure the wrapper restores `data/refresh_state.json` from HEAD, erasing the failed attempt and rolling `last_digest_date` back a week; the digest then looks healthy and repeats last week's "new" items | BLOCKING | ACCEPT | Wrapper now restores only `index.html` from HEAD and rewrites the state with a Python one-liner: HEAD's success fields, the working tree's `last_digest_date`, `last_attempt_status: "tests_failed"`. E27 asserts the status. |
| B3 | Integrity test hardcodes `year <= 2027`; the feed sends no `endDateTime`; `HORIZON_DAYS` declared and unused | BLOCKING | ACCEPT | Same class as the `default=2025` incident. Test bound becomes `today.year + 2`; fetch passes `endDateTime = today + HORIZON_DAYS`. |
| S1 | Task 4 edits `tests/fixtures/mini_index.html`, which `test_weekly_digest.py` rewrites from a constant on every run, so the refresh suite breaks on the second run | SHOULD-FIX | ACCEPT | Refresh tests get their own fixture, `tests/fixtures/mini_index_feed.html`, created in Task 1. `mini_index.html` is untouched. |
| S2 | Partial venue failures are never named in the digest; a dead venue id returns 0 rows and counts as success, dropping that venue's future rows | SHOULD-FIX | ACCEPT | `run()` treats a covered venue that returns 0 rows while last run's `per_venue` had more than 0 as failed (`zero_rows`), so its rows are kept and it is named. `_feed_status` appends `failed_venues` whenever non-empty, regardless of status. New eval E12b. |
| S3 | The per-artist roster re-matches on `h.name` without `artists` (third call site), contradicting the watchlist section | SHOULD-FIX | ACCEPT | Task 5 lists all three call sites; the roster is built from the matched names already stored on each hit. |
| S4 | `getMatchingConcerts` in `index.html:2450` has a second inline matcher the plan never touches | SHOULD-FIX | ACCEPT | Task 5 Step 5 replaces its inline expression with `artistMatches(c.name, c.artists, [a])`. |
| S5 | Liveness prints `PASS …` to stdout before the JSON summary, so Task 9's `json.load` fails | SHOULD-FIX | ACCEPT | `run_checks` runs under `contextlib.redirect_stdout(sys.stderr)`. |
| S6 | A failed push is invisible in the email; Cowork runtime (node, git creds, egress) never verified by the plan | SHOULD-FIX | ACCEPT in part | Wrapper records `last_push_status` in state and the feed line says "site push failed" when it is not `ok`. Task 9 gains a step: after the first Cowork run, read `logs/weekly_run.log` for `refresh: ok`, `tests: ok`, `git: pushed`. The wrapper logs `node --version` and `git remote -v` so a missing tool is visible. Pre-verifying the VM by hand is not possible from here; the first live run is the test, and the fallback (old-style email on fresh data) is acceptable for one week. |
| S7 | E27 passes before the wrapper is committed (clone has no wrapper) and never asserts exit 0 | SHOULD-FIX | ACCEPT | E27 copies the working-tree wrapper into the clone and asserts `rc=0`. |
| O1 | `.env` append merges lines if the file lacks a trailing newline | OPTIONAL | ACCEPT | Checked: the file does end in a newline today, but the safe form costs nothing: `{ echo; grep …; } >> .env`. |
| O2 | `git add -A` in Task 9 sweeps unrelated in-flight work | OPTIONAL | ACCEPT with a note | Task 9 uses explicit paths. The working tree does hold the never-pushed 2026-06-02 refresh and docs consolidation; those get their own commit first, by name, so the live site stops serving April data. |

Coverage the reviewer reported sound: merge semantics (E6 to E10), thin-feed
math (E11), E14 to E16 counts, `check_max_date` with a negative bound, no
existing row carries keys outside `ROW_KEYS`, every cited path and line number,
E21 to E25 against the planned code, pagination and dedupe, wrapper exit-code
propagation, Python 3.9 compatibility under `from __future__ import annotations`.
Not checked: live Ticketmaster responses, `.env`, the Cowork VM, in-browser
behaviour of Task 7.

Author's own fixes folded in at the same time (found before the review landed):
the `NEW SINCE` header used `_fmt_date(...)[4:]`, which renders `Oct 19, 2026`
and fails E21; replaced with `strftime('%b %-d')`. The digest parses dates with
`date.fromisoformat` inline, not a `_parse_date` helper; the plan now says so.

Shape changed (new Task 2a, wrapper writes state, zero-rows rule), so a second
blind review runs on the revised plan.

## Review 2, 2026-10-25 (revised plan, fresh reviewer, no knowledge of review 1)

Reviewed blind by `critic`. Verdict: ship with fixes. Adjudicated below.

| # | Finding | Severity | Decision | Reason |
|---|---|---|---|---|
| B1 | The zero-rows guard keyed on last week's `per_venue` count protects a venue for one week, then saves `0` and silently wipes it the week after; a dead id on the first run gets no protection | BLOCKING | ACCEPT | Rule now keys on the data: a venue returning 0 rows while `index.html` still holds future rows for it is `zero_rows`, every run, first run included. E12b runs twice in a row and asserts the rows survive both; E12c asserts a venue with no future rows and an empty feed is not flagged. |
| B2 | A crash in `refresh_concerts.py` (import error, corrupt state JSON, OSError) leaves last week's `ok` in state; the email reads healthy for a week | BLOCKING | ACCEPT | Wrapper writes `last_refresh_rc` every run; `_feed_status` notes a non-zero rc and also a `last_attempt_at` older than 2 days (catches the Cowork task still on the old prompt). `run()` catches unreadable state instead of crashing on it. E24 and E26 extended. |
| S3 | `good_http` dates (+30..+41 days) trip the 60-day liveness horizon, so E12b, E14 and E16 fail as written | SHOULD-FIX | ACCEPT | Dates spread `30 + 7*i`; n=12 reaches +107, n=1 (E17) still trips at +30. |
| S4 | E4 asserts `Other` is in `KNOWN_GENRES` before Task 4 adds it | SHOULD-FIX | ACCEPT | The allowlist edit moved to Task 2 Step 0. |
| S5 | Local is behind `origin/main` by the CNAME commit with June work staged; per-task commits would make every later pull and push non-fast-forward, and `--force` would delete the custom domain | SHOULD-FIX | ACCEPT | New Task 0: fast-forward first, then commit the June work by name, before any feature commit. Task 9 Step 0 now only confirms `ahead` with nothing `behind`. |
| S6 | Task 9 Step 2's `;` runs commit and push even when the suite fails | SHOULD-FIX | ACCEPT | Commit and push now sit inside a `&& { … }` block gated on `run_all.sh`. |
| S7 | Nothing proves the 19 ids point at LA rooms; a same-named venue in another city passes every check | SHOULD-FIX | ACCEPT | `event_to_row` rejects a venue whose `state.stateCode` is present and not `CA` (E2b); `fetch_venue_events` records `venue_seen` (TM name, city) per id and the dry run and Task 9 require every city to be in the LA set. The ids were resolved live on 2026-10-25, but the plan now proves it rather than asserting it. |
| S8 | Building the roster from deduplicated hits credits only the first of two watched artists on one show | SHOULD-FIX | ACCEPT | Roster built from pre-dedup `watch_hits`; the roster test now has two watched artists on one show and asserts both. |
| S9 | Day-granular `firstSeen` and `last_digest_date` mean a hand-run refresh on a Sunday afternoon is never reported as new | SHOULD-FIX | ACCEPT | `firstSeen` is now a full ISO timestamp; the digest records `last_digest_covered_through` (the `last_success_at` it rendered) and "new" means `firstSeen > covered_through`. E21 gains a same-day-later row. |
| O10 | A legitimate drop of over 50% trips the thin-feed guard every week with no way out short of hand-editing state | OPTIONAL | ACCEPT | `--accept-thin` flag skips the guard once and re-baselines (E11b); RUNBOOK documents it. |

Coverage the reviewer reported sound: parser change and E0 (fails before, passes after), `_extract_array` against `json.dumps` output, merge semantics, E1/E5/E11/E12/E13/E14b/E17 against the code, `to_pt` PDT math, the `check_max_date` sign convention, `venues.json` tiers and vendors against `VENUE_PRICE` and `VENUE_DEFAULT_VENDOR`, all 11 matcher cases, E26/E27 shell logic, every cited path and anchor line (five `isWatchedArtist(ev.name)` call sites, not six; harmless since the step greps). Not checked: live Ticketmaster behaviour, the Cowork runtime, browser behaviour of Task 7, the custom domain.

**Stopping at two rounds.** Round 2 changed interfaces (`firstSeen` type, `fetch_venue_events` signature, two new state keys) but every change is inside an existing step or a git-hygiene Task 0; no data flow was redesigned. Per `plan-review`, the next independent check is the build session's diff review against this plan, not a third blind round.
