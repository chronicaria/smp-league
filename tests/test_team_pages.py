"""W2 regression tests: team-page immersion, Starting Five, banners, depth
chart, scoring share, four factors, honest preseason states, Franchise Arc."""

import os
import sys
import unittest


_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_HERE)
_SCRIPTS = os.path.join(_REPO, "scripts")
if _SCRIPTS not in sys.path:
    sys.path.insert(0, _SCRIPTS)

import league_generator as lg  # noqa: E402
from smp.pages import team as team_page  # noqa: E402


def _team(tid, abbrev, region="Test", name=None):
    return {"tid": tid, "abbrev": abbrev, "region": region, "name": name or abbrev}


def _player(pid, first, last, tid=0, exp=2030, amount=10000, ovr=60, pos="PG", stats=None):
    return {
        "pid": pid,
        "firstName": first,
        "lastName": last,
        "tid": tid,
        "retiredYear": None,
        "born": {"year": 2000},
        "contract": {"exp": exp, "amount": amount},
        "ratings": [{"season": 2029, "pos": pos, "ovr": ovr, "pot": ovr + 2}],
        "stats": stats or [],
    }


def _stat_row(season=2030, gp=40, pts=800, fga=600, ast=200, tid=0):
    return {"season": season, "playoffs": False, "gp": gp, "min": gp * 30.0,
            "pts": pts, "fga": fga, "fg": int(fga * 0.5), "fta": 100, "ft": 80,
            "tp": 50, "tpa": 140, "ast": ast, "orb": 40, "drb": 160,
            "stl": 30, "blk": 20, "tov": 80, "tid": tid}


def _mil(amount):
    """The page's own short money label for a FIN_* constant ($5M, $2.5M), so the
    finance assertions track the constants instead of a rebalanced literal."""
    return team_page._fin_mil(amount)


def _playoff_series(season, home_tid, away_tid, home_won, away_won):
    return {
        "season": season,
        "series": [
            [  # semifinal round (2 matchups so expected rounds = 2)
                {"home": {"tid": home_tid, "won": 4}, "away": {"tid": 8, "won": 0}},
                {"home": {"tid": away_tid, "won": 4}, "away": {"tid": 9, "won": 1}},
            ],
            [  # final
                {"home": {"tid": home_tid, "won": home_won},
                 "away": {"tid": away_tid, "won": away_won}},
            ],
        ],
    }


class TestChampionsAndBanners(unittest.TestCase):
    def test_decided_final_yields_champion_and_runner_up(self):
        data = {"gameAttributes": {"season": 2031},
                "playoffSeries": [_playoff_series(2030, 2, 4, 4, 0)]}
        champs = team_page.champions_by_season(data)
        self.assertEqual(champs[2030]["champ"], 2)
        self.assertEqual(champs[2030]["runner_up"], 4)
        self.assertEqual(champs[2030]["rounds"], 2)

    def test_current_season_final_in_progress_is_not_a_title(self):
        # 2-1 in a best-of-7 (default games-to-win 4) must not mint a champion.
        data = {"gameAttributes": {"season": 2031},
                "playoffSeries": [_playoff_series(2031, 2, 4, 2, 1)]}
        self.assertEqual(team_page.champions_by_season(data), {})

    def test_past_season_short_final_still_counts(self):
        # 2026 finals ended 3-2 (games-to-win was 3 then); past seasons read the
        # decided series even though the retained games are gone.
        data = {"gameAttributes": {"season": 2031},
                "playoffSeries": [_playoff_series(2026, 5, 2, 3, 2)]}
        self.assertEqual(team_page.champions_by_season(data)[2026]["champ"], 5)

    def test_banner_history_and_kinds(self):
        data = {"gameAttributes": {"season": 2031},
                "playoffSeries": [_playoff_series(2029, 6, 2, 4, 1),
                                  _playoff_series(2030, 2, 4, 4, 0)]}
        entries = team_page.team_banner_history(data, 2)
        self.assertEqual([(e["season"], e["kind"]) for e in entries],
                         [(2029, "finals"), (2030, "title")])

    def test_banner_svg_variants(self):
        title = team_page.banner_svg(2030, "title", tid=2)
        finals = team_page.banner_svg(2029, "finals")
        self.assertIn("banner--title", title)
        self.assertIn("--team-primary", title)  # standalone: vars baked on
        self.assertIn("2030 League Champions", title)
        self.assertIn("CHAMPS", title)          # legible caption on the big banner
        self.assertIn("banner--finals", finals)
        self.assertIn("FINALS", finals)

    def test_rafters_render_nothing_without_titles(self):
        data = {"gameAttributes": {"season": 2031},
                "playoffSeries": [_playoff_series(2030, 2, 4, 4, 0)]}
        self.assertEqual(team_page.team_rafters_html(data, _team(0, "DUR")), "")
        self.assertIn("tm-rafters", team_page.team_rafters_html(data, _team(2, "CAM")))


