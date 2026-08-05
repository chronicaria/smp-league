"""Tests for the app-data-driven Compare and Trade Machine pages (W8)."""

import json
import os
import re
import sys
import unittest


_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_HERE)
_SCRIPTS = os.path.join(_REPO, "scripts")
if _SCRIPTS not in sys.path:
    sys.path.insert(0, _SCRIPTS)

import league_generator as lg  # noqa: E402
from smp.finance import FIN_TARGET_PAYROLL  # noqa: E402

_STATIC = os.path.join(_SCRIPTS, "smp", "static")

# SMP II is the 2003-04 pool: the league season is 2004 and stat pages start there.
_SEASON = 2004
_START_SEASON = 2004


def _team(tid, abbrev, region="Test", name=None):
    return {"tid": tid, "abbrev": abbrev, "region": region, "name": name or abbrev}


def _player(pid, first, last, tid=0, exp=_SEASON + 3, amount=20000, ovr=60, stats=None):
    return {
        "pid": pid,
        "firstName": first,
        "lastName": last,
        "tid": tid,
        "retiredYear": None,
        "born": {"year": 1980},
        "contract": {"exp": exp, "amount": amount},
        "ratings": [{"season": _SEASON, "pos": "G", "ovr": ovr, "pot": ovr + 5}],
        "stats": stats if stats is not None else [],
    }


# gp is a full 36-game season (the SMP II regular-season length).
_STAT_ROW = {
    "season": _SEASON,
    "playoffs": False,
    "tid": 0,
    "gp": 36,
    "min": 1500,
    "pts": 1000,
    "fga": 700,
    "fta": 200,
    "per": 20.14,
    "obpm": 2.04,
    "dbpm": 1.5,
    "ows": 3.06,
    "dws": 2.0,
}


def _extract_json(html, element_id):
    match = re.search(
        r'<script type="application/json" id="%s">(.*?)</script>' % element_id, html, re.S
    )
    if not match:
        return None
    return json.loads(match.group(1).replace("<\\/", "</"))


class TestComparePage(unittest.TestCase):
    def setUp(self):
        self.teams = [_team(0, "AAA"), _team(1, "BBB")]
        self.players = [
            _player(1, "Stat", "Haver", tid=0, stats=[dict(_STAT_ROW)]),
            _player(2, "No", "Stats", tid=1),
        ]
        self.prospect = {**_player(9, "Draft", "Kid", tid=-2), "draft": {"year": _SEASON}}
        self.data = {"players": self.players + [self.prospect]}

    def test_no_giant_embedded_payload_and_shell_present(self):
        html = lg.render_compare_page(self.data, self.teams, self.players, _SEASON, _START_SEASON)

        self.assertNotIn('id="compare-data"', html)  # old giant per-page JSON is gone
        self.assertEqual(html.count('role="combobox"'), 3 + 1)  # 3 pickers + header search
        self.assertIn('data-compare-combo="2"', html)
        self.assertIn('data-compare-out', html)
        self.assertIn("Loading player data", html)  # graceful loading state
        self.assertIn("<noscript>", html)
        self.assertIn("data-compare-radar", html)  # radar block + documented mapping
        self.assertIn("Spokes average the 15 subratings", html)

    def test_extras_supplement_covers_players_and_prospects(self):
        html = lg.render_compare_page(self.data, self.teams, self.players, _SEASON, _START_SEASON)

        extras = _extract_json(html, "compare-extra")
        self.assertIsNotNone(extras)
        self.assertEqual(len(extras["ratingKeys"]), 15)
        self.assertEqual(set(extras["stats"]), {"1", "2", "9"})
        gp, ts, per, bpm, ws = extras["stats"]["1"]
        self.assertEqual(gp, 36)
        # TS% = 100 * 1000 / (2 * (700 + 0.44 * 200)) = 63.5 (1dp)
        self.assertEqual(ts, 63.5)
        self.assertEqual(per, 20.1)
        self.assertEqual(bpm, 3.5)   # obpm + dbpm
        self.assertEqual(ws, 5.1)    # ows + dws
        self.assertEqual(extras["stats"]["2"], [0, None, 0.0, 0.0, 0.0])

    def test_supplement_escapes_script_close(self):
        payload = lg.compare_extras_payload(self.data, self.players, _SEASON, _START_SEASON)
        self.assertNotIn("</script", payload)


