"""Tests for scripts/smp/pages/game.py (game-page overhaul: split hero,
momentum bars, DNP footer, FPTS column, Fantasy MVP, Instant Classic chip,
projected box scores)."""

import contextlib
import json
import math
import os
import re
import shutil
import sys
import tempfile
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

    def test_preview_has_no_matchup_card_or_injury_report(self):
        # Both were dropped: the projected box score is built from the same two
        # rosters and states their difference in minutes and points, so a table
        # of roster averages beside it restated the input to a number already on
        # the page.
        self.assertNotIn(">Matchup</h2>", self.html)
        self.assertNotIn("INJURY REPORT", self.html)
        self.assertNotIn("cmp-table", self.html)

    def test_preview_has_projected_rosters(self):
        self.assertIn("Projected active rotation", self.html)
        # A preview shows what is known before tip-off -- ratings and each man's
        # projected contribution to the spread -- not an empty box score. It used
        # to print the played-game columns (FPTS and the rest) with an em-dash in
        # every cell, which is where the 160 dashes on this page came from.
        self.assertIn(">Imp</th>", self.html)
        self.assertNotIn(">FPTS</th>", self.html)
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


PREVIEW_GID = "schedule-2031-3"  # the gid _scheduled_item() mints for day 3


def _projection(gid=PREVIEW_GID, season=2031, home_tid=1, away_tid=2, sims=200,
                home_pts=104.0, away_pts=97.0, home_win_pct=0.62, scrub_minutes=0.4):
    """A projection file for the SMP I preview _scheduled_item() renders.

    Built here rather than read from league-data/: projected_box_scores.json is
    a local artifact the harness writes by hand, and this suite has to pass on a
    clone that has never run scripts/sim/project_box_scores.mjs.

    Minutes descend down each roster and the LAST man is under the floor, so one
    footer name is expected per side. Rows are emitted in roster order, not
    minutes order, so a test can prove the page does the sorting. Points are
    shared out in proportion to minutes so that each side's rows really do add
    up to its team score, the way the harness's output does — a fixture where
    they did not made the printed totals tie on every game and sent the hero
    into Pick 'em regardless of the score it was handed.
    """
    lines = []
    for tid, team_pts in ((home_tid, home_pts), (away_tid, away_pts)):
        roster = game_page.team_roster(tid, PLAYERS)
        assert len(roster) > game_page.PROJECTED_MIN_ROWS, tid
        minutes = [scrub_minutes if i == len(roster) - 1 else round(34.0 - 2.0 * i, 1)
                   for i in range(len(roster))]
        played = sum(minutes)
        for i, player in enumerate(roster):
            lines.append({
                "pid": safe_int(player.get("pid")), "tid": tid,
                "min": minutes[i], "pts": round(team_pts * minutes[i] / played, 1),
                "trb": 4.0, "ast": 2.0,
                "stl": 0.8, "blk": 0.4, "fg": 5.0, "fga": 11.0, "tp": 1.0, "tpa": 3.0,
                "ft": 2.0, "fta": 2.5, "orb": 1.0, "tov": 1.5, "pf": 2.0,
                "gs": 1.0 if i < 5 else 0.0,
            })
    return {
        "season": season, "sims": sims, "generated_from": "test",
        "games": {gid: {
            "home_tid": home_tid, "away_tid": away_tid,
            "home_pts": home_pts, "away_pts": away_pts, "home_win_pct": home_win_pct,
            "players": lines,
        }},
    }


@contextlib.contextmanager
def projection_file(payload):
    """Point game.py at `payload` (a dict, a raw string, or None for no file)."""
    tmp = tempfile.mkdtemp()
    path = os.path.join(tmp, "projected_box_scores.json")
    if payload is not None:
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(payload if isinstance(payload, str) else json.dumps(payload))
    previous = os.environ.get(game_page.PROJECTION_PATH_ENV)
    os.environ[game_page.PROJECTION_PATH_ENV] = path
    game_page.load_projected_box_scores.cache_clear()
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop(game_page.PROJECTION_PATH_ENV, None)
        else:
            os.environ[game_page.PROJECTION_PATH_ENV] = previous
        game_page.load_projected_box_scores.cache_clear()
        shutil.rmtree(tmp, ignore_errors=True)


