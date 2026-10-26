#!/usr/bin/env bash
# Run the full test suite. Zero Claude API calls, zero network.
# Usage: bash tests/run_all.sh
set -euo pipefail

cd "$(dirname "$0")/.."
echo "== Python unit + integration tests =="
python3 -m unittest discover -s tests -p 'test_*.py' --buffer -v

echo ""
echo "== Smoke: generate digest against real index.html =="
python3 scripts/weekly_digest.py --as-of 2026-04-20 --horizon-days 300 > /tmp/digest.json
python3 -c "import json,sys;d=json.load(open('/tmp/digest.json'));assert d['totals']['concerts']>300,d;print('smoke ok:',d['totals'])"

echo ""
echo "== JS sanity: fuzzy matcher parity =="
node tests/js_matcher_parity.js


echo ""
echo "== Wrapper: refresh failure never blocks the digest (E26) =="
scratch=$(mktemp -d); git clone -q . "$scratch/clone"; cp scripts/weekly_run.sh "$scratch/clone/scripts/weekly_run.sh"; mkdir -p "$scratch/clone/data"
out=$(cd "$scratch/clone" && REFRESH_CMD=false TESTS_CMD=true DIGEST_CMD="exit 7" SKIP_GIT=1 bash scripts/weekly_run.sh; echo "rc=$?")
echo "$out" | grep -q "refresh: failed" && echo "$out" | grep -q "rc=7" \
  && python3 -c "import json; s=json.load(open('$scratch/clone/data/refresh_state.json')); assert s['last_refresh_rc']=='1', s" \
  && echo "E26 ok" || { echo "E26 FAIL: $out"; exit 1; }

echo "== Wrapper: failed tests restore index.html and record the failure (E27) =="
( cd "$scratch/clone" \
  && printf '{"last_success_at":"2026-01-01T00:00:00-08:00","last_digest_covered_through":"2025-12-25T00:00:00-08:00"}\n' > data/refresh_state.json \
  && git -c user.email=t@t -c user.name=t commit -q -am "seed state" \
  && printf '{"last_success_at":"2026-01-01T00:00:00-08:00","last_digest_covered_through":"2026-01-01T00:00:00-08:00"}\n' > data/refresh_state.json \
  && REFRESH_CMD="echo x >> index.html" TESTS_CMD=false DIGEST_CMD=true SKIP_GIT=1 bash scripts/weekly_run.sh >/dev/null; rc=$? \
  && [ "$rc" = "0" ] && git diff --quiet index.html \
  && python3 -c "import json; s=json.load(open('data/refresh_state.json')); assert s['last_tests_status']=='tests_failed', s; assert s['last_digest_covered_through']=='2026-01-01T00:00:00-08:00', s; assert s['last_refresh_rc']=='0', s" ) \
  && echo "E27 ok" || { echo "E27 FAIL"; exit 1; }
rm -rf "$scratch"
echo ""
echo "All tests passed."