class TestTradePage(unittest.TestCase):
    def setUp(self):
        self.teams = [_team(0, "AAA"), _team(1, "BBB")]
        self.players = [
            _player(1, "Big", "Contract", tid=0, amount=30000, stats=[dict(_STAT_ROW)]),
            _player(2, "Other", "Guy", tid=1, amount=15000),
        ]
        self.data = {
            "players": self.players,
            "draftPicks": [
                {"dpid": 11, "tid": 0, "originalTid": 0, "season": 2005, "round": 1},
                {"dpid": 12, "tid": 0, "originalTid": 1, "season": 2006, "round": 2},
                {"dpid": 13, "tid": -1, "originalTid": 0, "season": 2005, "round": 1},
                {"dpid": 14, "tid": 1, "originalTid": 1, "season": "fuzz", "round": 1},
            ],
        }

    def test_no_embedded_roster_payload_and_shell_present(self):
        html = lg.render_trade_page(self.data, self.teams, self.players, _SEASON)

        self.assertNotIn('id="trade-data"', html)  # old giant per-page JSON is gone
        self.assertNotIn("renderSummary", html)    # inline JS constant moved to the bundle
        self.assertIn('data-trade-combo="0"', html)
        self.assertIn('data-trade-combo="1"', html)
        self.assertIn('data-trade-filter="1"', html)
        self.assertIn("Loading rosters", html)
        self.assertIn("data-trade-summary", html)
        self.assertIn("<noscript>", html)
        # server-rendered contract efficiency table is preserved
        self.assertIn("Contract Efficiency", html)
        self.assertIn("Big Contract", html)

    def test_value_metric_removed(self):
        html = lg.render_trade_page(self.data, self.teams, self.players, _SEASON)

        self.assertNotIn(">Value<", html)     # contract-efficiency Value column is gone
        self.assertIn(">WS per $10M<", html)  # efficiency stays WS-per-dollar-based

    def test_finance_readout_is_the_league_average_not_a_tax_line(self):
        # The league is uncapped and untaxed, so the shell frames payroll against the
        # league-average target (finance.FIN_TARGET_PAYROLL) and says so outright.
        html = lg.render_trade_page(self.data, self.teams, self.players, _SEASON)

        self.assertIn(f"${FIN_TARGET_PAYROLL / 1000:.0f}M league-average target", html)
        self.assertIn("there is no cap", html)
        for gone in ("luxury tax", "tax line", "tax bill"):
            self.assertNotIn(gone, html)

    def test_picks_supplement_labels_and_filtering(self):
        html = lg.render_trade_page(self.data, self.teams, self.players, _SEASON)

        extras = _extract_json(html, "trade-extra")
        self.assertIsNotNone(extras)
        self.assertEqual(set(extras["picks"]), {"0"})  # invalid tids/seasons dropped
        labels = {p["id"]: p["label"] for p in extras["picks"]["0"]}
        self.assertEqual(labels[11], "2005")
        self.assertEqual(labels[12], "2006 2nd (via BBB)")


class TestStaticAppAssets(unittest.TestCase):
    def _read(self, *parts):
        with open(os.path.join(_STATIC, *parts), encoding="utf-8") as fh:
            return fh.read()

    def test_compare_js_owns_shared_namespace_and_fetches_app_data(self):
        js = self._read("js", "compare.js")
        self.assertIn("assets/app-data.json", js)
        self.assertIn("window.SMPApps", js)
        self.assertIn("createCombobox", js)
        self.assertIn("radar", js)
        # radar spoke mapping stays the documented 6 spokes
        for spoke in ("Shooting", "Finishing", "Athleticism", "Playmaking", "Defense", "IQ"):
            self.assertIn("'%s'" % spoke, js)

    def test_trade_extras_js_consumes_namespace_and_payroll_line(self):
        js = self._read("js", "trade-extras.js")
        self.assertIn("window.SMPApps", js)
        # app-data still ships the line under the legacy "tax_line" key, but there is
        # no tax: the readout compares payroll to the league average and the "--over"
        # hook styles a team above it, not a taxpayer.
        self.assertIn("finance.tax_line", js)
        self.assertIn("tfin-team--over", js)
        self.assertIn("' above the '", js)
        self.assertIn("league average", js)
        self.assertNotIn("luxury", js)

    def test_trade_extras_js_projection_replaces_value(self):
        js = self._read("js", "trade-extras.js")
        # the engine "value" metric is gone: no per-player value column, no
        # value-based verdicts — replaced by the post-trade roster projection
        self.assertNotIn("trade-val", js)
        self.assertNotIn("wins this trade", js)
        for hook in ("window.SMPOvr", "tproj-side", "tproj-verdict", "projectedWins"):
            self.assertIn(hook, js)
        # win-shares ledger sums the app-data "ws" field per side
        self.assertIn("p.ws", js)

    def test_apps_css_covers_both_themes_hooks(self):
        css = self._read("css", "apps.css")
        for cls in (".combo-list", ".radar-poly", ".tfin-tick", ".app-loading", ".app-error",
                    ".tproj-side", ".tproj-delta--down", ".tproj-verdict"):
            self.assertIn(cls, css)
        # theme tokens only — no hardcoded page-background colors
        self.assertIn("var(--", css)


if __name__ == "__main__":
    unittest.main()
