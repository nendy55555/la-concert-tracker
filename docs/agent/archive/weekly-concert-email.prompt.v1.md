# Archived: weekly-concert-email prompt v1 (pre-hardening)

**Retired:** 2026-04-20
**Reason:** Replaced with deterministic Python script (`scripts/weekly_digest.py`) + thin Claude prompt for Gmail draft creation. See DECISIONS.md.

## Behavior (from SESSION-STATE and observed runs)

- Weekly on Sunday at 09:03 PT.
- WebSearch-only scan across all 18 LA venues (~25 searches), no Firecrawl.
- Matched WISHLIST_ARTISTS against search results via Claude reasoning.
- Composed HTML digest inline in the prompt.
- Saved a Gmail draft via `create_draft` with a 60s hang guard.
- No Chrome auto-send.
- Fallback recovery: manual digest on 2026-04-20 after 4-19 hang.

## Known failure modes

- 2026-04-19: Firecrawl credit exhaustion cascaded to WebSearch fallback loop; `create_draft` then hung for 27h. Root cause: missing timeout + unbounded search retries.
- Pre-fix prompt was phrased "new watchlist matches since last week" — delta framing caused empty-section emails when no new shows were added. Rebuilt to list all matching artists.

## How to restore if the hardened version fails

1. Run `scripts/weekly_digest.py --horizon-days 300 --text` locally to confirm data still parses.
2. If the Haiku-tier scheduled task fails to call `create_draft`, swap the task back to Sonnet in the scheduled tasks UI.
3. If the script itself fails (CONCERTS parse error after a data refresh), fix the data first — don't swap back to WebSearch, because the authoritative data lives in the repo.
