"""Tests for the client-side tools pages (W9): Lineup Lab + Win-Out Machine.

Covers the static shells (scripts/smp/pages/lineup.py / simulator.py) and the
JS-side math: the team_ovr constants live in the shared window.SMPOvr helper in
trade-extras.js (which precedes lineup.js in the bundle and is consumed by both
the Trade Machine and the Lineup Lab); they are regenerated from
scripts/projections.py and the JS formula is mirrored in Python to assert OVR
parity on known groups; simulator.js is asserted to carry the heat_style hsla
convention and to read the logistic model from app-data rather than hardcoding.
"""

import glob
import json
import math
import os
import re
import sys
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_HERE)
_SCRIPTS = os.path.join(_REPO, "scripts")
if _SCRIPTS not in sys.path:
    sys.path.insert(0, _SCRIPTS)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from current_export import load_current_export  # noqa: E402

import projections  # noqa: E402
from smp.core import heat_style, normalize_positions, team_sort_key, active_players, current_season  # noqa: E402
from smp.finance import FIN_SOFT_CAP  # noqa: E402
from smp.simmodel import REPLACEMENT_OVR  # noqa: E402
from smp.pages.lineup import render_lineup_pages  # noqa: E402
from smp.pages.simulator import render_simulator_pages  # noqa: E402

_JS_DIR = os.path.join(_SCRIPTS, "smp", "static", "js")
with open(os.path.join(_JS_DIR, "lineup.js"), encoding="utf-8") as fh:
    LINEUP_JS = fh.read()
with open(os.path.join(_JS_DIR, "trade-extras.js"), encoding="utf-8") as fh:
    TRADE_JS = fh.read()
with open(os.path.join(_JS_DIR, "simulator.js"), encoding="utf-8") as fh:
    SIMULATOR_JS = fh.read()


_SEASON = 2004


def _synthetic_league():
    teams = [
        {"tid": tid, "abbrev": f"T{tid}", "region": f"Region{tid}", "name": f"Name{tid}", "cid": 0}
        for tid in range(4)
    ]
    players = [
        {
            "pid": pid,
            "firstName": "Test",
            "lastName": f"Player{pid}",
            "tid": pid % 4,
            "retiredYear": None,
            "born": {"year": 1980},
            "contract": {"amount": 10000, "exp": _SEASON + 2},
            "ratings": [{"season": _SEASON, "pos": "G", "ovr": 60, "pot": 65}],
            "stats": [],
        }
        for pid in range(8)
    ]
    data = {
        "gameAttributes": [{"key": "season", "value": _SEASON}],
        "teams": teams,
        "players": players,
        "games": [],
        "schedule": [],
    }
    return data, teams, players


class TestLineupShell(unittest.TestCase):
    def test_shell_structure(self):
        data, teams, players = _synthetic_league()
        pages = render_lineup_pages(data, teams, players, _SEASON)
        self.assertEqual(set(pages), {"lineup.html"})
        html = pages["lineup.html"]
        self.assertIn("data-lineup-app", html)
        self.assertIn("<noscript>", html)
        self.assertIn("Lineup Lab", html)
        # ten ARIA combobox slots (5 starters + 5 bench), each with its own listbox
        self.assertEqual(html.count("data-ll-input"), 10)
        self.assertEqual(html.count('role="combobox"'), 10 + 1)  # 10 slots + global nav search
        self.assertEqual(html.count('class="search-results ll-results"'), 10)
        # 5-man / 10-man mode toggle; the bench group ships hidden (5-man default)
        self.assertEqual(html.count("data-ll-mode"), 2)
        self.assertIn('role="radiogroup"', html)
        self.assertIn("data-ll-bench hidden", html)
        self.assertIn("Bench 10", html)
        # The league is uncapped and untaxed: the salary anchor is the league-average
        # payroll (finance.FIN_SOFT_CAP), not a tax line, and the figure is derived
        # from the constant rather than hand-keyed.
        self.assertIn(f"salary vs the ${FIN_SOFT_CAP / 1000:.0f}M league average", html)
        self.assertNotIn("tax line", html)
        # the hero blurb ships once — guards the duplicated-copy bug fixed in lineup.py
        self.assertEqual(html.count("salary vs the"), 1)


