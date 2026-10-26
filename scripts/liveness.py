"""liveness: post-run assertions for scheduled pipelines.

Prove a successful-looking run actually did its job: data is fresh, counts
grew, the current period is present, repeated empty results escalate.
Exit-code contract: 0 all pass / 1 assertion failed / 2 a check itself broke.

Source: Documents/Claude/Accelerators/packages/liveness (copy this file into
the adopting project and keep this header). Python 3.9+, stdlib only.
Spec: Accelerators/docs/agent/specs/liveness/SPEC.md
"""
import json
import os
from collections import namedtuple
from datetime import date, datetime

VERSION = "2026-09-03"

Result = namedtuple("Result", ["ok", "name", "reason"])


class StateError(Exception):
    """The state file exists but cannot be read. Fails loud (exit 2)."""


class State(object):
    """Checkpoint and quiet-run counters, staged in memory.

    run_checks() commits only when the overall verdict is 0, so a rerun after
    an unrelated failure sees the same checkpoints as the failed run.
    A missing file is a first run; an unparseable one raises StateError.
    Plain overwrite on commit: single-writer scheduled tasks only.
    """

    def __init__(self, path):
        self.path = str(path)
        self._data = None

    def _load(self):
        if self._data is not None:
            return
        if os.path.exists(self.path):
            try:
                with open(self.path) as f:
                    raw = f.read()
                data = json.loads(raw) if raw.strip() else {}
                if not isinstance(data, dict):
                    raise ValueError("state root is not an object")
            except (ValueError, OSError) as e:
                raise StateError("state file unreadable: %s (%s)" % (self.path, e))
        else:
            data = {}
        data.setdefault("counts", {})
        data.setdefault("silent", {})
        self._data = data

    def get_count(self, name):
        self._load()
        return self._data["counts"].get(name)

    def set_count(self, name, value):
        self._load()
        self._data["counts"][name] = value

    def get_silent(self, name):
        self._load()
        return self._data["silent"].get(name, 0)

    def set_silent(self, name, value):
        self._load()
        self._data["silent"][name] = value

    def commit(self):
        if self._data is None:
            return
        with open(self.path, "w") as f:
            json.dump(self._data, f, indent=2)
            f.write("\n")


def _now(today):
    return today if today is not None else datetime.now()


def _as_date(today):
    t = _now(today)
    return t.date() if isinstance(t, datetime) else t


def check_fresh(path, max_age_days, today=None):
    """File mtime recency. Missing file is a FAIL, not an exception.
    Age exactly max_age_days passes; over fails."""
    name = "fresh:%s" % os.path.basename(str(path))
    if not os.path.exists(str(path)):
        return Result(False, name, "%s does not exist" % path)
    age_days = (_now(today).timestamp() - os.path.getmtime(str(path))) / 86400.0
    if age_days <= max_age_days:
        return Result(True, name, "age %.1fd within %sd" % (age_days, max_age_days))
    return Result(False, name, "age %.1fd exceeds max %sd" % (age_days, max_age_days))


def check_max_date(dates, max_age_days, today=None):
    """Recency of the newest ISO date string. Empty input is a FAIL."""
    name = "max_date"
    items = list(dates)
    if not items:
        return Result(False, name, "no dates supplied")
    newest = max(date.fromisoformat(str(d)[:10]) for d in items)
    age = (_as_date(today) - newest).days
    if age <= max_age_days:
        return Result(True, name, "newest %s, %sd old" % (newest, age))
    return Result(False, name, "newest %s is %sd old, max %sd" % (newest, age, max_age_days))


def check_grew(name, current, state, allow_equal=False):
    """Compare against the recorded checkpoint; first run records a baseline."""
    label = "grew:%s" % name
    prev = state.get_count(name)
    if prev is None:
        state.set_count(name, current)
        return Result(True, label, "baseline recorded at %s" % current)
    if current > prev:
        state.set_count(name, current)
        return Result(True, label, "%s -> %s" % (prev, current))
    if current == prev:
        if allow_equal:
            return Result(True, label, "unchanged at %s (allowed)" % current)
        return Result(False, label, "did not grow: still %s" % current)
    return Result(False, label, "shrank: %s -> %s" % (prev, current))


def check_contains(values, needle):
    """Membership, e.g. the current season present in an artifact's seasons."""
    items = list(values)
    name = "contains:%s" % needle
    if needle in items:
        return Result(True, name, "%s present" % needle)
    return Result(False, name, "expected %s, found %s" % (needle, items))


def silent_runs(name, found_count, state, escalate_after=2):
    """Zero results increments the quiet counter; any result resets it.
    FAIL at the threshold: N quiet runs means the pipe is likely broken."""
    label = "silent:%s" % name
    if found_count > 0:
        state.set_silent(name, 0)
        return Result(True, label, "%s found, counter reset" % found_count)
    k = state.get_silent(name) + 1
    state.set_silent(name, k)
    if k >= escalate_after:
        return Result(False, label, "no results %s runs running: pipeline likely broken" % k)
    return Result(True, label, "quiet %s/%s" % (k, escalate_after))


def current_year(today=None):
    return _as_date(today).year


def nfl_season(today=None):
    """NFL season label: the year the season starts. Jan/Feb belong to the
    prior season. Matches Betting Model scripts/19_pull_deep_history.py:330."""
    t = _as_date(today)
    return t.year if t.month >= 3 else t.year - 1


def run_checks(checks, state=None):
    """Run each zero-arg callable (or ready Result), print one line per check,
    return 0/1/2. 2 (a broken check) wins over 1. State commits only on 0."""
    any_fail = False
    any_broken = False
    for c in checks:
        try:
            r = c() if callable(c) else c
            print("%s %s: %s" % ("PASS" if r.ok else "FAIL", r.name, r.reason))
            if not r.ok:
                any_fail = True
        except Exception as e:
            print("BROKEN %s: %s" % (getattr(c, "__name__", "check"), e))
            any_broken = True
    if any_broken:
        return 2
    if any_fail:
        return 1
    if state is not None:
        try:
            state.commit()
        except Exception as e:
            print("BROKEN state-commit: %s" % e)
            return 2
    return 0
