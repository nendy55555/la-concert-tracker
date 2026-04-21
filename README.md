# LA Concert Tracker

Single-file web app that tracks concerts across 18 Los Angeles venues, flags shows matching a personal watchlist, and tracks on-sale dates.

Live site: https://nendy55555.github.io/la-concert-tracker/ (unlisted — not indexed)

## What it does

- Shows 400+ concerts across 18 LA venues, April–November 2026
- Three views: calendar, list, and "My Artists"
- Watchlist via star toggle (localStorage)
- Auto-match against a WISHLIST_ARTISTS list using fuzzy matching
- Filters by venue and genre
- On-sale date countdowns with vendor badges (Ticketmaster / AXS / Bowl)
- Google Calendar export per show
- "Hide past" toggle (default on)

## Venues tracked

Hollywood Bowl, Greek Theatre, Kia Forum, Crypto.com Arena, SoFi Stadium, The Wiltern, The Fonda Theatre, Troubadour, YouTube Theater, The Regent Theater, Rose Bowl, Hollywood Palladium, Academy LA, El Rey Theatre, Intuit Dome, Shrine Auditorium, The Novo, The Roxy Theatre.

## Stack

Single `index.html` file. No build step. Inline CSS + JS. Concert data lives as a `CONCERTS` array at the top of the `<script>` block.

## Updating data

Run the data refresh workflow (Firecrawl scrape → venue parsers → merge). A scheduled task `la-concert-watchlist-alert` runs daily at 9am and emails watchlist matches.

## Deploy

Pushed to `main` → GitHub Pages auto-publishes. No CI needed.

## Project docs

Agent docs in `docs/agent/` — `QUICKSTART.md` and `SESSION-STATE.md` carry context across sessions.