class TestHonestSeasonFallbacks(unittest.TestCase):
    def _items_2030(self):
        return [{
            "gid": 10, "day": 1, "season": 2030, "home_tid": 0, "away_tid": 1,
            "home_pts": 100, "away_pts": 90,
            "home_box": {"tid": 0, "pts": 100}, "away_box": {"tid": 1, "pts": 90},
            "game": {"gid": 10}, "playoffs": False,
        }]

    def test_games_table_falls_back_to_last_completed_season(self):
        teams_by_tid = {0: _team(0, "AAA"), 1: _team(1, "BBB")}
        html = lg.team_games_table(_team(0, "AAA"), self._items_2030(), teams_by_tid, 2031)
        self.assertIn("2030 Season Log", html)
        self.assertIn("no 2031 games yet", html)
        self.assertIn("2030 season game log", html)
        self.assertNotIn("current-season game log", html)

    def test_games_table_current_season_unchanged(self):
        teams_by_tid = {0: _team(0, "AAA"), 1: _team(1, "BBB")}
        html = lg.team_games_table(_team(0, "AAA"), self._items_2030(), teams_by_tid, 2030)
        self.assertIn("All Games", html)
        self.assertIn("current-season game log", html)

    def test_rotation_map_notes_fallback_season(self):
        data = {"games": [{
            "gid": 10, "season": 2030, "day": 1, "playoffs": False,
            "teams": [
                {"tid": 0, "pts": 100, "players": [{"pid": 1, "name": "A Guard", "min": 30}]},
                {"tid": 1, "pts": 90, "players": [{"pid": 2, "name": "B Wing", "min": 30}]},
            ],
        }]}
        items = lg.completed_game_items(data, season=2030, playoffs=False)
        logs = lg.build_game_logs(data, 2030)
        html = lg.rotation_map_card(_team(0, "AAA"), [], items, logs, 2031,
                                    {0: _team(0, "AAA"), 1: _team(1, "BBB")})
        self.assertIn("in 2030 (no 2031 games yet)", html)
        self.assertIn("red to green = minutes", html)
        self.assertIn('data-gid="10"', html)


class TestDepthChartCards(unittest.TestCase):
    def test_card_rows_labels_vacancies_and_stat_lines(self):
        roster = [
            _player(1, "Point", "Guard", pos="PG", ovr=70,
                    stats=[_stat_row(gp=40, pts=800, ast=200)]),
            _player(2, "Backup", "Guard", pos="PG", ovr=60),
            _player(3, "Deep", "Guard", pos="PG", ovr=50),
            _player(4, "Fourth", "Guard", pos="PG", ovr=45),
            _player(5, "Big", "Center", pos="C", ovr=65),
        ]
        roster[0]["jerseyNumber"] = 7
        html = team_page.depth_chart_card(roster, 2031, 2026)
        for label in ("Starters", "2nd String", "Reserves"):
            self.assertIn(label, html)
        # a 12-man roster never fills a 5-wide grid three deep: everything at
        # depth 3+ collapses into Reserves instead of a "3rd String" row
        self.assertNotIn("3rd String", html)
        # only the Starters row pads to five slots; SG/SF/PF have nobody at all
        self.assertEqual(html.count("depth-card--vacant"), 3)
        self.assertIn("#7", html)                      # jersey number shown
        self.assertIn("depth-ovr", html)               # OVR chip
        self.assertIn("<strong>20.0</strong><small>PTS</small>", html)  # 800/40
        self.assertIn("<strong>—</strong><small>PTS</small>", html)     # no-stats line
        for p in roster:
            self.assertEqual(html.count(lg.player_url(p, "../")), 1)

    def test_rows_below_the_starters_end_when_the_bucket_runs_out(self):
        roster = [_player(1, "Only", "Guy", pos="PG", ovr=70)]
        html = team_page.depth_chart_card(roster, 2031, 2026)
        self.assertIn("Starters", html)
        self.assertEqual(html.count("depth-card--vacant"), 4)  # SG/SF/PF/C empty
        self.assertNotIn("2nd String", html)
        self.assertNotIn("Reserves", html)


