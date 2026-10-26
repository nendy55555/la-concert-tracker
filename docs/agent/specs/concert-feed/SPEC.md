# Concert feed: live data for the LA Concert Tracker

**Slug:** `concert-feed` · **Written:** 2026-10-25 · **Gate:** build-gate, Standard eval tier

## What it does

Replaces the hand-pasted `CONCERTS` array with a weekly pull from the Ticketmaster
Discovery API for the 19 venues the tracker already covers. A new script,
`scripts/refresh_concerts.py`, fetches every upcoming music event at those venues,
maps each one to the existing row shape (plus three new fields: `tmId`, `artists`,
`firstSeen`), replaces the future rows inside `index.html`, stamps the page's
"Data refreshed" line, and records a state file. The weekly digest then leads with
what is new since the previous email (new shows and newly opened on-sales,
watchlist first), states how old the data is, and refuses to look healthy when the
refresh has failed. A wrapper, `scripts/weekly_run.sh`, chains refresh, tests,
commit and push, then the existing digest send, so the Sunday Cowork task keeps
running one command.

## Why now

The tracker has reported one show for a month, and that show does not exist
(Tame Impala, Kia Forum, 2026-11-14: Slayer is playing). The data was last
refreshed 2026-06-02. 39 of 40 watchlist artists have no LA show in the array.
This was flagged once already in June and patched by hand; the root cause,
no data source, was never fixed.

What it makes cheaper next: a Ticketmaster venue-calendar client and a "replace
the future, keep the past" merge are reusable for the Ticket Tracker and Row 5
(both already hold the same `TM_DISCOVERY_API_KEY`). Candidate accelerator:
`tm-venue-feed`, promote only after a second consumer appears.

## Decisions taken in the interview (2026-10-25)

| Question | Thomas chose | Consequence |
|---|---|---|
| Venue scope | **Only the current 19 venues** (18 + Peppermint Club) | Watchlist artists at untracked rooms (Mau P at BMO Stadium 2027-01-30, festival sets at NOS) stay invisible. Listed under out of scope with a one-flag path back. |
| Email lead | **New since last week** | Digest gets a top section: new shows and new on-sales since the previous digest, watchlist first, then new shows at tier 3 and 4 venues. Omitted when empty. Always states data age. |
| Runner | **Fold into the Sunday Cowork task** | One wrapper script. Refresh failure must never block the send; the digest reports the failure instead. |

## Files and interfaces

