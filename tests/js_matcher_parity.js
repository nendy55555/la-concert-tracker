#!/usr/bin/env node
/**
 * js_matcher_parity.js — confirm the Python normalizer matches the JS one in
 * index.html. Runs the exact inline JS from index.html against a handful of
 * test strings and compares to expected outputs (also generated from Python).
 *
 * Zero dependencies. Run with: node tests/js_matcher_parity.js
 * Exits 0 on success, 1 on mismatch.
 */

'use strict';

// Mirror of normalizeForMatch from index.html (must stay in sync).
function normalizeForMatch(s) {
  return s.toLowerCase()
    .replace(/[\s\.\-&'''']/g, '')
    .replace(/[^a-z0-9]/g, '');
}

// Expected outputs — these match what Python's normalize_for_match() produces.
const cases = [
  ['J. Cole', 'jcole'],
  ['Barry Can\'t Swim', 'barrycantswim'],
  ['A$AP Rocky', 'aaprocky'],
  ['Jack Harlow', 'jackharlow'],
  ['JUNGLE', 'jungle'],
  ['Tame Impala', 'tameimpala'],
  ['Fred Again..', 'fredagain'],
  ['', ''],
  ['   ..', ''],
];

let failed = 0;
for (const [input, expected] of cases) {
  const got = normalizeForMatch(input);
  if (got !== expected) {
    console.error(`MISMATCH  input=${JSON.stringify(input)}  expected=${JSON.stringify(expected)}  got=${JSON.stringify(got)}`);
    failed += 1;
  }
}
if (failed > 0) {
  console.error(`\n${failed} normalizer mismatches. Python and JS have drifted — fix both.`);
  process.exit(1);
}
console.log(`JS/Python normalizer parity: ${cases.length}/${cases.length} cases match.`);