class TestScoringShare(unittest.TestCase):
    def test_sorted_segments_and_toggle(self):
        roster = [
            _player(1, "High", "Scorer", stats=[_stat_row(pts=1000, fga=700, ast=100)]),
            _player(2, "Low", "Scorer", stats=[_stat_row(pts=500, fga=500, ast=300)]),
            _player(3, "No", "Games", stats=[]),
        ]
        html = team_page.scoring_share_card(_team(0, "AAA"), roster, 2031)
        self.assertIn("data-share-card", html)
        for key in ("pts", "fga", "ast"):
            self.assertIn(f'data-share-panel="{key}"', html)
        pts_panel = html.split('data-share-panel="pts"')[1].split("</div>\n")[0]
        self.assertLess(pts_panel.index("High Scorer"), pts_panel.index("Low Scorer"))
        # AST panel sorted the other way
        ast_panel = html.split('data-share-panel="ast"')[1]
        self.assertLess(ast_panel.index("Low Scorer"), ast_panel.index("High Scorer"))
        self.assertNotIn("No Games", html)

    def test_empty_without_any_stats(self):
        roster = [_player(1, "No", "Games", stats=[])]
        self.assertEqual(team_page.scoring_share_card(_team(0, "AAA"), roster, 2031), "")


class TestFourFactors(unittest.TestCase):
    def _teams(self):
        def stat(tid, fg, oppfg):
            return {"season": 2030, "playoffs": False, "gp": 40, "tid": tid,
                    "fg": fg, "tp": 300, "fga": 3200, "tov": 500, "fta": 800,
                    "ft": 640, "orb": 400, "drb": 1200, "pts": 4200, "oppPts": 4100,
                    "oppFg": oppfg, "oppTp": 280, "oppFga": 3100, "oppTov": 480,
                    "oppFta": 700, "oppFt": 560, "oppOrb": 380, "oppDrb": 1150}
        a = dict(_team(0, "AAA"), seasons=[], stats=[stat(0, 1700, 1500)])
        b = dict(_team(1, "BBB"), seasons=[], stats=[stat(1, 1500, 1700)])
        return [a, b]

    def test_diverging_strip_renders_rows(self):
        teams = self._teams()
        html = team_page.four_factors_card({"games": []}, teams[0], teams, 2031)
        self.assertIn("Four Factors", html)
        self.assertIn("league average", html)
        self.assertIn("eFG%", html)
        self.assertIn("Opp eFG%", html)
        self.assertIn("ff-bar-good", html)   # team A shoots better than league avg
        self.assertIn("no 2031 team stats yet", html)

    def test_requires_two_teams_with_stats(self):
        team = dict(_team(0, "AAA"), stats=[])
        self.assertEqual(team_page.four_factors_card({"games": []}, team, [team], 2031), "")


