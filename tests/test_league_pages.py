"""Tests for the league pages (W5/P8): draft re-grades, led-league gold styling,
the Rafters pennant strip, records/history polish, FA cards, schedule empty state,
schedule game projections (win% + spread), current-season feats default tab, and
one-decimal draft odds."""

import glob
import json
import os
import sys
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_HERE)
_SCRIPTS = os.path.join(_REPO, "scripts")
if _SCRIPTS not in sys.path:
    sys.path.insert(0, _SCRIPTS)

from smp.pages import league as lp  # noqa: E402
from smp.core import normalize_positions, current_season, team_sort_key  # noqa: E402


def _load_export(name="2031_preseason.json"):
    # These pages recap a season that has been PLAYED -- champions, history,
    # records, draft re-grades, a live schedule. The SMP II export is a pre-draft
    # snapshot with zero games, so the only export that exercises them is the
    # archived SMP I league; the renderers are league-agnostic. Look in
    # league-data/ first so a future played-season export takes over on its own.
    matches = glob.glob(os.path.join(_REPO, "league-data", name)) or glob.glob(
        os.path.join(_REPO, "league-data", "smp1", name)
    )
    if not matches:
        raise unittest.SkipTest("no %s export available" % name)
    with open(matches[0], "r", encoding="utf-8") as fh:
        data = json.load(fh)
    normalize_positions(data)
    return data


class _ExportCase(unittest.TestCase):
    """Loads the real export once for integration-style page assertions."""

    data = None

    @classmethod
    def setUpClass(cls):
        cls.data = _load_export()
        cls.season = current_season(cls.data)
        cls.teams = sorted(cls.data.get("teams", []), key=team_sort_key)


class TestOrdinalAndNotes(unittest.TestCase):
    def test_ordinal(self):
        self.assertEqual(lp.ordinal(1), "1st")
        self.assertEqual(lp.ordinal(2), "2nd")
        self.assertEqual(lp.ordinal(3), "3rd")
        self.assertEqual(lp.ordinal(4), "4th")
        self.assertEqual(lp.ordinal(11), "11th")
        self.assertEqual(lp.ordinal(12), "12th")
        self.assertEqual(lp.ordinal(21), "21st")

    def test_steal_needs_production(self):
        # top-3 class value from outside the lottery, with real minutes -> steal
        note = lp._regrade_note(11, 1, {"gp": 102}, class_matured=True)
        self.assertEqual(note[0], "badge-good")
        self.assertIn("1st in class by career WS, picked 11th", note[1])
        # same rank gap but a 10-game cameo is noise, not a steal
        self.assertIsNone(lp._regrade_note(11, 1, {"gp": 10}, class_matured=True))

    def test_bust_needs_high_pick_and_mature_class(self):
        note = lp._regrade_note(1, 5, {"gp": 14}, class_matured=True)
        self.assertEqual(note[0], "badge-bad")
        self.assertIn("Picked 1st, 5th in class by career WS", note[1])
        # immature classes are too early to call
        self.assertIsNone(lp._regrade_note(1, 5, {"gp": 14}, class_matured=False))
        # late picks never read as busts
        self.assertIsNone(lp._regrade_note(9, 14, {"gp": 50}, class_matured=True))

    def test_never_played_high_pick(self):
        note = lp._regrade_note(4, None, {"gp": 0}, class_matured=True)
        self.assertEqual(note[0], "badge-bad")
        self.assertIn("yet to play", note[1])
        self.assertIsNone(lp._regrade_note(4, None, {"gp": 0}, class_matured=False))


class TestLedLeagueMark(unittest.TestCase):
    def test_mark_wraps_value_with_gold_class_and_sr_text(self):
        html = lp.led_league_mark("31.5 PTS", "Led the league in PTS in 2030")
        self.assertIn('class="led-league"', html)
        self.assertIn("31.5 PTS", html)
        self.assertIn("led-star", html)
        self.assertIn("(led the league)", html)
        self.assertIn('title="Led the league in PTS in 2030"', html)


class TestHonorChips(unittest.TestCase):
    def test_empty_honors_render_dash(self):
        self.assertIn("muted", lp.honor_chips_html([]))

    def test_repeat_honors_group_with_count(self):
        html = lp.honor_chips_html([("mvp", 2029), ("mvp", 2030), ("roy", 2027)])
        self.assertIn("×2", html)
        self.assertIn("MVP 2029, 2030", html)
        self.assertIn("Rookie of the Year 2027", html)
        # crest svgs come from identity.crest_svg (currentColor tinting)
        self.assertIn('fill="currentColor"', html)


class TestPennants(unittest.TestCase):
    def test_pennant_uses_team_vars_and_label(self):
        team = {"tid": 2, "abbrev": "CAM", "region": "Cambridge", "name": "Platypuses"}
        svg = lp.pennant_svg(team, 2030)
        self.assertIn("--team-primary:", svg)
        self.assertIn("var(--team-primary)", svg)
        self.assertIn('aria-label="Cambridge Platypuses — 2030 champions"', svg)
        self.assertIn("2030", svg)

    def test_empty_pennant_is_decorative(self):
        team = {"tid": 0, "abbrev": "DUR", "region": "Durham", "name": "Destroyers"}
        svg = lp.pennant_svg(team)
        self.assertIn('aria-hidden="true"', svg)
        self.assertIn("rafters-pennant-empty", svg)
        self.assertNotIn("CHAMPS", svg)


