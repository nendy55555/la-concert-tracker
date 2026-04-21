# Session State

## Last Updated
2026-04-20

## Completed This Session (deploy)
- Published site to GitHub Pages: https://nendy55555.github.io/la-concert-tracker/
- Added `noindex` meta tag + `robots.txt` for unlisted access
- Added `.gitignore` (macOS + editor noise)
- Replaced placeholder README with real project README
- Initialized git repo, pushed to `github.com/nendy55555/la-concert-tracker`

## Incident: weekly-concert-email hung 2026-04-19
- Scheduled task fired on Sun 4/19 09:09 PT as expected.
- Firecrawl API returned "out of credits" (same issue as 4/4).
- Bot fell back to WebSearch (~24 searches), then called `create_draft` — the call hung.
- Session ran for ~27 hours before manual intervention on 4/20.
- No draft was created; no email was sent.
- Root cause: prompt had no hang guard on `create_draft`, no retry ceiling on WebSearch fallback, and a Chrome auto-send step that was unreliable.
- **Fix applied 2026-04-20:** rewrote the task prompt to be WebSearch-only (skip Firecrawl entirely), capped searches at ~25, removed Chrome send, and added a 60s hang guard on `create_draft` with no retries. Manual digest sent as a recovery email (draft created 4/20, subject "🎵 LA Concert Weekly — April 19, 2026 (recovery delivery)").
- **Follow-up 2026-04-20:** Thomas flagged the first recovery draft said "No new watchlist matches this week" — that section was a *delta* (new since last week) instead of a full roster. Rebuilt the watchlist section to list **all** watchlist artists with LA shows (5 total: J. Cole x2 at Intuit Dome, Jack Harlow at Hollywood Palladium, JUNGLE at Crypto.com, Tame Impala at Kia Forum) plus a "no LA shows in tracker" list for the remaining 32 artists with a note on non-tracked venues (BMO Stadium, LA State Historic Park). New draft created, subject "🎵 LA Concert Weekly — April 19, 2026 (watchlist fix)".
- **Prompt update needed for next run:** change scheduled task prompt from "new watchlist matches since last week" to "all watchlist artists with upcoming LA shows" — delta framing caused the empty-section bug.

## Completed This Session
- Feature 8: Past event dimming + "Hide past" toggle
  - Calendar: past days get 0.3 opacity, collapsed to show count only when "Hide past" on
  - List view: past events shown with 0.35 opacity and dimmed date headers; filtered out when "Hide past" on
  - My Artists table: past shows filtered out when "Hide past" on, dimmed when shown
  - Modal: past events marked with "PAST" badge and reduced opacity
  - "TODAY" badge on current day in calendar view
  - "— TODAY" / "— PAST" label in modal header
  - "Hide past" checkbox in filter bar (default: on)
  - Show count in result counter respects hide-past state
- Feature 9: Daily concert watchlist notification (scheduled task)
  - Scheduled task `la-concert-watchlist-alert` runs daily at 9am
  - Scrapes all 18 venue pages via Firecrawl search
  - Diffs against existing CONCERTS array in index.html
  - Checks new concerts against WISHLIST_ARTISTS via fuzzy match
  - Emails tjnendick5@gmail.com with watchlist matches (skips email if nothing new)

## Previously Completed (earlier sessions)
- Feature 1: Data refresh via Firecrawl (149→428 concerts)
- Feature 2: Google Calendar export ("Add to Cal" button)
- Feature 3: On-sale date infrastructure (fields, CSS, getSaleBadge function)
- Feature 4: Ticket vendor identification + on-sale date tracking
- Feature 5: Venue-based price tiers ($/$$/$$$/$$$$)
- Feature 6: Data gap fixes (vendor defaults, formatListeners, support act cleanup)
- Feature 7: Support/opener act visibility (modal, list, calendar, My Artists)

## Files Changed
- `index.html` — all changes (single-file app), now ~2200 lines

## Known Issues
- Only 5 events have on-sale dates populated; 423 still empty
- Fonda Theatre and Troubadour data still thin (JS-rendered pages)
- Spotify listener counts default to 0 for ~280 scraped entries
- Price ranges are venue-level estimates, not per-event actuals
- No deployment (local file only)
- Scheduled task needs first manual "Run now" to approve tool permissions

## Decisions
- "Hide past" defaults to ON — most users want to see upcoming shows
- Past calendar days still show event count (not fully hidden) for context
- Scheduled task runs at 9am daily, emails only when new watchlist matches found

## Next Session Start
- Run the scheduled task manually once to approve tool permissions
- Conflict detection (flag same-night watchlisted artists)
- Batch-scrape Ticketmaster event URLs for more on-sale dates
- Populate Spotify monthly listener counts for ~280 entries still at 0
- Deployment (GitHub Pages or similar)
