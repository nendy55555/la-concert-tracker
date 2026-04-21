# Hardening Inventory

**Session:** Pre-Max-downgrade hardening pass
**Date:** 2026-04-20
**Workspace scope:** Only `LA Concert Tracker` is mounted in this Cowork session. Other scheduled tasks exist for other projects (housing, NFL, honeymoon, recipes, sports, spending) but their repos are not accessible. They are listed at the bottom as "Out of scope (not mounted)" for future passes.

## Work queue (priority order)

| Rank | Project | Path | Priority |
|------|---------|------|----------|
| 1 | LA Concert Tracker | `/LA Concert Tracker` | 5 |

## Projects

### 1. LA Concert Tracker — priority 5

**What it does:** Single-file HTML web app that tracks 428 concerts across 18 LA venues (Apr–Nov 2026), flags shows against a watchlist, and emails Thomas a weekly digest of upcoming watchlist shows.

**Runtime Claude dependency:**
- **Static site (`index.html`):** None. Pure inline JS, zero API calls.
- **Weekly digest (`weekly-concert-email` scheduled task):** Required — currently Opus/Sonnet-tier because the task does WebSearch (~25 calls), reasoning over results, HTML composition, then `create_draft`. After hardening: downgradeable to Haiku, and most work moves off Claude entirely (pure script reads the CONCERTS array already in the repo).
- **Dead tasks (`concert-watchlist-alert`, `la-concert-watchlist-alert`):** Tagged `[DELETE ME]`. Must be deleted.

**Current test coverage:** None.

**Dependencies pinned:**
- N: Google Fonts loaded from `fonts.googleapis.com` at latest — not pinned. Low risk but listed.
- N: No package.json, no lockfile. All code is vanilla JS, so there's nothing to lock.

**Last meaningful change:** 2026-04-20 (initial commit — single commit repo).

**Priority score: 5 / 5**
- Use frequency: weekly digest + daily viewing = high
- Current Claude cost: ~25 WebSearches + reasoning + HTML composition per run = the single most expensive recurring item across the workspace
- Silent-break risk: high — past incident 2026-04-19 where Firecrawl ran out of credits and the task hung for 27 hours before manual recovery

**Planned hardening:**
- Convert weekly digest from WebSearch+reasoning → pure script that reads `index.html` and creates a Gmail draft. Claude's only remaining job is "run script, send draft."
- Delete the two `[DELETE ME]` tasks.
- Pin Google Fonts URL to a specific CSS2 snapshot or inline the @font-face.
- Add JS unit tests (run on Node, no browser) for: concert sort, fuzzy matcher, date parser, vendor/price badges, digest renderer.
- Add a pipeline smoke test that generates the digest end-to-end and asserts the HTML contains expected sections.
- RUNBOOK covering: manual digest run, Gmail auth rotation, swapping Claude tiers back up, data refresh steps, GitHub Pages deploy.

---

## Out of scope (not mounted in this session)

These scheduled tasks exist for other projects not mounted here. Documenting them so Thomas knows what's still unhardened:

- `honeymoon-deal-scanner` [PAUSED]
- `honeymoon-deal-alert` [PAUSED]
- `fetch-upcoming-games` [DISABLED]
- `weekly-housing-digest` [DISABLED]
- `futures-odds-daily-refresh` [PAUSED]
- `review-recipe-import-rules` [ENABLED — weekly Mon 9am]
- `morning-warmup` [ENABLED — hourly keepalive]
- `nfl-weekly-picks` [DISABLED — offseason]
- `nfl-post-game-score` [PAUSED — until Sep 2026]
- `monthly-spending-email` [ENABLED — manual only]

**Recommendation:** open those project folders in separate Cowork sessions and run the same hardening loop. The POST-MAX-PLAYBOOK.md written in Phase 3 documents how to do this without burning a full Max subscription.
