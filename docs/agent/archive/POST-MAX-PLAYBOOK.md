# Post-Max Playbook

**Audience:** You, ~10 days from now, on a non-Max plan with minimal Claude budget.
**Scope:** This document is workspace-level advice. It covers LA Concert Tracker explicitly; the patterns apply to the other projects still to be hardened.

## 0. Core principle

The cheapest Claude call is the one that never runs. The second cheapest is a Haiku call that reads a pre-generated file and does exactly one MCP tool call. Everything else is expensive.

When you feel the urge to write "search the web and figure out…", stop. Write a script that reads already-known data and rewrites the prompt to invoke the script.

## 1. How to use Claude on a minimal plan

### Rule of thumb — tier selection

| Task shape | Default tier |
|---|---|
| "Run this script, call one MCP tool, exit" | Haiku |
| "Read a file, make a small edit based on clear spec" | Haiku |
| "Debug an error I'm stuck on" | Sonnet |
| "Design a feature / architecture / tests from scratch" | Sonnet |
| "Understand an unfamiliar codebase deeply" | Sonnet or Opus (one-off) |

Do not default to Opus. Use Opus only when Sonnet has already tried and failed on the same problem.

### Rule of thumb — when NOT to call Claude

- You already know the answer and just don't want to type it → type it.
- The task is deterministic (sort, transform, render) → write a script (or reuse one of ours).
- The task is "remind me to…" → scheduled task with a no-op prompt + notification.
- The task is "did X change?" → `git log -p -- path/to/X`.
- The task is "what does this do?" → read the file. Faster than a round-trip.

## 2. Diagnosing issues without Claude

Rough order of operations when something breaks:

1. **Read the error.** Verbatim. Copy-paste if needed.
2. **Does it reproduce?** If yes, localize it (`grep`, `git log`, `git bisect`).
3. **Is a test failing?** Read the test source, read the failing assertion, read the code under test. That's usually enough.
4. **Is an MCP tool failing?** Check Settings → Connectors → is it green? If red, Reconnect. If auth, re-grant scopes.
5. **Is a scheduled task hanging?** Cancel the run, disable the task, investigate tomorrow. Do NOT let a hung task eat a full day (see 2026-04-19 incident).
6. **Is the network involved?** Try `curl -sS -o /dev/null -w "%{http_code}\n" <url>` before assuming Claude can help.
7. **Still stuck after 15 minutes?** One targeted Sonnet call with full error text + relevant file contents + "what would you check first?" — you want the checklist, not the fix.

## 3. Rotating API keys / credentials

### Gmail MCP token
Settings → Connectors → Gmail → Reconnect. Grant the same scopes.

### GitHub (for `git push`)
`gh auth login` (GitHub CLI) or regenerate a personal access token at https://github.com/settings/tokens and `git config --global credential.helper osxkeychain`.

### Firecrawl (only needed if you run the old-style scrape manually)
https://firecrawl.dev dashboard → rotate API key → update local `.env` if you have one. The hardened weekly digest does NOT use Firecrawl.

### Anthropic API (if you use the API directly from scripts)
https://console.anthropic.com → API keys. Never commit keys — use `~/.config/anthropic/credentials` or env var `ANTHROPIC_API_KEY`.

## 4. Updating dependencies without Claude

For LA Concert Tracker: no dependencies to update — vanilla JS + Python stdlib. The only upstream moving target is Google Fonts, which is non-blocking.

For other projects:
- `npm outdated` / `pip list --outdated` shows what's stale.
- Bump minor versions aggressively, major versions reluctantly.
- After any bump, run the project's test suite. If none exists, the project isn't hardened — see §6.

## 5. Model tier swaps

Every scheduled task has a tier. To swap:

1. Claude desktop → Scheduled Tasks sidebar.
2. Click the task.
3. Model dropdown → pick tier.
4. "Run now" to verify.

The prompts in this workspace are deliberately tier-agnostic. You should almost never need to rewrite a prompt to move between Haiku and Sonnet.

## 6. Hardening the remaining projects

The LA Concert Tracker has been fully hardened in this session. These are still unhardened (or unknown-state):