class TestFranchiseArc(unittest.TestCase):
    def _data_and_teams(self):
        seasons = []
        for s, w, l, prw in ((2029, 30, 15, 1), (2030, 38, 7, 2), (2031, 0, 0, -1)):
            seasons.append({"season": s, "won": w, "lost": l, "playoffRoundsWon": prw})
        me = dict(_team(2, "CAM"), seasons=seasons, stats=[])
        other = dict(_team(4, "TOR"), seasons=[
            {"season": 2029, "won": 15, "lost": 30, "playoffRoundsWon": -1},
            {"season": 2030, "won": 7, "lost": 38, "playoffRoundsWon": 1},
        ], stats=[])
        data = {
            "gameAttributes": {"season": 2031},
            "teams": [me, other],
            "playoffSeries": [_playoff_series(2029, 2, 4, 1, 4),
                              _playoff_series(2030, 2, 4, 4, 0)],
            "events": [
                {"type": "trade", "season": 2029, "tids": [2, 4], "pids": [7, 8]},
                {"type": "teamExpansion", "season": 2028, "tids": [2]},
                {"type": "retired", "season": 2030, "pids": [55]},
            ],
            "players": [
                {"pid": 55, "firstName": "Old", "lastName": "Legend", "tid": -3,
                 "retiredYear": 2030,
                 "stats": [{"season": 2029, "playoffs": False, "tid": 2, "gp": 40}]},
            ],
        }
        return data, [me, other], me

    def test_franchise_seasons_labels(self):
        data, teams, me = self._data_and_teams()
        rows = team_page.franchise_seasons(me, data, teams)
        self.assertEqual([r["season"] for r in rows], [2029, 2030])  # 0-0 preseason row skipped
        by_season = {r["season"]: r for r in rows}
        # 2029: playoffSeries says tid 4 won the final; CAM (prw=1) lost the Finals
        self.assertEqual(by_season[2029]["result"], "Lost Finals")
        self.assertEqual(by_season[2030]["result"], "Champion")
        self.assertEqual(by_season[2030]["finish"], 1)

    def test_history_page_renders_arc_table_and_scope(self):
        data, teams, me = self._data_and_teams()
        html = team_page.render_team_history_page(me, [], teams, 2031, 2026, data=data)
        self.assertIn("team-scope", html)
        self.assertIn("Franchise Arc", html)
        self.assertIn("Season Results", html)
        self.assertIn("TITLE", html)          # champion marker on the ribbon
        # P8: trade/retirement/expansion event pins are gone from the arc
        self.assertNotIn("arc-pin", html)
        self.assertNotIn("Joined the league", html)
        self.assertNotIn("retired", html)
        self.assertIn('href="test-cam-2-history.html"', html)  # subnav self-link

    def test_empty_franchise_shows_honest_empty_state(self):
        me = dict(_team(9, "ITH"), seasons=[{"season": 2031, "won": 0, "lost": 0}], stats=[])
        data = {"gameAttributes": {"season": 2031}, "teams": [me], "playoffSeries": [],
                "events": [], "players": []}
        html = team_page.render_team_history_page(me, [], [me], 2031, 2026, data=data)
        self.assertIn("No completed seasons yet", html)


