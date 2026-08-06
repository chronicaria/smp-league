"""Resolve the league export the site is actually built from.

Tests used to name the export file directly. That silently rots: when a new export
lands, the site rebuilds from it while every test goes on asserting against the old
one, still green. So this mirrors the rule the build workflow uses -- among the
current league's exports (league-data/*.json, never the archived subdirectories),
the one furthest along by (season, phase, games played) wins.
"""

import glob
import json
import os

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_HERE)
LEAGUE_DATA = os.path.join(_REPO, "league-data")


def current_export_path():
    """Path to the newest export, or None when league-data holds none."""
    best = None
    for path in sorted(glob.glob(os.path.join(LEAGUE_DATA, "*.json"))):
        try:
            with open(path, encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, ValueError):
            continue
        if not isinstance(data, dict):
            continue  # odds_history.json is a list, not an export
        attrs = data.get("gameAttributes", {})
        if isinstance(attrs, list):
            attrs = {a["key"]: a["value"] for a in attrs if isinstance(a, dict) and "key" in a}
        season = attrs.get("season")
        if not isinstance(season, int):
            continue
        phase = attrs.get("phase")
        key = (season, phase if isinstance(phase, int) else -1, len(data.get("games", [])), path)
        if best is None or key > best:
            best = key
    return best[3] if best else None


def load_current_export():
    """(path, parsed export). Raises if none is present — a missing export is a
    broken checkout, not a reason to quietly skip the tests that need one."""
    path = current_export_path()
    if path is None:
        raise AssertionError(f"no league export found in {LEAGUE_DATA}")
    with open(path, encoding="utf-8") as fh:
        return path, json.load(fh)
