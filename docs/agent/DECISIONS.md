# Decisions Log

Append-only. Each entry: date, decision, reasoning, reversibility notes.

---

## 2026-04-20 — Hardening pass: move weekly digest off Claude

**Decision:** Replace the WebSearch+reasoning workflow in `weekly-concert-email` with a pure Python script that reads `CONCERTS` from `index.html` and produces an HTML digest. Claude's only remaining job is calling the Gmail `create_draft` MCP tool.

**Why:**
- The authoritative data is already in the repo. Searching the web for it was redundant.
- The 2026-04-19 hang (27 hours, Firecrawl out of credits, WebSearch fallback loop, then `create_draft` hang) proved the live-data path is fragile.
- Post-Max, WebSearch + Opus/Sonnet reasoning is the biggest recurring cost in this workspace.

**Tradeoffs:**
- Digest freshness is bounded by how often Thomas refreshes the CONCERTS array (every few months). Acceptable — the weekly email is a reminder, not a discovery tool.
- When Thomas does refresh CONCERTS, the very next digest will reflect all new shows.

**Reversibility:** Fully reversible. The old WebSearch prompt is preserved in `docs/agent/archive/weekly-concert-email.prompt.v1.md`. The scheduled task prompt can be swapped back in ~60s.

---

## 2026-04-20 — Downgrade scheduled task from Sonnet to Haiku

**Decision:** After script replacement, switch the scheduled-task model tier to Haiku (`claude-haiku-4-5-20251001`).

**Why:** The remaining work is running a script and calling one MCP tool. No reasoning, no reading long docs, no composition.

**Eval plan:** Before flipping the default, run the new prompt 3× on Haiku and 1× on Sonnet, compare output. Recorded in `tests/model_eval.md`.

**Reversibility:** Add a one-line swap note in RUNBOOK.md for escalating back to Sonnet if Haiku regresses.

---

## 2026-04-20 — Delete stale scheduled tasks

**Decision:** Delete `concert-watchlist-alert` and `la-concert-watchlist-alert`. Both are tagged `[DELETE ME]` and superseded by `weekly-concert-email`.

**Why:** Dead tasks clutter the scheduler UI, and if they were ever accidentally re-enabled they'd send broken emails.

**Reversibility:** Both are already paused (`enabled: false`). Deletion is irreversible, but the replacement task (`weekly-concert-email`) does the same job.

---

## 2026-04-20 — Do NOT pin Google Fonts

**Decision:** Keep `https://fonts.googleapis.com/css2?family=Orbitron:...&display=swap` as-is. Do not self-host.

**Why:**
- Pinning requires either a git-committed CSS snapshot (drift risk, font files > 100KB each) or self-hosting fonts via @font-face (adds binary files to repo + build complexity).
- Failure mode is cosmetic only — site falls back to system sans + monospace which is legible.
- The fallback stack is already defined in CSS vars.

**Reversibility:** Trivial — re-enable this decision by downloading font files and adding @font-face.

---

## 2026-04-20 — Python stdlib only for digest script

**Decision:** `scripts/weekly_digest.py` uses only Python 3.11+ stdlib. No `pip install`.

**Why:** Eliminates supply-chain risk, eliminates "pip install failed" as a runtime failure mode, works on any Mac/Linux with Python 3.11.

**Tradeoffs:** Hand-rolling the HTML template and JS-to-JSON parser rather than using `jinja2` / `pyjsparser`. Both are ~40 lines of simple code.

---

## 2026-04-20 — No separate data file

**Decision:** Keep `CONCERTS` embedded in `index.html`. Do not split into `concerts.json`.

**Why:**
- Single-file app is a feature — deploys with one `git push`.
- Splitting would add a build step or a fetch+error path for users on slow connections.
- The digest script parses the array out of the HTML reliably; the regex is simple and tested.

**Reversibility:** Moderate. Would require the parser + the app's inline script to load from JSON, plus a GitHub Pages path.