def _table_rows(html, index):
    """Body rows of the index-th projected box table, as lists of cell text."""
    tables = re.findall(
        r'<table data-sortable class="gx-rot-table gx-pbox-table">(.*?)</table>', html, re.S
    )
    body = tables[index].split("<tbody>")[1].split("</tbody>")[0]
    rows = []
    for row in re.findall(r"<tr.*?</tr>", body, re.S):
        cells = [re.sub(r"<[^>]+>", "", c).strip()
                 for c in re.findall(r"<td[^>]*>(.*?)</td>", row, re.S)]
        rows.append(cells)
    return rows


class TestProjectedBoxScores(unittest.TestCase):
    """Previews swap their rotation tables for a projected box score when the
    Monte Carlo has run the game."""

    def setUp(self):
        self.item = _scheduled_item()

    def test_projection_replaces_the_rotation_tables(self):
        with projection_file(_projection()):
            html = render(self.item, [self.item], 2031)
        self.assertIn("Projected box score", html)
        self.assertEqual(html.count("gx-pbox-table"), 2)
        self.assertNotIn("Projected active rotation", html)
        # Imp is a simmodel term and has no place beside a different model's
        # point estimates; it goes with the rotation table it belonged to.
        self.assertNotIn(">Imp</th>", html)
        self.assertIn("mean of 200 simulations", html)
        self.assertIn(">MIN</th>", html)

    def test_rows_are_sorted_by_projected_minutes(self):
        with projection_file(_projection()):
            html = render(self.item, [self.item], 2031)
        for index in (0, 1):
            rows = _table_rows(html, index)
            self.assertEqual(rows[-1][0], "Total")
            minutes = [float(r[4]) for r in rows[:-1]]
            self.assertEqual(minutes, sorted(minutes, reverse=True))
            self.assertTrue(all(m >= game_page.PROJECTED_MIN_FLOOR for m in minutes))

    def test_sub_floor_player_is_a_footer_line_not_a_row_of_zeros(self):
        with projection_file(_projection(scrub_minutes=0.4)):
            html = render(self.item, [self.item], 2031)
        self.assertEqual(html.count("Reserve, not dressed:"), 2)
        for tid in (1, 2):
            roster = game_page.team_roster(tid, PLAYERS)
            scrub = game_page.player_name(roster[-1])
            self.assertIn(game_page.esc(scrub), html)
        # One man per side sat down, so each table is a row short of the roster.
        self.assertEqual(len(_table_rows(html, 0)) - 1, len(game_page.team_roster(2, PLAYERS)) - 1)

    def test_totals_row_sums_the_printed_rows(self):
        with projection_file(_projection()):
            html = render(self.item, [self.item], 2031)
        for index in (0, 1):
            rows = _table_rows(html, index)
            total = rows[-1]
            for column in (4, 5):  # MIN, PTS
                self.assertAlmostEqual(
                    float(total[column]),
                    round(sum(float(r[column]) for r in rows[:-1]), 1),
                    places=1,
                )

    def test_every_rostered_man_appears_as_a_row_or_in_the_footer(self):
        with projection_file(_projection()):
            html = render(self.item, [self.item], 2031)
        for tid in (1, 2):
            for player in game_page.team_roster(tid, PLAYERS):
                self.assertIn(game_page.esc(game_page.player_name(player)), html)

    def test_figures_carry_one_decimal(self):
        with projection_file(_projection()):
            html = render(self.item, [self.item], 2031)
        for row in _table_rows(html, 0)[:-1]:
            for cell in (row[4], row[5], row[6]):  # MIN, PTS, REB
                self.assertRegex(cell, r"^\d+\.\d$")


