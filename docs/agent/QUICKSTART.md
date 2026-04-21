# LA Concert Tracker — Quickstart

## What Is This
Single-file HTML concert tracker for Los Angeles. 428 concerts across 18 venues, April–November 2026. Cyberpunk neon design (Orbitron + IBM Plex Mono).

## Architecture
Everything lives in `index.html`. No build system. CSS + JS inline. Data is a `CONCERTS` array of objects at the top of the `<script>` block (~line 1195).

## Key Data Fields
```
{ date, name, venue, genre, support, spotifyMonthlyListeners, ticketUrl, ticketVendor, onSaleDate, presaleDate }
```
- `ticketVendor`: Auto-detected from URL domain. Ticketmaster: 116, Hollywood Bowl: 88, others smaller, 190 unknown.
- `onSaleDate` / `presaleDate`: Format `YYYY-MM-DDThh:mm` or `YYYY-MM-DD`. Currently populated for 5 events.

## Features
- Calendar / List / My Artists views
- Watchlist (localStorage) with star toggle
- Artist tracking (WISHLIST_ARTISTS + manual add) with fuzzy match
- Venue + genre filters
- Google Calendar export per show
- Vendor badges (color-coded by vendor)
- On-sale date badges with countdown + time display
- **Upcoming Ticket Drops** banner (auto-shows events with future on-sale dates)
- Search by artist name

## Current State
- Last updated: April 20, 2026
- Last data refresh: March 31, 2026
- 428 concerts, 18 venues
- **Deployed to GitHub Pages:** https://nendy55555.github.io/la-concert-tracker/ (unlisted — `noindex` meta + robots.txt)
- In-flight: nothing (clean state)
- Known gaps: most on-sale dates still empty, Fonda/Troubadour thin, Spotify counts default 0 for scraped entries

## Deploy
- Repo: github.com/nendy55555/la-concert-tracker (public, but site is no-indexed)
- Push to `main` → GitHub Pages auto-publishes within ~1 min
- To update: edit `index.html`, `git add -A && git commit -m "msg" && git push`

## Data Refresh
Firecrawl scrape venue pages → venue-specific parsers → merge with existing data. See conversation history for parser details.

## File Routing
- Styles: lines 10–1092
- HTML structure: lines 1093–1195
- Concert data: lines ~1195–1623
- JS logic: lines ~1623–1998
