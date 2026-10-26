# Concert feed: eval set

**Tier:** Standard (emailed weekly, relied on). 33 cases (E0 to E27 plus E2b, E9b, E11b, E12b, E12c, E14b). All code-graded with
`unittest`, zero network, fixtures under `tests/fixtures/`. Every case names its
pass condition so two graders reach the same verdict.

**Suites**
- Regression (holds at 100%): everything below plus the existing 43 Python and
  9 JS cases. Runs via `bash tests/run_all.sh`.
- Capability: none yet. When the first real-world miss appears (a show Thomas
  knows about that the feed did not return), it becomes a DEBUG.md entry and a
  new case here.

**Sources:** `brain/concepts/silent-failure.md` (stale default, swallowing
aggregator, unchecked return), the 2026-06-02 stale-email incident, the Tame
Impala ghost row found 2026-10-25, the Dave Hause / Dave Koz false match seen in
the API probe 2026-10-25.

## Fixtures

- `tests/fixtures/tm_events_sample.json`: one Discovery API page shaped like the
  real response, four events: a music show at The Novo with public sale and two
  presales; a Lakers game at Crypto.com Arena (segment Sports); a cancelled show
  at The Wiltern; a music show at Troubadour with `dateTBD: true`.
- `tests/fixtures/tm_events_page2.json`: a second page for pagination, one event,
  `page.totalPages: 2`.
- `tests/fixtures/matcher_cases.json`: shared Python/JS matcher cases
  (`{watch, artists, name, expect}`).
- `tests/fixtures/mini_index_feed.html`: a copy of `mini_index.html` with the
  refresh markers and one future row without `tmId` at a covered venue (Tame
  Impala, Kia Forum). The digest suite rewrites `mini_index.html` from a
  constant, so the refresh suite needs its own file.
- Parser round-trip names for E0: `Tyler, The Creator “CHROMAKOPIA” Tour`,
  `Dawes, Live: An Evening`, a name ending in a backslash, one with braces,
  brackets and `//`, one with accents and an en dash.

## Cases

### Parser (`weekly_digest._js_array_to_python` with `refresh_concerts.render_row`)

| # | Case | Pass condition |
|---|---|---|
| E0 | Hard names round-trip | Five rows with the names above rendered by `render_row` and parsed back are `==` to the input dicts; a legacy single-quoted row with a `// comment` line still parses. |

### Mapping (`event_to_row`)

| # | Case | Pass condition |
|---|---|---|
| E1 | Novo music event → row | `date == "2026-11-20"`, `venue == "The Novo"` (canonical, not "The Novo by Microsoft"), `name` is the event name, `artists == ["Headliner Name", "Opener Name"]`, `support == "Opener Name"`, `ticketUrl` is the event url, `ticketVendor == "AXS"` (from venues.json), `onSaleDate == "2026-05-29T10:00"` (UTC 17:00 → PT), `presaleDate == "2026-05-28T10:00"` (earliest presale), `tmId == event id`, `spotifyMonthlyListeners == 0`, `firstSeen == "2026-10-26T09:05:00-07:00"` (the injected `now`). |
| E2b | Venue in another state | Same event with `venues[0].state.stateCode == "NM"` → `None`; with `"CA"` → a row. |
| E2 | Sports segment event | `event_to_row` returns `None`. |
| E3 | Cancelled status, and separately `dateTBD: true` | Both return `None`. |
| E4 | Genre map | `map_genre("Hip-Hop/Rap") == "Hip-Hop/R&B"`, `"R&B" → "Hip-Hop/R&B"`, `"Dance/Electronic" → "Electronic/EDM"`, `"Metal" → "Rock"`, `"Alternative" → "Rock"`, `"Folk" → "Indie/Folk"`, `"Latin" → "Latin"`, `"Punk" → "Punk"`, `"Jazz" → "Other"`, `None → "Other"`. Every value is in `KNOWN_GENRES`. |
| E5 | Pagination | With a fake fetcher serving page 0 then page 1, `fetch_venue_events` returns 2 rows (the Novo show and the page-2 show), one HTTP call per page, a duplicate `tmId` across pages collapses to one row, every URL carries `startDateTime` of today and `endDateTime` of today + 365 days, and the `seen` dict records `{"KovZ917A25f": "The Novo by Microsoft, ?"}`. |

