"""Tests for scripts/smp/pages/game.py (game-page overhaul: split hero,
momentum bars, DNP footer, FPTS column, Fantasy MVP, Instant Classic chip)."""

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

from smp.core import (  # noqa: E402
    ALL_PLAYERS_BY_PID,
    active_players,
    completed_game_items,
    safe_float,
    safe_int,
    team_sort_key,
)
from smp.derived import drama_index, fantasy_pts, feats_index  # noqa: E402
from smp.pages import game as game_page  # noqa: E402

# The SMP II export is a pre-draft snapshot with zero games played, so the only
# real box scores in the repo are SMP I's, archived under league-data/smp1/. The
# renderer is league-agnostic; what it needs is games that were actually played.
_EXPORT = os.path.join(_REPO, "league-data", "smp1", "2031_preseason.json")

with open(_EXPORT, "r", encoding="utf-8") as fh:
    DATA = json.load(fh)

TEAMS = sorted(DATA.get("teams", []), key=team_sort_key)
TEAMS_BY_TID = {int(t["tid"]): t for t in TEAMS}
PLAYERS = active_players(DATA)
FEATS = feats_index(DATA)
ALL_PLAYERS_BY_PID.clear()
ALL_PLAYERS_BY_PID.update(
    {safe_int(p.get("pid")): p for p in DATA.get("players", []) if p.get("pid") is not None}
)

ITEMS_2030 = completed_game_items(DATA, 2030)
ITEMS_2029 = completed_game_items(DATA, 2029)


def item_by_gid(items, gid):
    for item in items:
        if item.get("gid") == gid:
            return item
    raise AssertionError("gid %s not found" % gid)


def render(item, items, season, feats=FEATS):
    return game_page.render_game_page(item, items, TEAMS, PLAYERS, season, feats_by_gid=feats)


class TestSplitHero(unittest.TestCase):
    def setUp(self):
        # gid 518: 2030 day 12, one OT, drama index 68 (the max in the export).
        self.item = item_by_gid(ITEMS_2030, 518)
        self.html = render(self.item, ITEMS_2030, 2030)

    def test_dual_identity_backgrounds_and_vars(self):
        self.assertIn("gx-bg gx-bg-away", self.html)
        self.assertIn("gx-bg gx-bg-home", self.html)
        self.assertIn("--gx-home-primary:", self.html)
        self.assertIn("--gx-away-chart:", self.html)

    def test_winner_and_loser_sides_marked(self):
        self.assertIn("gx-won", self.html)
        self.assertIn("gx-lost", self.html)

    def test_full_team_names_and_records(self):
        for key in ("home_tid", "away_tid"):
            team = TEAMS_BY_TID[safe_int(self.item[key])]
            full = "%s %s" % (team["region"], team["name"])
            self.assertIn(full, self.html)
        self.assertIn("gx-team-record", self.html)
        # Records are real 2030 rows, formatted like 30-15.
        home = TEAMS_BY_TID[safe_int(self.item["home_tid"])]
        row = [r for r in home["seasons"] if r.get("season") == 2030][-1]
        self.assertIn(">%d-%d<" % (row["won"], row["lost"]), self.html)

    def test_no_logo_images(self):
        self.assertNotIn("<img", self.html)

    def test_winner_marked_in_line_score(self):
        self.assertIn("gx-win-row", self.html)
        self.assertIn("gx-win-tick", self.html)
        self.assertEqual(self.html.count("gx-win-row"), 1)

    def test_ot_shown_in_center_label(self):
        self.assertIn("Final · OT", self.html)


class TestInstantClassic(unittest.TestCase):
    def test_high_drama_game_gets_chip(self):
        item = item_by_gid(ITEMS_2030, 518)
        self.assertGreaterEqual(drama_index(item["game"], FEATS), game_page.DRAMA_CLASSIC_MIN)
        html = render(item, ITEMS_2030, 2030)
        self.assertIn("gx-classic", html)
        self.assertIn('href="../classics.html"', html)
        self.assertIn("Instant Classic", html)

    def test_blowout_gets_no_chip(self):
        item = item_by_gid(ITEMS_2029, 445)  # 109-point margin
        self.assertLess(drama_index(item["game"], FEATS), game_page.DRAMA_CLASSIC_MIN)
        html = render(item, ITEMS_2029, 2029)
        self.assertNotIn("gx-classic", html)
        self.assertNotIn("Instant Classic", html)