class TestChampionsIndex(_ExportCase):
    def test_champions_by_season_matches_known_history(self):
        champs = lp.champions_by_season(self.data)
        self.assertEqual(champs.get(2026), 5)   # Gooners
        self.assertEqual(champs.get(2027), 1)   # Dragons
        self.assertEqual(champs.get(2028), 2)   # Platypuses
        self.assertEqual(champs.get(2029), 6)   # Bears
        self.assertEqual(champs.get(2030), 2)   # Platypuses


class TestDraftRegrades(_ExportCase):
    @classmethod
    def setUpClass(cls):
        super(TestDraftRegrades, cls).setUpClass()
        cls.html = lp.render_draft_page(cls.data, cls.teams, cls.season)

    def test_every_past_class_gets_a_panel(self):
        for year in (2026, 2027, 2028, 2029, 2030):
            self.assertIn(f'id="panel-regrade-{year}"', self.html)
        # future classes are prospect panels, not re-grades
        self.assertNotIn('id="panel-regrade-2031"', self.html)

    def test_regrade_rows_carry_value_and_callouts(self):
        self.assertIn("Draft Re-Grades", self.html)
        # Ed Johnson: 2nd-round pick 11 with the best career WS of the 2027 class
        self.assertIn("1st in class by career WS, picked 11th", self.html)
        # Sam Lewis: 2027 #1 pick outside the class top four by WS
        self.assertIn("Picked 1st, 5th in class by career WS", self.html)

    def test_still_on_team_marker_present(self):
        self.assertIn("regrade-still", self.html)
        self.assertIn("Still with the team that drafted him", self.html)

    def test_award_crests_render_in_regrades(self):
        self.assertIn("regrade-crest", self.html)

    def test_rookie_class_states_no_games_honestly(self):
        self.assertIn("class debuts in 2031 · nothing to re-grade yet", self.html)


class TestHistoryPage(_ExportCase):
    @classmethod
    def setUpClass(cls):
        super(TestHistoryPage, cls).setUpClass()
        cls.html = lp.render_history_page(cls.data, cls.teams)

    def test_rafters_strip_has_all_franchises_and_titles(self):
        self.assertEqual(self.html.count("rafters-slot"), 10)
        # five championships across four franchises
        self.assertEqual(self.html.count('<svg class="rafters-pennant"'), 5)
        self.assertEqual(self.html.count("rafters-pennant-empty"), 6)
        self.assertIn('href="#season-2030"', self.html)

    def test_season_cards_are_linkable(self):
        for year in (2026, 2030):
            self.assertIn(f'id="season-{year}"', self.html)

    def test_led_league_gold_marks_present(self):
        self.assertIn('class="led-league"', self.html)
        self.assertIn("Led the league in", self.html)

    def test_transaction_log_filters_and_draft_events(self):
        self.assertIn("data-txlog", self.html)
        self.assertIn("data-tx-type-filter", self.html)
        self.assertIn("data-tx-team-filter", self.html)
        self.assertIn('data-tx-type="draft"', self.html)
        # the 2026 fantasy draft (1,500+ seeding picks) must stay out of the log
        self.assertNotIn("2026 fantasy draft", self.html)

    def test_transaction_items_carry_team_ids_for_filtering(self):
        self.assertIn('data-tx-tids=",', self.html)


class TestRecordsPage(_ExportCase):
    @classmethod
    def setUpClass(cls):
        super(TestRecordsPage, cls).setUpClass()
        cls.html = lp.render_records_page(cls.data, cls.teams, cls.season)

    def test_feats_tables_drop_redundant_season_column(self):
        # the per-season tab already names the season; no Season column inside
        header_zone = self.html.split('id="feats-2026"')[1].split("</thead>")[0]
        self.assertNotIn(">Season<", header_zone)
        self.assertIn(">Player<", header_zone)

    def test_single_game_feat_leaders_marked_gold(self):
        self.assertIn("Best single-game", self.html)
        self.assertIn('class="led-league"', self.html)

    def test_all_time_leaders_have_totals_and_per_game_panels(self):
        self.assertIn('data-leaders-panel="totals"', self.html)
        self.assertIn('data-leaders-panel="pg"', self.html)
        self.assertIn("data-leaders-toggle", self.html)
        self.assertIn("Points Per Game", self.html)
        self.assertIn("Career Points", self.html)


class TestFreeAgencyPage(_ExportCase):
    @classmethod
    def setUpClass(cls):
        super(TestFreeAgencyPage, cls).setUpClass()
        from smp.core import free_agents
        cls.html = lp.render_free_agency_page(free_agents(cls.data), cls.teams, cls.season, 2026)

    def test_top_ten_card_strip(self):
        self.assertIn("fa-card-strip", self.html)
        self.assertEqual(self.html.count('class="fa-card"'), 10)
        self.assertIn("fa-card-ask", self.html)
        self.assertIn("Asking price", self.html)

    def test_cards_use_portrait_chain(self):
        # every card carries either an <img> portrait or a monogram fallback
        self.assertIn("fa-card-portrait", self.html)