class TestImmersionAndPolish(unittest.TestCase):
    def test_scope_wrapper_stripe_and_subnav_on_all_pages(self):
        team = dict(_team(0, "AAA"), seasons=[], stats=[])
        teams = [team]
        pages = [
            lg.render_team_roster_page(team, [], teams, 2031, 2026),
            lg.render_team_games_page(team, [], teams, 2031, 2026),
            lg.render_team_finances_page(team, [], teams, 2031, 2026),
            team_page.render_team_history_page(team, [], teams, 2031, 2026),
        ]
        for html in pages:
            self.assertIn('class="team-scope"', html)
            self.assertIn("--team-primary:", html)
            self.assertIn("tm-stripe", html)
            self.assertIn("tm-watermark", html)
            self.assertIn(">History</a>", html)  # 4th subnav entry

    def test_zero_gp_rows_shown_by_default_with_hide_toggle(self):
        roster = [
            _player(1, "Played", "Games", stats=[_stat_row()]),
            _player(2, "Never", "Played", stats=[]),
        ]
        html = team_page.roster_tabs(roster, 2031, 2026, "../", {}, None)
        # P8: inactive players are visible by default — the checkbox starts checked
        self.assertIn("data-toggle-inactive checked", html)
        self.assertIn("1 player with 0 GP", html)
        self.assertNotIn("hidden</label>", html)
        self.assertEqual(html.count('<tr class="inactive-row">'), 2)  # stats + advanced

    def test_all_zero_gp_roster_shows_everyone(self):
        roster = [_player(1, "Rookie", "One", stats=[]), _player(2, "Rookie", "Two", stats=[])]
        html = team_page.roster_tabs(roster, 2031, 2026, "../", {}, None)
        self.assertNotIn("data-toggle-inactive", html)
        self.assertNotIn("inactive-row", html)

    def test_finances_page_has_no_orphan_owed_payroll_heading(self):
        team = dict(_team(0, "AAA"), seasons=[], stats=[])
        html = lg.render_team_finances_page(team, [], [team], 2031, 2026)
        self.assertNotIn("block-title", html)
        self.assertIn("<h2>Salaries</h2>", html)

    def test_cap_sheet_tiles_have_explainers(self):
        # what the old Luxury Tax card became: there is no tax to report, so the
        # card reports payroll against the league-average line instead.
        tfin = {"payroll": 110000.0, "cap": 100000.0, "cap_room": -10000.0, "over_cap": False}
        data = {"gameAttributes": {"salaryCap": 100000, "salaryCapType": "none",
                                   "minContract": 1000, "maxRosterSize": 12}}
        html = team_page.cap_sheet_card(tfin, data, 2004, 12, {"teams": {}})
        self.assertIn("Cap Sheet", html)
        self.assertIn("has-tip", html)
        self.assertIn('title="', html)
        self.assertNotIn("Luxury tax", html)

    def test_team_color_ramp_is_deterministic_and_distinct(self):
        ramp1 = team_page.team_color_ramp(2, 8)
        ramp2 = team_page.team_color_ramp(2, 8)
        self.assertEqual(ramp1, ramp2)
        self.assertEqual(len(set(ramp1)), 8)

    def test_starting_five_court_is_gone_from_the_roster_page(self):
        team = dict(_team(0, "AAA"), seasons=[], stats=[])
        html = lg.render_team_roster_page(team, [_player(1, "Point", "Guard")], [team], 2031, 2026)
        self.assertNotIn("sfive", html)
        self.assertNotIn("Starting Five", html)
        self.assertIn("Depth Chart", html)  # the card-based depth chart stays the anchor