class TestMomentumBars(unittest.TestCase):
    def test_ot_game_has_five_columns(self):
        item = item_by_gid(ITEMS_2030, 518)
        svg = game_page.momentum_bars_svg(item, TEAMS_BY_TID)
        for label in ("Q1", "Q2", "Q3", "Q4", ">OT<"):
            self.assertIn(label, svg)
        self.assertNotIn("2OT", svg)
        self.assertIn("gx-mom-bar-home", svg)
        self.assertIn("gx-mom-bar-away", svg)
        self.assertIn('role="img"', svg)
        self.assertIn("Period scoring margins", svg)

    def test_regulation_game_has_four_columns(self):
        item = item_by_gid(ITEMS_2029, 445)
        svg = game_page.momentum_bars_svg(item, TEAMS_BY_TID)
        self.assertIn("Q4", svg)
        self.assertNotIn(">OT<", svg)

    def test_bar_direction_matches_period_winner(self):
        item = item_by_gid(ITEMS_2030, 518)
        home_q = item["home_box"]["ptsQtrs"]
        away_q = item["away_box"]["ptsQtrs"]
        svg = game_page.momentum_bars_svg(item, TEAMS_BY_TID)
        home_bars = svg.count("gx-mom-bar-home")
        away_bars = svg.count("gx-mom-bar-away")
        expect_home = sum(1 for h, a in zip(home_q, away_q) if h > a)
        expect_away = sum(1 for h, a in zip(home_q, away_q) if a > h)
        self.assertEqual(home_bars, expect_home)
        self.assertEqual(away_bars, expect_away)

    def test_scheduled_game_has_no_bars(self):
        self.assertEqual(game_page.momentum_bars_svg(_scheduled_item(), TEAMS_BY_TID), "")


class TestBoxScoreTables(unittest.TestCase):
    def setUp(self):
        # gid 225 (2029 day 1): both rosters carry DNP players.
        self.item = item_by_gid(ITEMS_2029, 225)
        self.html = render(self.item, ITEMS_2029, 2029)

    def test_fpts_column_present_in_both_tables(self):
        self.assertEqual(self.html.count(">FPTS</th>"), 2)
        self.assertIn(game_page.FPTS_TITLE, self.html)

    def test_dnp_players_moved_to_footer(self):
        self.assertEqual(self.html.count("Did not play:"), 2)
        for box_key in ("home_box", "away_box"):
            box = self.item[box_key]
            for player_box in box["players"]:
                if safe_float(player_box.get("min")) <= 0:
                    # DNP names appear once (footer), not as a table row.
                    self.assertNotIn(">%s</a> " % player_box["name"], self.html)

    def test_played_rows_match_minutes(self):
        selected, bench_index, dnp = game_page.played_box_players(self.item["home_box"])
        self.assertTrue(all(safe_float(p.get("min")) > 0 for p in selected))
        self.assertTrue(all(safe_float(p.get("min")) <= 0 for p in dnp))
        self.assertEqual(len(selected) + len(dnp), len(self.item["home_box"]["players"]))
        self.assertEqual(bench_index, 5)

    def test_totals_row_carries_team_fpts(self):
        team_fpts = fantasy_pts(self.item["home_box"])
        self.assertIsNotNone(team_fpts)
        # FPTS displays as a whole number; the raw float stays as the sort key.
        self.assertIn(">%d</td>" % int(round(team_fpts)), self.html)

    def test_gmsc_column_replaced_by_fpts(self):
        self.assertNotIn(">GmSc<", self.html)
        self.assertNotIn("ESPN", self.html)

    def test_shot_zone_percentages_have_one_decimal(self):
        zones = self.html.index("Shot Zones")
        pcts = re.findall(r"\((\d+(?:\.\d+)?)%\)", self.html[zones:])
        self.assertTrue(pcts)
        for pct in pcts:
            self.assertRegex(pct, r"^\d+\.\d$")


class TestGameStars(unittest.TestCase):
    def _best(self, item, key_fn):
        best = None
        for box_key in ("home_box", "away_box"):
            for p in item[box_key]["players"]:
                if safe_float(p.get("min")) <= 0:
                    continue
                value = key_fn(p)
                if value is not None and (best is None or value > best[0]):
                    best = (value, p)
        return best

    def test_fantasy_mvp_badge_when_leaders_differ(self):
        item = item_by_gid(ITEMS_2029, 226)
        from smp.core import game_score_value
        potg = self._best(item, game_score_value)[1]
        fmvp = self._best(item, fantasy_pts)[1]
        self.assertNotEqual(potg["pid"], fmvp["pid"])  # sanity: they differ here
        html = render(item, ITEMS_2029, 2029)
        self.assertIn("Fantasy MVP", html)
        self.assertIn(fmvp["name"], html)

    def test_no_extra_badge_when_same_player(self):
        item = item_by_gid(ITEMS_2030, 518)
        from smp.core import game_score_value
        potg = self._best(item, game_score_value)[1]
        fmvp = self._best(item, fantasy_pts)[1]
        self.assertEqual(potg["pid"], fmvp["pid"])  # sanity: same star
        html = render(item, ITEMS_2030, 2030)
        self.assertNotIn("Fantasy MVP", html)
        self.assertIn("FPTS</span>", html)  # POTG line still shows the fantasy total