**Create**
- `scripts/venues.json`: the 19 venues, each `{name, tmVenueIds: [...], vendor, tier}`. One canonical venue can map to several Ticketmaster venue entities (Shrine Auditorium also covers Shrine Expo Hall; El Rey's live entity is "El Rey Theatre - Los Angeles", id `Z6r9jZkv7e`, not the dead `KovZpZAkJnnA`). An empty `tmVenueIds` marks a venue the feed does not cover: its existing future rows are kept. `tier` is the 1 to 4 price tier already in `VENUE_PRICE`, read by the digest to decide which non-watchlist shows count as notable. The fragile part lives in config (scraping-decay route 3). All 19 ids were resolved against the live API on 2026-10-25.
- `scripts/refresh_concerts.py`: fetch, map, merge, guard, write, state. Stdlib only.
- `scripts/liveness.py`: copy of `Accelerators/packages/liveness/src/liveness.py`, header kept.
- `scripts/weekly_run.sh`: the one command the Cowork task runs.
- `data/refresh_state.json`: committed. `last_success_at`, `last_attempt_at`, `last_attempt_status`, `future_rows`, `per_venue` counts, `last_digest_date`.
- `tests/test_refresh_concerts.py`, `tests/fixtures/tm_events_sample.json`, `tests/fixtures/matcher_cases.json`.

**Modify**
- `index.html`: the `CONCERTS` block is rewritten by the script between `const CONCERTS = [` and its closing `];`. The `.last-updated` div gets `<!--LAST_REFRESH:START-->…<!--LAST_REFRESH:END-->` markers. Calendar navigation crosses year boundaries and the header year follows the displayed month. `isWatchedArtist` uses `c.artists` when present.
- `scripts/weekly_digest.py`: matcher precision rule, "New since" section, data-age line, reads and writes `data/refresh_state.json`.
- `tests/test_index_html_integrity.py`: `KNOWN_GENRES` gains `Other`; a test asserts the refresh markers exist.
- `tests/js_matcher_parity.js`, `tests/run_all.sh`.
- `Scheduled/weekly-concert-email/SKILL.md`, `docs/agent/{QUICKSTART,RUNBOOK,SESSION-STATE,DECISIONS}.md`.
- `.env`: gains `TM_DISCOVERY_API_KEY`, copied from `Projects/Row 5/scanner/.env` by a shell command, never echoed.

**Row shape after this change**

```jsonc
{ date, name, venue, genre, support, spotifyMonthlyListeners: 0, ticketUrl,
  ticketVendor, onSaleDate, presaleDate,
  tmId: "vvG10Z_58XADKo",                    // "" on legacy rows
  artists: ["Tom Jones"],                     // attraction names; [] on legacy rows
  firstSeen: "2026-10-26T09:05:00-07:00" }    // ISO timestamp of the refresh that first saw this tmId; "" on legacy rows
```

`REQUIRED_FIELDS` in the integrity test is unchanged; the three new fields are
optional so legacy past rows still pass.

## Behaviour that must hold

1. **Past is history, future is the feed.** Rows dated before today are kept
   value-for-value (the whole array is re-rendered in one consistent style, so
   quoting may change; parsed dicts do not). Rows dated today or later are
   replaced, per venue, by what Ticketmaster returns. A future row with no
   `tmId` at a covered venue is dropped: that is how the Tame Impala ghost dies.
   A venue with empty `tmVenueIds` is uncovered and keeps its future rows.
2. **Per-venue failure isolation.** If one venue's fetch fails after retries,
   or returns zero events while `index.html` still lists future shows there (a
   dead or renamed venue id looks exactly like that), that venue's existing
   future rows are kept and the venue is named in the state file and the
   digest, on every run until it recovers. Only when every venue fails does the
   run exit non-zero without writing. A venue in another state can never be
   stamped with an LA name: events whose Ticketmaster venue carries a
   `stateCode` other than `CA` are dropped.
3. **Thin-feed guard.** If the fetched future row count is under 50% of the
   previous run's `future_rows`, nothing is written and the exit code says so.
   A feed that quietly returns 12 rows must not overwrite 400.
4. **Atomic, verified write.** The new `index.html` is parsed with
   `weekly_digest.load_data` before it replaces the old one; everything outside
   the `CONCERTS` block and the refresh markers is byte-identical.
5. **Precision over recall in the matcher.** When a row carries `artists`, a
   watchlist name matches only by exact normalized equality with an attraction
   name. Legacy rows keep the substring rule, restricted to watch terms of five
   or more normalized characters, so `Dave` stops matching Dave Koz.
6. **The email never looks healthy on stale data.** Every digest states the
   refresh age as its first line under the title, and appends every failure
   class present: ten days or older (STALE), a failed last attempt, a refresh
   that exited non-zero without recording a result, no refresh attempt in the
   last two days, venues not refreshed, tests failed after the refresh (data
   rolled back), site push failed.
7. **First run is quiet.** With no `last_digest_covered_through` in state, the
   digest omits the "New since" block and prints "Feed connected" with the row
   count instead of listing 400 shows as new. From then on "new" means first
   seen after the refresh the previous digest showed, so a hand-run refresh
   later the same Sunday still counts the following week.
8. **Refresh failure never blocks the send.** `weekly_run.sh` runs the digest
   whatever the refresh and test outcomes, restores `index.html` from HEAD if
   the test suite fails after a refresh while keeping the failure evidence in
   the state file (it never restores that file wholesale), records the
   refresh exit code and the push result, and exits with the digest's code.

## Accelerators used

- `liveness` (extracted): `check_max_date` on the written future dates
  (newest date at least 60 days out) and a minimum future-row floor of 20, run
  after the write. Copied file, provenance header kept, Python 3.10 syntax
  allowed in callers only (the module itself stays 3.9-clean).
- `scheduled-task-template` conventions for `SKILL.md` exit codes.
- Not used: `notify` (candidate only; SMTP path already exists and works),
  `browser-state-import` (no bot wall here, the API is public).

## Explicitly out of scope

- Any venue beyond the 19. The design keeps a one-line path back: a
  `watchlistAnywhere: true` flag in `venues.json` would add a `keyword` query
  per watchlist artist over `dmaId=324`. Not built.
- The Gist-synced watchlist reaching the digest (carried-over known issue).
- `spotifyMonthlyListeners`: stays 0 for feed rows.
- A NEW badge in the UI. The email carries "new"; the page gets a correct
  refresh stamp and year navigation only.
- Moving the task to launchd. Thomas chose the Cowork task; the wrapper is
  written so a launchd plist could call the same script later.
- Deleting the two duplicate-send weeks (Jul 26, Aug 8/9) from history or
  investigating the Sep 13 and Sep 20 missed sends.
- Ticket price ranges from TM (`priceRanges` is usually absent).

## End-to-end verification

1. `python3 scripts/refresh_concerts.py` from the project root exits 0, prints a
   JSON summary with `per_venue` counts for 19 venues, `future_rows` between 150
   and 700, and `failed_venues: []`.
2. `bash tests/run_all.sh` passes, including the new suites.
3. `git log -1` shows the data commit; after `git push`,
   https://nendy55555.github.io/la-concert-tracker/ shows
   "Data refreshed: <today> · N upcoming shows across 19 venues" and the
   calendar reaches January 2027.
4. `python3 scripts/weekly_digest.py --horizon-days 180 --text` shows the
   "Feed connected" line, zero Tame Impala, and a data age of 0 days.
5. `bash scripts/weekly_run.sh` with `DIGEST_ARGS="--email-to tjnendick5@gmail.com"`
   lands one email at Thomas's address. The next Sunday's Cowork run (after he
   swaps the task command) produces the first real "New since" block.

## Open questions and the assumption in use

| Question | Assumption until answered |
|---|---|
| Does Ticketmaster list the Hollywood Bowl's LA Phil summer season, or only Live Nation bookings? | TM lists it. Check in May 2027 when the Bowl calendar drops; if not, a `manual_concerts.json` override is a half-day task. |
| Does the Cowork task's `python3` resolve to Homebrew 3.15 (as `scripts/__pycache__/*.cpython-310.pyc` and the running digest's `str \| None` syntax imply)? | Yes. The wrapper logs `python3 --version` on every run so a change is visible. |
| Are the two recipients (Thomas, thomasandmariah@) still right? | Unchanged. `EMAIL_TO` in `.env` is not touched. |
| How many events per venue per page does the Discovery API return at `size=200`, and does `totalPages` ever exceed 5 for one venue? | 200 per page, no venue exceeds 2 pages (Crypto.com Arena had 106 upcoming across all segments). The client pages until `totalPages` with a cap of 10. |
