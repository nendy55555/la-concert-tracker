# LA Concert Tracker — Audit

**Date:** 2026-04-20
**Audited version:** `64c29e9` (initial commit)
**Purpose:** Pre-Max-downgrade hardening.

## 1. System map

### Inputs
- `index.html` `CONCERTS` array — 428 concerts, hand-curated and periodically refreshed via Firecrawl venue scrapes.
- `index.html` `WISHLIST_ARTISTS` array — 37 tracked artists.
- `localStorage` `la_concert_watchlist` — per-device starred shows.
- `localStorage` `la_tracked_artists` — per-device custom tracked artists.
- Scheduled task environment — access to MCP Gmail, WebSearch, Firecrawl.

### Transformations
- `normalizeForMatch(str)` — lowercase, strip whitespace, punctuation, and non-alphanumerics. Used for fuzzy artist matching.
- `isWatchedArtist(name)` — normalized substring match either direction.
- `getMatchingConcerts(artist)` — filter CONCERTS by fuzzy match, sort by date.
- `VENUE_DEFAULT_VENDOR` loop — fills missing `ticketVendor` based on venue.
- `getPriceBadge` / `getSaleBadge` / `getVendorBadge` — render badges.
- Date predicates: `isPastDate`, `isToday`.
- Filters: venue set ∩ genre set ∩ `hidePast`.
- Calendar, list, and My Artists renderers — DOM writes only.

### Outputs
- Rendered HTML in the browser.
- `localStorage` writes on star/track.
- `window.open(generateGCalUrl(ev))` — Google Calendar link.
- External links (Ticketmaster, Spotify, Google Calendar).
- Weekly Gmail draft from the scheduled task.

## 2. Claude call sites

### Site A: `weekly-concert-email` scheduled task — runs Sunday 09:03 PT

**What it does today:** WebSearch-only scan (~25 searches) across 18 venues for upcoming LA concerts, cross-reference results against WISHLIST_ARTISTS, compose an HTML digest with watchlist matches + new shows + on-sale drops, save a Gmail draft.

**Classification:** **Replaceable with script.**

**Why:**
- The authoritative CONCERTS dataset already lives in `index.html` in the repo.
- The fuzzy matcher (`normalizeForMatch`) is a pure function — reimplementable in Python in 5 lines.
- The HTML digest is a Mustache-tier template.
- The only irreducibly-Claude operation is calling the Gmail `create_draft` MCP tool. A Haiku-tier prompt can do this: "Run the script, email the output."

**Hardening plan:**
1. Write `scripts/weekly_digest.py` (Python 3, stdlib only) that:
   - Parses `CONCERTS` and `WISHLIST_ARTISTS` out of `index.html` (JS-to-JSON converter, deterministic).
   - Filters to upcoming watchlist matches + on-sale drops in next 14 days.
   - Renders HTML to `dist/weekly_digest.html` + plain text fallback.
   - Prints a JSON summary to stdout (subject line, counts, match list) for the Claude prompt to feed into `create_draft`.
2. Rewrite the scheduled task prompt to: "Run `python3 scripts/weekly_digest.py`, read the output file, create a Gmail draft with the rendered HTML. No searching. No reasoning about music. Zero retries on `create_draft` — if it hangs 60s, abort."
3. Target tier: **Haiku**. Sonnet fallback if Haiku can't reliably call the MCP tool.

### Site B: Data refresh (ad-hoc, not scheduled)

**What it does today:** Firecrawl scrape venues → venue parsers → merge into CONCERTS. Thomas runs this manually a few times a year.

**Classification:** **Genuinely requires Claude reasoning** (for now). Venue pages vary wildly in HTML structure; parsing with regex alone is brittle. Kept as-is but called manually, not on a schedule. Not a recurring cost.

**Post-hardening note:** If this becomes painful post-Max, rewrite per-venue parsers as Python BeautifulSoup scripts. Out of scope for this pass.

### Site C: Static site runtime — `index.html`

**Classification:** **None — zero Claude dependency.** Users load the page, everything runs client-side.

## 3. Dead code / unused features

- Line 2125: `function openModalForEvent(d,n){openModal(d);}` — `n` arg is never read. Candidate for removal, but zero maintenance cost. **Leave.**
- Line 1781: `The Peppermint Club` entry in `VENUE_PRICE` and `VENUE_DEFAULT_VENDOR`, but it's not in the canonical 18-venue list and no concerts reference it. **Leave** (defensive — cheap to keep, risky to remove in case of future data that references it).
- Line 1336 onward: 428 concert rows — no obvious dead rows. A ~28% of rows have `spotifyMonthlyListeners: 0`. Not dead, just incomplete data.
- README claims **"18 venues"** but the app surfaces **19** (includes Peppermint Club conditionally). Inconsistency but not a bug. Will mention in RUNBOOK.

## 4. Dependencies

### Runtime
- **Google Fonts CSS** (`Orbitron` + `IBM+Plex+Mono`) via `fonts.googleapis.com`.
  - Not pinned. Risk: Google could change the served CSS. Low probability, low impact (fonts fall back to system sans-serif + monospace).
  - **Decision:** add `display=swap` already done. Add a local fallback stack — already present via CSS vars. **Leave upstream as-is; document fallback in runbook.**
- **No JS dependencies.** No CDN libraries.

### Build/deploy
- **None.** Push to `main` → GitHub Pages serves.

### Tooling for the digest script
- Python 3.11+ standard library only. No pip dependencies. Explicitly avoided to eliminate supply-chain risk.

## 5. Implicit assumptions that could silently break

| Assumption | Failure mode | Mitigation |
|---|---|---|
| `CONCERTS` array parseable by a regex/JS-JSON converter | Data refresh introduces trailing commas, unescaped quotes, comment-only lines | Write parser with clear errors; test runs as part of digest CI |
| `index.html` at repo root always contains a single `const CONCERTS = [...]` declaration | Refactor splits data into a separate file | Parser asserts single declaration; fail loud if not found |
| Gmail MCP `create_draft` succeeds in <60s | MCP hang (as happened 2026-04-19) | 60s timeout in prompt, no retries, exit |
| Scheduled task has network + MCP access | Creds rotate or MCP quota exhausts | Digest script exits non-zero, Claude reports failure; no partial draft |
| Local tz interpretation is America/Los_Angeles | Scheduled task infra tz changes | Script uses `ZoneInfo("America/Los_Angeles")` explicitly |
| `WISHLIST_ARTISTS` + `trackedArtists` define "what I care about" | `trackedArtists` is in browser localStorage only — not visible to scheduled task | Digest uses `WISHLIST_ARTISTS` (repo) only; documented in runbook |
| `onSaleDate` / `presaleDate` formatted `YYYY-MM-DDThh:mm` or `YYYY-MM-DD` | Refresh introduces new format | Parser accepts both, logs unparseable as warnings |

## 6. Summary

| Area | State |
|---|---|
| Static site | Already low-maintenance. Keep. |
| Weekly digest | Move ~95% of work off Claude into a script. |
| Dead code | None worth removing. |
| Dependencies | One external (Google Fonts). Document fallback, don't pin. |
| Tests | None today. Adding full unit + smoke coverage for the digest pipeline. |
| Claude tier | Opus/Sonnet → Haiku after migration. |