### Merge (`merge_rows`)

| # | Case | Pass condition |
|---|---|---|
| E6 | Past rows preserved | Given 3 past rows and 2 future rows in `existing`, `merge_rows(existing, fetched={venue: rows}, failed=set(), today)` output starts with the 3 past rows unchanged (`==` on dicts). |
| E7 | Ghost row dropped | A future row at "Kia Forum" with no `tmId` is absent from output when "Kia Forum" is in `fetched` (even if `fetched["Kia Forum"]` is empty). |
| E8 | `firstSeen` carried | A fetched row whose `tmId` exists in `existing` with `firstSeen: "2026-09-01"` keeps `"2026-09-01"`; a fetched row with a new `tmId` keeps the `firstSeen` the fetch stamped on it (the run's `now`). |
| E9 | Failed venue isolation | With `failed={"The Fonda Theatre"}`, existing future Fonda rows (with or without `tmId`) are all present in output; other venues' future rows are replaced. |
| E10 | Output sorted | Output is sorted by `(date, name.lower())`. |

### Guards and write (`main` with injected fetcher)

| # | Case | Pass condition |
|---|---|---|
| E11 | Thin feed | State says `future_rows: 400`; fetcher returns 40 future rows total → exit code 5, `index.html` bytes unchanged, state `last_attempt_status == "thin_feed"`, `last_success_at` unchanged. |
| E11b | Accept thin | Same setup with `accept_thin=True` → exit 0 and state `future_rows == 40`. |
| E12 | All venues fail | Fetcher raises for every venue → exit 4, `index.html` unchanged, state `last_attempt_status == "all_failed"`. |
| E12b | Zero rows with existing future rows | Kia Forum's feed returns 0 while the fixture holds a future Kia Forum row (the Tame Impala ghost). Run twice in a row: both runs exit 0, both report `failed_venues == ["Kia Forum (zero_rows)"]`, and the row survives both. |
| E12c | Zero rows with no existing future rows | The Fonda's feed returns 0 and the fixture has no future Fonda row → exit 0, `failed_venues == []`, `per_venue["The Fonda Theatre"] == 0`. |
| E13 | Missing key | `TM_DISCOVERY_API_KEY` unset and absent from `.env` → exit 3 before any fetch (fetcher call count 0). |
| E14 | Round trip | Successful run → `weekly_digest.load_data(new_index)` parses; row count equals `len(past) + len(fetched future)`; the text before `const CONCERTS = [` and after the closing `];` is byte-identical to the original except inside the refresh markers; no `*.tmp` file remains. |
| E14b | Parse failure | A corrupted `CONCERTS` opener → exit 2 and state `last_attempt_status == "parse"`; the process does not die on `SystemExit`. |
| E15 | Refresh stamp | After a successful run with `today=2026-10-26` and 212 future rows, the markers enclose exactly `Data refreshed: October 26, 2026 &bull; 212 upcoming shows across 19 venues`. |
| E16 | State on success | `last_success_at` and `last_attempt_at` are the run's ISO timestamp, `future_rows == 240`, `per_venue` has 19 keys, `failed_venues == []`, `last_attempt_status == "ok"`, the summary has `venue_seen`, and foreign keys (`last_digest_at`, `last_digest_covered_through`, `last_tests_status`, `last_push_status`, `last_refresh_rc`) pass through untouched. |
| E17 | Liveness floor | A successful fetch whose newest future date is under 60 days out, or whose future count is under 20, exits 1 after writing (data is written, the verdict is loud). Printed line contains `FAIL`. |

### Matcher (Python and JS, shared fixture)

| # | Case | Pass condition |
|---|---|---|
| E18 | Exact on attractions | `artists=["Dave Hause & The Mermaid"]`, watch `Dave` → False. `artists=["Dave"]` → True. `artists=["Fred again.."]`, watch `Fred Again` → True. `artists=["J. Cole"]`, watch `JCole` → True. `artists=["ODESZA"]`, watch `Odesza` → True. `artists=["Jungle Brothers"]`, watch `Jungle` → False. |
| E19 | Legacy rows | `artists=[]`, name `Kendrick Lamar - Grand National Tour`, watch `Kendrick Lamar` → True. `artists=[]`, name `Dave Koz Christmas`, watch `Dave` → False (term under 5 chars). `artists=[]`, name `Notion`, watch `Notion` → True. |
| E20 | JS parity | `node tests/js_matcher_parity.js` evaluates every case in `matcher_cases.json` with the `index.html` matcher and reports `N/N cases match`, exit 0. |

### Digest

| # | Case | Pass condition |
|---|---|---|
| E21 | New since | State `last_digest_covered_through: "2026-10-19T09:05:00-07:00"`, today `2026-10-26`; rows with `firstSeen` `2026-10-20T09:05` (watchlist), `2026-10-23T09:05` (tier 4 venue, not watchlist), `2026-10-10T09:05` (watchlist), `2026-10-19T15:30` (tier 3, hand-refreshed after the last digest), `2026-10-24T09:05` (tier 1). Text output has a `NEW SINCE Oct 19` section listing the watchlist row first, then the tier 4 and the same-day-later rows, and neither the old row nor the tier 1 row. |
| E22 | New on-sales | Row with `onSaleDate: "2026-10-22T10:00"` appears under the new section as an on-sale; `onSaleDate: "2026-10-01T10:00"` does not. |
| E23 | Section omitted | No rows newer than `last_digest_date` → text does not contain `NEW SINCE`. |
| E24 | Data age | State `last_success_at` 1 day ago → text contains `Data refreshed 1 day ago`. 10 days ago → contains `STALE`. `last_attempt_status: "all_failed"` with a fresh `last_success_at` → contains `last refresh attempt failed`. Non-empty `failed_venues` → each entry named. `last_tests_status: "tests_failed"` → contains `tests failed`. `last_push_status: "failed"` → contains `site push failed`. `last_refresh_rc: "1"` → contains `refresh exited 1`. `last_attempt_at` 8 days ago → contains `no refresh attempt in the last 2 days`. The feed line is the fourth line of the text render. |
| E25 | Bootstrap and missing state | State without `last_digest_covered_through` → no `NEW SINCE`, text contains `Feed connected`. No state file at all → digest still renders, text contains `refresh state missing`. |

### Wrapper (shell, in `run_all.sh`)

| # | Case | Pass condition |
|---|---|---|
| E26 | Refresh failure does not block | In a scratch clone with the working-tree wrapper copied in: `REFRESH_CMD=false TESTS_CMD=true DIGEST_CMD="exit 7" SKIP_GIT=1 bash scripts/weekly_run.sh` exits 7, its log contains `refresh: failed`, and state `last_refresh_rc == "1"`. |
| E27 | Failed tests restore data, keep evidence | In the scratch clone, with HEAD's state holding an older `last_digest_covered_through` and the working tree a newer one: `REFRESH_CMD="echo x >> index.html" TESTS_CMD=false DIGEST_CMD=true SKIP_GIT=1 bash scripts/weekly_run.sh` exits 0, `git diff --quiet index.html` passes, and state holds `last_tests_status == "tests_failed"`, the newer `last_digest_covered_through`, and `last_refresh_rc == "0"`. |

## Reference solutions

Each case's reference is the implementation in PLAN.md; the fixture values above
are the oracle. E1's timezone expectation was checked by hand: 2026-05-29T17:00Z
is 10:00 PDT.