class TestProjectedHeroAgreement(unittest.TestCase):
    """The hero may not contradict the box score printed below it."""

    def setUp(self):
        self.item = _scheduled_item()
        self.home_ab = TEAMS_BY_TID[1]["abbrev"]
        self.away_ab = TEAMS_BY_TID[2]["abbrev"]

    def test_hero_quotes_the_projection_when_one_is_published(self):
        with projection_file(_projection(home_pts=104.0, away_pts=97.0, home_win_pct=0.62)):
            html = render(self.item, [self.item], 2031)
        self.assertIn("Win probability · 200 simulations of this game", html)
        self.assertIn(">62.0%<", html)
        self.assertIn(">38.0%<", html)
        self.assertIn("%s -7.0" % self.home_ab, html)

    def test_hero_names_the_side_the_projection_favours(self):
        # Away team ahead on the mean score: the spread must flip with it.
        with projection_file(_projection(home_pts=94.5, away_pts=100.0, home_win_pct=0.31)):
            html = render(self.item, [self.item], 2031)
        self.assertIn("%s -5.5" % self.away_ab, html)
        self.assertIn(">31.0%<", html)
        self.assertIn(">69.0%<", html)

    def test_hero_falls_back_to_the_season_sim_without_a_projection(self):
        with projection_file(None):
            html = render(self.item, [self.item], 2031)
        self.assertIn("Win probability · same model as the season sim", html)
        self.assertNotIn("simulations of this game", html)

    def test_hero_and_body_never_disagree_about_whether_a_projection_exists(self):
        """A projection the body rejects must not still be speaking in the hero.

        The body drops a side that cannot field PROJECTED_MIN_ROWS usable rows;
        before the two shared one gate, the hero went on quoting the run the
        page had just discarded.
        """
        payload = _projection()
        entry = payload["games"][PREVIEW_GID]
        home = [line for line in entry["players"] if line["tid"] == 1]
        entry["players"] = ([line for line in entry["players"] if line["tid"] == 2]
                            + home[:game_page.PROJECTED_MIN_ROWS - 1])
        with projection_file(payload):
            html = render(self.item, [self.item], 2031)
        self.assertNotIn("Projected box score", html)
        self.assertIn("Projected active rotation", html)
        self.assertIn("Win probability · same model as the season sim", html)
        self.assertNotIn("simulations of this game", html)

    def test_pickem_when_the_runs_three_views_of_even_disagree(self):
        """Mean score, win frequency and the printed totals are three views of
        one run. On a coin-flip game they can straddle even; the hero then has
        to say Pick 'em rather than pick a side the rest of the page argues with.
        """
        # Home ahead by 0.1 on the mean score, but losing the win frequency.
        with projection_file(_projection(home_pts=97.1, away_pts=97.0, home_win_pct=0.49)):
            html = render(self.item, [self.item], 2031)
        self.assertIn("Pick &#x27;em", html)
        self.assertNotIn("%s -0.1" % self.home_ab, html)
        self.assertIn(">49.0%<", html)  # the probabilities still say what they say

    def test_a_clear_favourite_is_never_downgraded_to_pickem(self):
        with projection_file(_projection(home_pts=104.0, away_pts=97.0, home_win_pct=0.62)):
            html = render(self.item, [self.item], 2031)
        self.assertNotIn("Pick &#x27;em", html)
        self.assertIn("%s -7.0" % self.home_ab, html)

    def test_printed_margin_ignores_the_men_below_the_minutes_floor(self):
        """projected_printed_margin must sum the ROWS, not the roster — that gap
        is the whole reason the hero consults it."""
        payload = _projection()
        with projection_file(payload):
            data = game_page.projected_box_data(self.item, TEAMS_BY_TID, PLAYERS)
        self.assertIsNotNone(data)
        printed = game_page.projected_printed_margin(data, 1)
        entry = payload["games"][PREVIEW_GID]
        by_tid = {1: 0.0, 2: 0.0}
        for line in entry["players"]:
            if line["min"] >= game_page.PROJECTED_MIN_FLOOR:
                by_tid[line["tid"]] += line["pts"]
        self.assertAlmostEqual(printed, by_tid[1] - by_tid[2], places=6)

    def test_printed_margin_really_can_differ_from_the_full_roster_margin(self):
        """Give one bench-warmer points the other does not have: the Total row
        moves, the team score does not, and the two margins part company. That
        gap is worth up to ~0.6 on the real file."""
        payload = _projection()
        entry = payload["games"][PREVIEW_GID]
        scrub = min((line for line in entry["players"] if line["tid"] == 2),
                    key=lambda line: line["min"])
        self.assertLess(scrub["min"], game_page.PROJECTED_MIN_FLOOR)
        scrub["pts"] += 5.0  # never printed, so it cannot reach the Total row
        with projection_file(payload):
            data = game_page.projected_box_data(self.item, TEAMS_BY_TID, PLAYERS)
        printed = game_page.projected_printed_margin(data, 1)
        full = {1: 0.0, 2: 0.0}
        for line in entry["players"]:
            full[line["tid"]] += line["pts"]
        self.assertAlmostEqual(printed - (full[1] - full[2]), 5.0, places=6)

    def test_no_rotation_total_row_to_disagree_with_the_hero(self):
        # The Matchup card carried a "Rotation total" whose tooltip claimed to be
        # what the spread was built from — true of the season sim, a lie once the
        # hero quoted the game sim. The card is gone, so the claim cannot come back.
        with projection_file(_projection()):
            projected = render(self.item, [self.item], 2031)
        with projection_file(None):
            plain = render(self.item, [self.item], 2031)
        for html in (projected, plain):
            self.assertNotIn("Rotation total", html)
            self.assertNotIn("the spread above is built from", html)


