#!/usr/bin/env node
// Parity: the matcher in index.html must agree with Python on tests/fixtures/matcher_cases.json.
// Also keeps the original normalizer parity cases. Functions are extracted from index.html itself.
'use strict';
const fs = require('fs');
const path = require('path');
const ROOT = path.resolve(__dirname, '..');
const html = fs.readFileSync(path.join(ROOT, 'index.html'), 'utf8');

function extract(fnName) {
  const start = html.indexOf('function ' + fnName + '(');
  if (start === -1) { console.error('could not find ' + fnName); process.exit(1); }
  let depth = 0, i = html.indexOf('{', start);
  for (; i < html.length; i++) {
    if (html[i] === '{') depth++;
    else if (html[i] === '}') { depth--; if (depth === 0) break; }
  }
  return html.slice(start, i + 1);
}
const lib = new Function(extract('normalizeForMatch') + '\nvar MIN_LEGACY_TERM = 5;\n' + extract('artistMatches') +
  '\nreturn {normalizeForMatch: normalizeForMatch, artistMatches: artistMatches};')();

const normCases = [
  ['J. Cole', 'jcole'], ["Barry Can't Swim", 'barrycantswim'], ['A$AP Rocky', 'aaprocky'],
  ['Jack Harlow', 'jackharlow'], ['JUNGLE', 'jungle'], ['Tame Impala', 'tameimpala'],
  ['Fred Again..', 'fredagain'], ['', ''], ['   ..', ''],
];
let ok = 0, total = 0;
for (const [input, want] of normCases) {
  total++; const got = lib.normalizeForMatch(input);
  if (got === want) ok++; else console.error('normalizer mismatch', JSON.stringify(input), got, want);
}
const cases = JSON.parse(fs.readFileSync(path.join(__dirname, 'fixtures', 'matcher_cases.json'), 'utf8'));
for (const c of cases) {
  total++; const got = lib.artistMatches(c.name, c.artists, [c.watch]);
  if (got === c.expect) ok++; else console.error('matcher mismatch', JSON.stringify(c), 'got', got);
}
console.log(`JS/Python matcher parity: ${ok}/${total} cases match.`);
process.exit(ok === total ? 0 : 1);