class TestSimulatorShell(unittest.TestCase):
    def test_shell_structure_fresh_season(self):
        data, teams, players = _synthetic_league()
        pages = render_simulator_pages(data, teams, players, _SEASON)
        self.assertEqual(set(pages), {"simulator.html"})
        html = pages["simulator.html"]
        self.assertIn("data-wo-app", html)
        self.assertIn("data-wo-games", html)
        self.assertIn("data-wo-odds", html)
        self.assertIn("data-wo-reset", html)
        self.assertIn("<noscript>", html)
        # same-model note + honest fresh-season wording (no completed games above)
        self.assertIn("same team-strength model", html)
        self.assertIn("projected schedule", html)
        self.assertIn("5,000 times", html)

    def test_played_season_wording(self):
        data, teams, players = _synthetic_league()
        data["games"] = [{
            "gid": 1, "season": _SEASON, "day": 1, "playoffs": False,
            "teams": [{"tid": 0, "pts": 100, "players": []}, {"tid": 1, "pts": 90, "players": []}],
        }]
        html = render_simulator_pages(data, teams, players, _SEASON)["simulator.html"]
        self.assertIn("every remaining regular-season game", html)
        self.assertNotIn("hasn't tipped off", html)


def _js_team_ovr_constants():
    """The OVR_A/OVR_B/OVR_K literals shipped in the shared SMPOvr helper
    (trade-extras.js — the single client-side copy; lineup.js consumes it)."""
    out = {}
    for name in ("OVR_A", "OVR_B", "OVR_K"):
        match = re.search(r"const %s = (-?[0-9.]+);" % name, TRADE_JS)
        assert match, f"{name} literal missing from trade-extras.js"
        out[name] = float(match.group(1))
    return out


def _js_team_ovr_mirror(ovrs, a, b, k):
    """Python mirror of lineup.js teamOvrRaw/teamOvr (incl. Math.round semantics)."""
    top = sorted((float(o) for o in ovrs), reverse=True)[:10]
    while len(top) < 10:
        top.append(0.0)
    mov = -k
    for i in range(10):
        mov += a * math.exp(b * i) * top[i]
    raw = mov * 50.0 / 15.0 + 50.0
    return int(math.floor(raw + 0.5))


class TestLineupJsMath(unittest.TestCase):
    """The JS-side team_ovr port must match projections.team_ovr exactly."""

    GROUPS = [
        [80, 75, 70, 68, 66, 64, 62, 60, 58, 56],  # full ten-man roster
        [70, 68, 65, 62, 60],                      # a five-man lineup (pads five zeros)
        [50, 50, 50, 50, 50],
        [90, 88, 85, 84, 80],
        [42],                                      # degenerate single player
    ]

    def test_constants_regenerated_from_projections(self):
        # Regenerate the regular-season branch constants from projections.team_ovr
        # itself: with a=OVR_A, b=OVR_B, k=OVR_K the formula must reproduce
        # projections.team_ovr for every probe group. This pins the JS literals
        # to the Python source of truth without parsing projections.py.
        consts = _js_team_ovr_constants()
        for group in self.GROUPS:
            self.assertEqual(
                _js_team_ovr_mirror(group, consts["OVR_A"], consts["OVR_B"], consts["OVR_K"]),
                projections.team_ovr(group),
                f"JS-mirrored team OVR diverges from projections.team_ovr for {group}",
            )

    def test_lineup_replacement_padding_matches_documented_adaptation(self):
        # lineup.js pads a short group to ten with simmodel.REPLACEMENT_OVR
        # (documented adaptation): lineupOvrRaw(five) == team_ovr(five + [40]*5).
        match = re.search(r"const REPLACEMENT_OVR = (-?[0-9.]+);", LINEUP_JS)
        self.assertIsNotNone(match, "REPLACEMENT_OVR literal missing from lineup.js")
        self.assertEqual(float(match.group(1)), REPLACEMENT_OVR)
        consts = _js_team_ovr_constants()
        for five in ([70, 68, 65, 62, 60], [90, 88, 85, 84, 80], [50] * 5):
            padded = five + [REPLACEMENT_OVR] * 5
            self.assertEqual(
                _js_team_ovr_mirror(padded, consts["OVR_A"], consts["OVR_B"], consts["OVR_K"]),
                projections.team_ovr(padded),
            )

    def test_known_values(self):
        # Fixed known values, computed once from projections.py, guarded here so
        # a silent change to either side is caught. The five-man values are the
        # lineup grade (five picks + replacement bench).
        self.assertEqual(projections.team_ovr([80, 75, 70, 68, 66, 64, 62, 60, 58, 56]), 120)
        self.assertEqual(projections.team_ovr([70, 68, 65, 62, 60] + [REPLACEMENT_OVR] * 5), 53)
        self.assertEqual(projections.team_ovr([90, 88, 85, 84, 80] + [REPLACEMENT_OVR] * 5), 137)
        self.assertEqual(projections.team_ovr([50] * 5 + [REPLACEMENT_OVR] * 5), -13)

    def test_mov_inverse_documented_in_js(self):
        # SMPOvr maps raw OVR back to predicted margin with (raw - 50) * 15/50 —
        # the exact inverse of team_ovr's raw = mov * 50/15 + 50 anchoring.
        self.assertIn("(raw - 50) * 15 / 50", TRADE_JS)
        raw = 62.0
        self.assertAlmostEqual((raw - 50) * 15 / 50, (raw - 50) * 0.3)

    def test_shared_helper_published_and_consumed(self):
        # trade-extras.js precedes lineup.js in build.py's concat order and
        # publishes the one client-side team_ovr port; lineup.js must consume
        # it rather than carrying its own constants.
        self.assertIn("window.SMPOvr = { teamOvrRaw, roundOvr, ovrToMov }", TRADE_JS)
        self.assertIn("window.SMPOvr", LINEUP_JS)
        for name in ("OVR_A", "OVR_B", "OVR_K"):
            self.assertNotIn("const %s =" % name, LINEUP_JS)

    def test_trade_projection_reads_payload_model(self):
        # Post-trade record projections must use app-data.sim's logistic model
        # and season length — parity with the server sim, nothing hardcoded.
        self.assertIn("data.sim.logistic_k", TRADE_JS)
        self.assertIn("data.sim.hca", TRADE_JS)
        self.assertIn("season_games", TRADE_JS)
        self.assertIn("ws_season", TRADE_JS)