class TestProjectedFallback(unittest.TestCase):
    """Every way the file can be absent, stale or malformed ends on today's
    preview — the projection is optional and may never break a build."""

    def setUp(self):
        self.item = _scheduled_item()
        with projection_file(None):
            self.baseline = render(self.item, [self.item], 2031)
        self.played = item_by_gid(ITEMS_2030, 518)
        with projection_file(None):
            self.played_baseline = render(self.played, ITEMS_2030, 2030)

    def _stale(self, **kwargs):
        payload = _projection()
        entry = payload["games"][PREVIEW_GID]
        for key, value in kwargs.items():
            if key in ("season", "sims"):
                payload[key] = value
            else:
                entry[key] = value
        return payload

    def test_every_broken_shape_renders_the_ordinary_preview(self):
        off_roster = _projection()
        for line in off_roster["games"][PREVIEW_GID]["players"]:
            line["pid"] += 900000
        cases = {
            "no file": None,
            "empty": "",
            "unparseable": "{not json",
            "a list": "[1, 2, 3]",
            "a string": '"nope"',
            "no games key": '{"season": 2031}',
            "games is a list": {"season": 2031, "sims": 200, "games": []},
            "gid absent": {"season": 2031, "sims": 200, "games": {"999999": {}}},
            "another league's season": self._stale(season=2004),
            "home_tid disagrees": self._stale(home_tid=99),
            "away_tid disagrees": self._stale(away_tid=99),
            "players is not a list": self._stale(players={}),
            "every pid off-roster": off_roster,
        }
        for name, payload in cases.items():
            with self.subTest(case=name):
                with projection_file(payload):
                    html = render(self.item, [self.item], 2031)
                self.assertEqual(html, self.baseline)

    def test_played_box_scores_are_untouched_by_the_projection(self):
        """gid 518 was played; nothing about it may change when the file lands.

        The third fixture is a projection that MATCHES gid 518 exactly — right
        season, right gid, right tids — so this proves the played path ignores
        projections outright, not merely that the staleness gate rejected a
        mismatched one.
        """
        matching = _projection(gid="518", season=2030,
                               home_tid=safe_int(self.played["home_tid"]),
                               away_tid=safe_int(self.played["away_tid"]))
        for payload in (None, _projection(), matching):
            with projection_file(payload):
                html = render(self.played, ITEMS_2030, 2030)
            self.assertEqual(html, self.played_baseline)
            self.assertNotIn("Projected box score", html)
            self.assertIn("Did not play:", html)  # the real box score, unchanged

    def test_the_matching_fixture_would_have_been_accepted_on_a_preview(self):
        """Guards the test above: prove the gid-518 fixture is one the gate
        accepts, so 'played pages are unchanged' is not passing by accident."""
        matching = _projection(gid="518", season=2030,
                               home_tid=safe_int(self.played["home_tid"]),
                               away_tid=safe_int(self.played["away_tid"]))
        preview = dict(self.played, gid=518, source="schedule", game=None,
                       home_box=None, away_box=None, home_pts=None, away_pts=None)
        with projection_file(matching):
            self.assertIsNotNone(game_page.projected_game(preview))
            self.assertIsNotNone(
                game_page.projected_box_data(preview, TEAMS_BY_TID, PLAYERS)
            )


class TestDramaThreshold(unittest.TestCase):
    def test_threshold_is_selective_on_real_data(self):
        scores = [drama_index(g, FEATS) for g in DATA.get("games", [])]
        classics = [s for s in scores if s >= game_page.DRAMA_CLASSIC_MIN]
        self.assertGreater(len(classics), 0)
        self.assertLess(len(classics) / len(scores), 0.05)


if __name__ == "__main__":
    unittest.main()
