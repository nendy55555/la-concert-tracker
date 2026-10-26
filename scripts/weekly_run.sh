#!/usr/bin/env bash
# Weekly LA Concert run: refresh data from Ticketmaster, test, commit+push, send the digest.
# The digest ALWAYS runs. A refresh, test or push failure is recorded in data/refresh_state.json
# so the email names it; none of them is fatal.
# Env overrides (tests only): REFRESH_CMD, TESTS_CMD, DIGEST_CMD, DIGEST_ARGS, SKIP_GIT=1
set -u
cd "$(dirname "$0")/.."
mkdir -p logs
LOG="logs/weekly_run.log"
STATE="data/refresh_state.json"
log() { echo "$(date '+%Y-%m-%d %H:%M:%S') $*" | tee -a "$LOG"; }

# set_state KEY VALUE: merge one string key into the state file (creates it if missing).
set_state() {
  python3 - "$STATE" "$1" "$2" <<'PY'
import json, sys, pathlib
p = pathlib.Path(sys.argv[1]); st = json.loads(p.read_text() or "{}") if p.exists() else {}
st[sys.argv[2]] = sys.argv[3]
p.parent.mkdir(parents=True, exist_ok=True); p.write_text(json.dumps(st, indent=2, sort_keys=True) + "\n")
PY
}

log "run start · $(python3 --version 2>&1) · node $(node --version 2>&1 || echo missing) · $(git remote get-url origin 2>/dev/null || echo 'no remote')"

if [ "${SKIP_GIT:-0}" != "1" ]; then
  git pull --ff-only >>"$LOG" 2>&1 || log "git: pull failed (continuing on local data)"
fi

refresh_status="ok"
if ( eval "${REFRESH_CMD:-python3 scripts/refresh_concerts.py}" ) >>"$LOG" 2>&1; then
  log "refresh: ok"; set_state last_refresh_rc 0
else
  rc=$?; refresh_status="failed"; log "refresh: failed($rc)"; set_state last_refresh_rc "$rc"
fi

if [ "$refresh_status" = "ok" ]; then
  if ( eval "${TESTS_CMD:-bash tests/run_all.sh}" ) >>"$LOG" 2>&1; then
    log "tests: ok"; set_state last_tests_status ok
    if [ "${SKIP_GIT:-0}" != "1" ]; then
      git add index.html "$STATE" >>"$LOG" 2>&1
      if git diff --cached --quiet; then
        log "git: nothing to commit"; set_state last_push_status ok
      elif git commit -q -m "data: weekly refresh $(date '+%Y-%m-%d')" >>"$LOG" 2>&1 && git push -q >>"$LOG" 2>&1; then
        log "git: pushed"; set_state last_push_status ok
      else
        log "git: failed (site not updated; digest still sends)"; set_state last_push_status failed
      fi
    else
      set_state last_push_status skipped
    fi
  else
    log "tests: failed · restoring index.html from HEAD, keeping evidence in state"
    git checkout -- index.html 2>>"$LOG" || log "git: restore failed"
    # Rebuild state: HEAD's success fields + the working tree's digest keys and refresh rc + the failure flag.
    python3 - "$STATE" <<'PY' >>"$LOG" 2>&1 || log "state: rebuild failed"
import json, subprocess, sys, pathlib
p = pathlib.Path(sys.argv[1])
cur = json.loads(p.read_text() or "{}") if p.exists() else {}
try:
    head = json.loads(subprocess.check_output(["git", "show", f"HEAD:{p.as_posix()}"], text=True) or "{}")
except subprocess.CalledProcessError:
    head = {}
for k in ("last_digest_at", "last_digest_covered_through", "last_refresh_rc"):
    if cur.get(k):
        head[k] = cur[k]
head["last_tests_status"] = "tests_failed"
p.write_text(json.dumps(head, indent=2, sort_keys=True) + "\n")
PY
  fi
fi

# Subshell: an `exit N` override (E26) must end the digest step, never the wrapper.
( eval "${DIGEST_CMD:-python3 scripts/weekly_digest.py --horizon-days 180 --onsale-days 14 --email ${DIGEST_ARGS:-}}" ) >>"$LOG" 2>&1
drc=$?
log "digest: exit $drc"
exit $drc