class TestSchedulePage(_ExportCase):
    def test_offseason_empty_state_points_to_projections(self):
        html = lp.render_schedule_page(self.data, self.teams)
        self.assertIn("sched-empty", html)
        self.assertIn("hasn't been released yet", html)
        self.assertIn('href="index.html"', html)
        self.assertIn("title odds", html)


class TestFeatsDefaultTab(_ExportCase):
    """records.html Single-Game Feats: the CURRENT season tab is the visible
    default (honest empty state until games play), newest seasons first."""

    @classmethod
    def setUpClass(cls):
        super(TestFeatsDefaultTab, cls).setUpClass()
        cls.html = lp.render_records_page(cls.data, cls.teams, cls.season)

    def test_current_season_tab_is_default_and_first(self):
        self.assertEqual(self.season, 2031)
        self.assertIn('id="tab-feats-2031" aria-controls="panel-feats-2031" '
                      'aria-selected="true"', self.html)
        self.assertLess(self.html.index('data-tab-target="panel-feats-2031"'),
                        self.html.index('data-tab-target="panel-feats-2030"'))

    def test_current_season_panel_visible_others_hidden(self):
        self.assertIn('id="panel-feats-2031" role="tabpanel" aria-labelledby="tab-feats-2031" data-tab-panel>', self.html)
        self.assertIn('id="panel-feats-2030" role="tabpanel" aria-labelledby="tab-feats-2030" data-tab-panel hidden>', self.html)

    def test_current_season_empty_state_is_honest(self):
        # no 2031 feats in this export yet -> the default tab explains itself
        self.assertIn("No feats in 2031 yet", self.html)


class TestScheduleProjections(unittest.TestCase):
    """Unplayed scheduled games carry sim-model win% (one decimal, both teams
    via the two team columns + the title tooltip) and a spread."""

    @classmethod
    def setUpClass(cls):
        cls.data = _load_export("2031_regularseason.json")
        cls.season = current_season(cls.data)
        cls.teams = sorted(cls.data.get("teams", []), key=team_sort_key)
        cls.html = lp.render_schedule_page(cls.data, cls.teams)

    def test_projections_render_for_unplayed_games(self):
        self.assertIn("sched-proj", self.html)
        self.assertIn("sched-spread", self.html)
        self.assertIn("proj. win% &amp; spread", self.html)

    def test_win_probabilities_are_one_decimal(self):
        import re
        pcts = re.findall(r'class="sched-proj[^"]*">(\d+\.\d)%', self.html)
        self.assertTrue(pcts, "expected win-probability chips on unplayed games")
        # spreads are signed one-decimal numbers
        spreads = re.findall(r'class="sched-spread">([+-]\d+\.\d)<', self.html)
        self.assertTrue(spreads)

    def test_tooltip_names_both_teams(self):
        import re
        details = re.findall(r'title="Projected: (\w+) (\d+\.\d)% · (\w+) (\d+\.\d)%', self.html)
        self.assertTrue(details)
        for home, p_home, away, p_away in details[:20]:
            self.assertNotEqual(home, away)
            self.assertAlmostEqual(float(p_home) + float(p_away), 100.0, delta=0.11)

    def test_projection_numbers_match_sim_client_inputs(self):
        import math
        from smp.simmodel import sim_client_inputs
        from smp.core import active_players
        sim = sim_client_inputs(self.data, self.teams, active_players(self.data), self.season)
        strengths = sim["strengths"]
        items = [
            {"gid": 1, "season": self.season, "home_tid": 0, "away_tid": 1},
        ]
        proj = lp._game_projections(self.data, self.teams, self.season, items)
        p_home, margin = proj["1"]
        expected_margin = strengths[0] - strengths[1] + sim["hca"]
        self.assertAlmostEqual(margin, expected_margin, places=9)
        self.assertAlmostEqual(p_home, 1.0 / (1.0 + math.exp(-expected_margin * sim["logistic_k"])), places=9)


class TestSpreadAndOddsFormatting(unittest.TestCase):
    def test_spread_label_is_betting_style(self):
        # a team projected to win by 3.24 is a -3.2 favorite
        self.assertEqual(lp._spread_label(3.24), "-3.2")
        self.assertEqual(lp._spread_label(-3.24), "+3.2")
        self.assertEqual(lp._spread_label(0.01), "+0.0")

    def test_odds_pct_one_decimal_with_conventions(self):
        self.assertEqual(lp._odds_pct(42.0), "42.0%")
        self.assertEqual(lp._odds_pct(0.26), "0.3%")
        self.assertEqual(lp._odds_pct(0.04), "&lt;0.1%")
        self.assertEqual(lp._odds_pct(0.0), "—")


if __name__ == "__main__":
    unittest.main()