class TestFinanceDisplay(unittest.TestCase):
    """New model: net revenue is the whole next-season budget — no carried cash,
    and with an uncapped league there is no luxury tax to net out either."""

    def _rules_data(self, season=2031):
        """A 10-team, 36-game uncapped league, shaped like the real export."""
        teams = [_team(tid, "T%02d" % tid) for tid in range(10)]
        return {
            "gameAttributes": {"season": season, "numGames": 36, "salaryCap": 100000,
                               "salaryCapType": "none", "minContract": 1000,
                               "maxRosterSize": 12},
            "teams": teams,
        }

    def _league(self):
        teams = [
            {"tid": 0, "abbrev": "AAA", "region": "City", "name": "AAA",
             "seasons": [{"season": 2031, "won": 20, "lost": 16}]},
            {"tid": 1, "abbrev": "BBB", "region": "City", "name": "BBB",
             "seasons": [{"season": 2031, "won": 6, "lost": 30}]},
        ]
        players = [
            {"pid": 1, "firstName": "P", "lastName": "0", "tid": 0,
             "contract": {"amount": 120000, "exp": 2032}, "ratings": [{"season": 2031, "ovr": 60}]},
            {"pid": 2, "firstName": "P", "lastName": "1", "tid": 1,
             "contract": {"amount": 40000, "exp": 2032}, "ratings": [{"season": 2031, "ovr": 60}]},
        ]
        data = {"teams": teams, "players": players, "playoffSeries": [], "releasedPlayers": []}
        return lg.compute_league_finances(data, teams, players, 2031, odds={})

    def test_money_label_helper_renders_real_figures(self):
        # The assertions below are formatted by the page's own _fin_mil, so pin it:
        # a formatter that returned "" would make every one of them vacuous.
        self.assertEqual(_mil(5000), "$5M")
        self.assertEqual(_mil(2500), "$2.5M")
        self.assertEqual(_mil(lg.FIN_PER_WIN), "$%gM" % (lg.FIN_PER_WIN / 1000))

    def test_ledger_presents_budget_not_cash(self):
        lf = self._league()
        html = team_page.finance_ledger_card(lf["teams"][0], 2032, lf["cap"])
        self.assertNotIn("League share", html)  # P8: no flat share row
        self.assertIn("Win payouts", html)
        self.assertIn(f"({_mil(lg.FIN_PER_WIN)} × W)", html)  # per-win rate, exact label
        self.assertIn("Postseason", html)
        self.assertIn("2032 net revenue", html)
        self.assertIn("Season balance", html)
        self.assertIn("Committed 2032 payroll", html)
        self.assertIn("Spendable in 2032", html)
        self.assertNotIn("Cash on hand", html)
        self.assertNotIn("Starting balance", html)
        self.assertNotIn("Luxury tax", html)    # no tax exists in an uncapped league

    def test_ledger_money_is_wins_times_the_per_win_rate(self):
        lf = self._league()
        rich, poor = lf["teams"][0], lf["teams"][1]
        # No appearance money and no tax pool: revenue is wins × the per-win rate.
        self.assertAlmostEqual(rich["net_revenue_proj"], lg.FIN_PER_WIN * 20)
        self.assertAlmostEqual(rich["surplus_next"], lg.FIN_PER_WIN * 20 - 120000)
        self.assertAlmostEqual(poor["net_revenue_proj"], lg.FIN_PER_WIN * 6)
        self.assertAlmostEqual(poor["surplus_next"], lg.FIN_PER_WIN * 6 - 40000)
        # a team that outspends what it wins reads red on the spendable tile
        self.assertIn("delta-down", team_page.finance_ledger_card(rich, 2032, lf["cap"]))

    def test_hero_chip_shows_payroll_against_the_line(self):
        lf = self._league()
        rich, poor = lf["teams"][0], lf["teams"][1]
        html = team_page.hero_cap_chip(rich, lg.FIN_TARGET_PAYROLL, 2031)
        self.assertIn("2031 payroll", html)
        self.assertIn("Over the cap by", html)
        self.assertIn("delta-down", html)
        self.assertNotIn("Cash on hand", html)
        under = team_page.hero_cap_chip(poor, lg.FIN_TARGET_PAYROLL, 2031)
        self.assertIn("Cap space", under)
        self.assertIn("delta-up", under)

    def test_rules_card_states_the_new_numbers(self):
        html = team_page.finance_rules_card(self._rules_data(), 2031)
        self.assertNotIn("League share", html)  # P8: no flat share
        self.assertIn(f"+{_mil(lg.FIN_PER_WIN)}", html)        # per win
        self.assertIn(f"+{_mil(lg.FIN_PLAYOFF)}", html)        # berth
        self.assertIn(f"+{_mil(lg.FIN_PLAYOFF_WIN)}", html)    # each playoff win
        self.assertIn(f"+{_mil(lg.FIN_FINALS)}", html)         # finals
        self.assertIn(f"+{_mil(lg.FIN_CHAMP)}", html)          # title
        stacked = lg.FIN_PLAYOFF + 6 * lg.FIN_PLAYOFF_WIN + lg.FIN_FINALS + lg.FIN_CHAMP
        self.assertIn(f"+{_mil(stacked)}", html)  # champion's stacked bonus
        # 36 games × 10 teams / 2 = 180 wins shared out, plus the postseason pool
        self.assertIn(_mil(lg.FIN_TARGET_PAYROLL), html)  # league-average budget
        self.assertIn("No salary cap and no luxury tax.", html)
        self.assertNotIn("$75", html)   # no starting cash
        self.assertNotIn("carried cash", html.replace("no carried cash", ""))


if __name__ == "__main__":
    unittest.main()
