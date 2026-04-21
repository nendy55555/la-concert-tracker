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
echo "All tests passed."