class TestPagerContext(unittest.TestCase):
    def test_pager_shows_day_and_matchup(self):
        items = ITEMS_2030
        item = items[1]
        html = render(item, items, 2030)
        prev_item, next_item = items[0], items[2]
        for target in (prev_item, next_item):
            away = TEAMS_BY_TID[safe_int(target["away_tid"])]["abbrev"]
            home = TEAMS_BY_TID[safe_int(target["home_tid"])]["abbrev"]
            self.assertIn(
                "Day %d · %s @ %s" % (safe_int(target["day"]), away, home), html
            )
        self.assertIn("← Prev", html)
        self.assertIn("Next →", html)

    def test_first_game_has_disabled_prev(self):
        items = ITEMS_2029
        html = render(items[0], items, 2029)
        self.assertIn("gx-pager disabled", html)


def _scheduled_item(day=3, season=2031, home_tid=1, away_tid=2):
    return {
        "gid": "schedule-%d-%d" % (season, day),
        "day": day,
        "season": season,
        "home_tid": home_tid,
        "away_tid": away_tid,
        "home_pts": None,
        "away_pts": None,
        "home_box": None,
        "away_box": None,
        "game": None,
        "source": "schedule",
        "playoffs": False,
    }


class TestPreviewPages(unittest.TestCase):
    def setUp(self):
        self.item = _scheduled_item()
        self.html = render(self.item, [self.item], 2031)

    def test_preview_still_renders_with_split_hero(self):
        self.assertIn("gx-hero", self.html)
        self.assertIn("gx-bg gx-bg-away", self.html)
        self.assertIn("Scheduled game", self.html)
        # No winner or loser treatment before tip-off.
        self.assertNotIn("gx-won", self.html)
        self.assertNotIn("gx-lost", self.html)
        self.assertNotIn("gx-classic", self.html)

    def test_preview_has_matchup_card_and_projected_rosters(self):
        self.assertIn("Matchup", self.html)
        self.assertIn("INJURY REPORT", self.html)
        self.assertIn("Projected active rotation", self.html)
        self.assertIn(">FPTS</th>", self.html)
        self.assertNotIn("Did not play:", self.html)

    def test_preview_center_is_at_sign(self):
        self.assertIn('<span class="gx-at">@</span>', self.html)


class TestPreviewProjection(unittest.TestCase):
    """The preview hero's projection block: win probabilities + spread, one
    decimal, numerically identical to the Monte Carlo's win_prob model."""

    def setUp(self):
        self.item = _scheduled_item()  # home_tid=1, away_tid=2, season 2031
        self.html = render(self.item, [self.item], 2031)

    def _sim_probability(self):
        from smp.simmodel import SIM_HCA, SIM_LOGISTIC_K, sim_client_inputs
        strengths = sim_client_inputs(DATA, TEAMS, PLAYERS, 2031)["strengths"]
        diff = strengths[1] - strengths[2] + SIM_HCA
        return diff, 1.0 / (1.0 + math.exp(-diff * SIM_LOGISTIC_K))

    def test_projection_block_present_in_hero(self):
        hero_end = self.html.index("box-team-section")
        self.assertIn('class="gx-proj"', self.html[:hero_end])
        self.assertIn("gx-proj-bar", self.html)
        self.assertIn("gx-proj-spread", self.html)

    def test_strengths_match_sim_client_inputs(self):
        from smp.simmodel import sim_client_inputs
        expected = sim_client_inputs(DATA, TEAMS, PLAYERS, 2031)["strengths"]
        computed = game_page.preview_strengths(TEAMS, PLAYERS, 2031)
        self.assertEqual(computed, expected)

    def test_probabilities_one_decimal_and_sum_to_100(self):
        _, p_home = self._sim_probability()
        home_pct = round(p_home * 100, 1)
        away_pct = round(100.0 - home_pct, 1)
        self.assertIn(">%.1f%%<" % home_pct, self.html)
        self.assertIn(">%.1f%%<" % away_pct, self.html)
        self.assertAlmostEqual(home_pct + away_pct, 100.0, places=6)

    def test_spread_shows_favorite_laying_points(self):
        diff, _ = self._sim_probability()
        fav = TEAMS_BY_TID[1 if diff > 0 else 2]["abbrev"]
        self.assertIn("%s %.1f" % (fav, -abs(diff)), self.html)

    def test_completed_game_has_no_projection(self):
        item = item_by_gid(ITEMS_2030, 518)
        html = render(item, ITEMS_2030, 2030)
        self.assertNotIn("gx-proj", html)

    def test_win_prob_formula_matches_simulate_league(self):
        # p = 1/(1+exp(-(sH-sA+1.5)*0.16)) — the exact win_prob inside the sim.
        strengths = {1: 2.0, 2: -1.0}
        p = game_page.preview_home_win_prob(strengths, 1, 2)
        self.assertAlmostEqual(p, 1.0 / (1.0 + math.exp(-(2.0 - (-1.0) + 1.5) * 0.16)), places=12)


class TestDramaThreshold(unittest.TestCase):
    def test_threshold_is_selective_on_real_data(self):
        scores = [drama_index(g, FEATS) for g in DATA.get("games", [])]
        classics = [s for s in scores if s >= game_page.DRAMA_CLASSIC_MIN]
        self.assertGreater(len(classics), 0)
        self.assertLess(len(classics) / len(scores), 0.05)


if __name__ == "__main__":
    unittest.main()
