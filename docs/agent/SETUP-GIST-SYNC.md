# Watchlist Sync Setup (GitHub Gist)

The site stores your starred shows + tracked artists in browser localStorage by default. That's fine for one device, but it's wiped when you clear browser data and doesn't follow you across devices. This doc walks you through wiring up GitHub Gist as a free, durable backend.

## One-time setup (~3 min)

### 1. Create a Personal Access Token
1. Open https://github.com/settings/tokens?type=beta (Fine-grained PATs)
2. Click **Generate new token**
3. Name: `LA Concert Tracker Sync`
4. Expiration: 1 year (set a calendar reminder to rotate)
5. Resource owner: your account
6. Repository access: **Public Repositories (read-only)** — gists don't require repo scope
7. Permissions → Account permissions → **Gists: Read and write**
8. Click **Generate token**, copy the `github_pat_...` string

> Classic tokens work too. If you go that route, only check the `gist` scope.

### 2. Open the site, click the gear in the header
- Top right of the header, you'll see `○ Local`
- Click it → modal opens

### 3. Paste the PAT, click "Create new gist"
- Paste your token in the PAT field
- Click **Create new gist** — the app creates a private gist on your account and auto-fills the Gist ID
- Click **Save** to lock it in

That's it. The dot turns green (`● Synced`) and every star/artist add now syncs to the gist within 1.5s.

## Using it on a second device
1. Open the site on the new device
2. Click the gear → paste the same PAT and the Gist ID (find it in the URL of your gist on github.com)
3. Click **Save** — the modal pulls the existing watchlist from the gist and merges it with whatever's local

## Sync model (how it actually works)
- **localStorage** is the working cache — instant, offline-friendly
- **Gist** is the durable mirror — synced on every change (debounced 1.5s)
- **On page load**, the app fetches the gist and unions remote + local. Local additions made offline survive the next sync.
- **Conflict policy:** union (set merge). Last-writer-wins doesn't apply because we never delete from the remote — only union additions. To remove an artist, untrack it on the device and the next push will overwrite the gist with the smaller list.

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `! Bad token` | PAT expired or wrong scope | Regenerate with `gist` scope, paste again |
| `! Gist not found` | Gist ID typo or gist deleted | Re-paste ID from gist URL, or click "Create new gist" |
| `! Push HTTP 403` | Rate limit (rare — limit is 5000/hr) | Wait an hour |
| `! Network` | Offline or DNS issue | Site keeps working in local mode; sync resumes when back online |
| Indicator stays `○ Local` after Save | Either field empty | Both PAT and Gist ID required |

## Manual controls (modal buttons)
- **Save** — commit the PAT/Gist ID and run an initial sync
- **Create new gist** — POST a new private gist with current state
- **Push now** — force-PATCH the gist with current local state (overwrites remote)
- **Pull now** — re-fetch the gist and merge into local
- **Disconnect** — clear PAT + Gist ID from this browser. Local data stays intact. Remote gist is not touched.

## Security notes
- The PAT lives in this browser's `localStorage` under key `la_gist_pat`. Anyone with access to your browser profile can read it. The site is unlisted and the token is scoped only to gists.
- The gist itself is private (default for `Create new gist`). Only requests bearing the PAT can read it.
- If your browser is compromised, revoke the PAT at https://github.com/settings/tokens.

## What about the weekly digest?
The Python digest script (`scripts/weekly_digest.py`) only reads the hardcoded `WISHLIST_ARTISTS` array in `index.html`. It does **not** currently read the gist. If you want UI-added artists to flow into the weekly digest, either:
- (Easy) Periodically copy your tracked artists from the UI back into `WISHLIST_ARTISTS` in `index.html` and commit
- (Future) Wire the digest script to fetch the gist on run — see `docs/agent/SESSION-STATE.md` "Next Session" for the deferred Chunk 3