class TestSimulatorJsModel(unittest.TestCase):
    def test_logistic_model_read_from_payload_not_hardcoded(self):
        # The client must consume app-data.sim's constants (parity with
        # simmodel.SIM_HCA / SIM_LOGISTIC_K), never its own copies.
        self.assertIn("data.sim.logistic_k", SIMULATOR_JS)
        self.assertIn("data.sim.hca", SIMULATOR_JS)
        self.assertNotIn("0.16", SIMULATOR_JS)
        self.assertNotIn("1.5", SIMULATOR_JS)

    def test_heat_style_convention_matches_core(self):
        # Client heatStyle mirrors core.heat_style: hue = 4 + frac * 126 into
        # hsla(hue, 55%, 41%, .45).
        self.assertIn("4 + frac * 126", SIMULATOR_JS)
        self.assertIn(", 55%, 41%, .45)", SIMULATOR_JS)
        # spot-check the Python side renders the shape the JS reproduces
        self.assertEqual(heat_style(7.0, 0.0, 10.0, 1), "background-color: hsla(92, 55%, 41%, .45)")
        self.assertEqual(heat_style(0.0, 0.0, 10.0, 1), "background-color: hsla(4, 55%, 41%, .45)")

    def test_deterministic_seed_documented(self):
        # Same base seed constant as simmodel.simulate_league's rng, folded with
        # the lock-state string, so identical locks replay identical sims.
        self.assertIn("20290101", SIMULATOR_JS)
        self.assertIn("mulberry32", SIMULATOR_JS)
        self.assertIn("fnv1a", SIMULATOR_JS)
        self.assertIn("5000", re.sub(r"[_,]", "", SIMULATOR_JS))

    def test_lineup_js_uses_payload_logistic(self):
        self.assertIn("payload.sim.logistic_k", LINEUP_JS)
        self.assertIn("payload.sim.hca", LINEUP_JS)


class TestRealExport(unittest.TestCase):
    def test_shells_render_on_real_export(self):
        _, data = load_current_export()
        normalize_positions(data)
        season = current_season(data)
        teams = sorted(data.get("teams", []), key=team_sort_key)
        players = active_players(data)
        lineup_html = render_lineup_pages(data, teams, players, season)["lineup.html"]
        sim_html = render_simulator_pages(data, teams, players, season)["simulator.html"]
        self.assertIn("data-lineup-app", lineup_html)
        self.assertIn("data-wo-app", sim_html)
        self.assertIn(str(season), lineup_html)
        self.assertIn(str(season), sim_html)


if __name__ == "__main__":
    unittest.main()