- `honeymoon-deal-scanner` / `honeymoon-deal-alert` — PAUSED.
- `fetch-upcoming-games` — DISABLED.
- `weekly-housing-digest` — DISABLED.
- `futures-odds-daily-refresh` — PAUSED.
- `review-recipe-import-rules` — ENABLED (Mon 9am weekly).
- `morning-warmup` — ENABLED (hourly keepalive 6am–8pm).
- `nfl-weekly-picks` — DISABLED (offseason).
- `nfl-post-game-score` — PAUSED until Sep 2026.
- `monthly-spending-email` — manual only.

### Per-project hardening loop (reusable)

1. **Open the project folder in Cowork.** Do not try to harden from this workspace — you need the files.
2. **Generate an AUDIT.md.** Focus on Claude call sites. Classify each as: Replaceable / Downgradeable / Cacheable / Genuinely-needs-Claude.
3. **Replace what you can.** For deterministic work, a Python stdlib script is usually enough. For search-heavy work, check if the data is actually already local (it often is).
4. **Downgrade what remains.** Target Haiku unless an eval proves otherwise.
5. **Add tests.** One per Claude-replacement, one per top-level behavior, one smoke test.
6. **Write a RUNBOOK.** Think "me in six months with no Claude."
7. **Update SESSION-STATE.md** so the next session starts oriented.

Budget: 1 project / 1 Cowork session should be enough. Each saves you 80–95% of that project's Claude cost.

### Which project to harden next

Priority heuristic: `use_frequency × current_cost × silent_break_risk`. Rough ranking:

| Project | Frequency | Cost now | Risk | Priority |
|---|---|---|---|---|
| `review-recipe-import-rules` | weekly | low (one skill read) | low | 2 |
| `morning-warmup` | hourly | trivial | trivial | 1 (leave alone) |
| `weekly-housing-digest` | weekly (disabled) | high (5 sites + scoring + email) | medium | 4 |
| `monthly-spending-email` | monthly | medium (HTML compose) | low | 3 |
| `nfl-weekly-picks` | weekly (Sep–Feb) | high (model pipeline) | medium | 4 (pre-season) |

Start with `weekly-housing-digest` when you re-enable it — same pattern as the concert digest (scrape less, read more).

## 7. Emergency recovery

### Scheduled task hung overnight
1. Sidebar → task → Cancel run.
2. Sidebar → task → toggle Enabled off.
3. Check Gmail for partial drafts (sometimes the draft exists even if the task "hung").
4. Investigate in a normal session. Do not "Run now" until you've read the logs.

### Site is broken after a push
1. `git revert HEAD && git push` — you're back to the last working state in <60s.
2. Then investigate on a branch.

### Tests fail after a data edit
The test output tells you exactly which row is wrong. Open `index.html`, find the row, fix it, re-run tests.

### Claude account suspended / API key revoked
- Scheduled tasks will fail silently or with auth errors. Disable them.
- LA Concert Tracker keeps working — the site runs without Claude.
- Weekly digest: run `python3 scripts/weekly_digest.py --horizon-days 180` locally and email yourself manually from the `dist/weekly_digest.html` output.

## 8. Things to NEVER do on a minimal plan

- **Let a task run unattended on Opus.** One debugging session with Opus can burn a day of budget.
- **Re-scrape data you already have.** If it's in the repo, read the repo.
- **Retry Claude calls on timeout.** Abort, investigate, fix root cause.
- **Use Claude to read files Claude wrote 10 minutes ago.** Re-read is free for you (just open the file), expensive via API.
- **Debug prompts inside the scheduled task.** Dev-loop locally first, paste the working prompt into the task.

## 9. Kill list — disable if budget is very tight

If you hit a hard wall, disable these first:

1. `morning-warmup` — it's a keepalive. You don't need it on a minimal plan. Saves ~15 hourly sessions/day.
2. `review-recipe-import-rules` — weekly rule-drift check. Can run monthly instead, or delete until you're actively editing the recipe project.

Keep:
- `weekly-concert-email` — it's now cheap (one Haiku call + one MCP call).

## 10. Quick reference — this workspace

| Thing | Where |
|---|---|
| Project root | `~/Documents/Claude/Projects/LA Concert Tracker` |
| Run tests | `bash tests/run_all.sh` |
| Generate digest | `python3 scripts/weekly_digest.py --text` |
| Edit scheduled task | Claude desktop sidebar → Scheduled Tasks |
| Live site | https://nendy55555.github.io/la-concert-tracker/ |
| Repo | github.com/nendy55555/la-concert-tracker |
| Agent docs | `docs/agent/` |
