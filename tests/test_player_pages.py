"""Regression tests for the unified per-player page (scripts/smp/pages/player.py)."""

import os
import sys
import unittest


_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_HERE)
_SCRIPTS = os.path.join(_REPO, "scripts")
if _SCRIPTS not in sys.path:
    sys.path.insert(0, _SCRIPTS)

from smp.pages import player as pp  # noqa: E402
import league_generator as lg  # noqa: E402


def _team(tid, abbrev, region="Test", name=None):
    return {"tid": tid, "abbrev": abbrev, "region": region, "name": name or abbrev}


TEAMS = [_team(0, "AAA", region="Alpha", name="Aces"), _team(1, "BBB", region="Beta", name="Bears")]


def _stat_row(season=2030, tid=0, gp=10, pts=300, playoffs=False, **extra):
    row = {
        "season": season, "tid": tid, "playoffs": playoffs, "gp": gp, "gs": gp,
        "min": 30.0 * gp, "fg": 100, "fga": 200, "tp": 20, "tpa": 60,
        "ft": 50, "fta": 60, "orb": 20, "drb": 60, "ast": 40, "tov": 20,
        "stl": 10, "blk": 8, "ba": 2, "pf": 20, "pts": pts,
        "fgAtRim": 40, "fgaAtRim": 60, "fgLowPost": 20, "fgaLowPost": 40,
        "fgMidRange": 20, "fgaMidRange": 40, "dd": 3, "td": 1, "qd": 0, "fxf": 0,
        "per": 18.0, "ewa": 4.0, "ows": 2.0, "dws": 1.5, "vorp": 2.5,
        "obpm": 2.0, "dbpm": 1.0, "orbp": 5.0, "drbp": 15.0, "trbp": 10.0,
        "astp": 20.0, "stlp": 1.5, "blkp": 2.0, "usgp": 25.0,
        "pm100": 3.0, "onOff100": 4.0, "ortg": 115.0, "drtg": 108.0,
    }
    row.update(extra)
    return row


def _player(pid, first="Test", last="Player", tid=0, with_stats=True, **extra):
    player = {
        "pid": pid,
        "firstName": first,
        "lastName": last,
        "tid": tid,
        "retiredYear": None,
        "born": {"year": 2005, "loc": "Testville"},
        "jerseyNumber": 23,
        "contract": {"amount": 20000, "exp": 2032},
        "salaries": [
            {"season": 2030, "amount": 15000},
            {"season": 2031, "amount": 20000},
            {"season": 2032, "amount": 20000},
        ],
        "statsTids": [-7, 0, 1] if with_stats else [],
        "ratings": [
            {"season": 2030, "pos": "SG", "ovr": 60, "pot": 66, "skills": ["3", "Dp"]},
            {"season": 2031, "pos": "SG", "ovr": 63, "pot": 66, "skills": ["3", "Dp"]},
        ],
        "stats": [_stat_row()] if with_stats else [],
    }
    player.update(extra)
    return player


def _log_entry(day=3, pts=25, min_=32.0):
    return {
        "day": day, "gid": 100 + day, "tid": 0, "opp_tid": 1, "home": True,
        "team_pts": 110, "opp_pts": 100, "overtimes": 0, "playoffs": False,
        "box": {
            "pid": 1, "min": min_, "fg": 9, "fga": 18, "tp": 3, "tpa": 7,
            "ft": 4, "fta": 5, "orb": 1, "drb": 5, "ast": 6, "tov": 2,
            "stl": 1, "blk": 1, "pf": 2, "pts": pts, "pm": 8,
        },
    }


class TestUnifiedPage(unittest.TestCase):
    def test_returns_unified_page_plus_redirect_stubs(self):
        pages = pp.render_player_pages(_player(1), TEAMS, 2031, 2026, log_entries=[_log_entry()])
        self.assertEqual(set(pages), {"", "-stats", "-log", "-ratings"})
        unified = pages[""]
        for section_id in ("overview", "stats", "log", "ratings", "contract"):
            self.assertIn(f'id="{section_id}"', unified)
        self.assertIn("data-player-rail", unified)
        # Old sub-URLs forward to the unified page's anchors.
        slug = lg.player_slug(_player(1))
        self.assertIn(f"url={slug}.html#stats", pages["-stats"])
        self.assertIn(f"url={slug}.html#log", pages["-log"])
        self.assertIn(f"url={slug}.html#ratings", pages["-ratings"])
        self.assertIn("http-equiv=\"refresh\"", pages["-stats"])

    def test_rail_omits_sections_without_data(self):
        pages = pp.render_player_pages(_player(2, with_stats=False), TEAMS, 2031, 2026)
        unified = pages[""]
        self.assertNotIn('href="#stats"', unified)
        self.assertNotIn('href="#log"', unified)
        self.assertIn('href="#ratings"', unified)
        self.assertIn('href="#contract"', unified)
        # Stubs still exist so stale URLs never 404.
        self.assertIn("-stats", pages)

    def test_facade_exports_render_player_pages(self):
        self.assertIs(lg.render_player_pages, pp.render_player_pages)


class TestTradingCard(unittest.TestCase):
    def test_team_card_carries_identity_vars_and_career_dots(self):
        teams_by_tid = {t["tid"]: t for t in TEAMS}
        html = pp.trading_card_html(_player(3), teams_by_tid, 2031)
        self.assertIn("--team-primary:", html)
        self.assertNotIn("player-card--fa", html)
        self.assertIn("player-card-num", html)  # corner jersey number
        self.assertIn('title="Three-point shooter"', html)  # skill chip
        self.assertIn("player-card-plate", html)  # position/team nameplate
        self.assertIn("plate-pos", html)
        # statsTids [-7, 0, 1] -> two real franchises, current one ringed.
        n_dots = html.count('class="career-dot"') + html.count('class="career-dot career-dot--now"')
        self.assertEqual(n_dots, 2)
        self.assertIn("career-dot career-dot--now", html)

    def test_stat_tiles_have_counting_row_and_shooting_row(self):
        teams_by_tid = {t["tid"]: t for t in TEAMS}
        player = _player(30)
        html = pp.trading_card_html(player, teams_by_tid, 2031)
        self.assertIn("player-card-tiles", html)
        self.assertIn("card-tile-row--counting", html)
        self.assertIn("card-tile-row--shooting", html)
        for label in ("PTS", "REB", "AST", "STL", "BLK", "FG%", "3P%", "FT%", "FPTS"):
            self.assertIn(f">{label}<", html)
        self.assertIn(">30.0<", html)  # 300 pts / 10 gp
        self.assertIn(">1.0<", html)   # 10 stl / 10 gp
        self.assertIn(">0.8<", html)   # 8 blk / 10 gp
        self.assertIn(">50.0<", html)  # 100/200 FG
        self.assertIn(">33.3<", html)  # 20/60 3P
        self.assertIn(">83.3<", html)  # 50/60 FT
        self.assertIn("2030 per game", html)

    def test_hero_fpts_average_keeps_one_decimal(self):
        teams_by_tid = {t["tid"]: t for t in TEAMS}
        player = _player(33)
        html = pp.trading_card_html(player, teams_by_tid, 2031)
        # 502 fantasy pts / 10 gp -> 50.2 (one decimal on the hero card only).
        expected = lg.fantasy_pts(player["stats"][0]) / 10.0
        self.assertIn(f">{expected:.1f}<", html)

    def test_no_games_played_renders_no_tiles(self):
        teams_by_tid = {t["tid"]: t for t in TEAMS}
        html = pp.trading_card_html(_player(31, with_stats=False), teams_by_tid, 2031)
        self.assertNotIn("player-card-tiles", html)

    def test_free_agent_gets_neutral_silver_card_with_asking_price(self):
        teams_by_tid = {t["tid"]: t for t in TEAMS}
        player = _player(4, tid=-1)
        html = pp.trading_card_html(player, teams_by_tid, 2031)
        # The card section itself carries no team style attr; silver comes from CSS.
        self.assertIn('<section class="player-card player-card--fa">', html)
        self.assertIn("Free Agent", html)
        # Asking-price plate quotes the player's own priced contract.
        self.assertIn("Asking price", html)
        self.assertIn(lg.fmt_money(pp.fa_asking_price(player, 2031)), html)
        self.assertIn("$20M", html)  # contract.amount, not a re-derived curve value

    def test_rostered_card_has_no_asking_price(self):
        teams_by_tid = {t["tid"]: t for t in TEAMS}
        html = pp.trading_card_html(_player(32), teams_by_tid, 2031)
        self.assertNotIn("Asking price", html)


class TestHeroHonors(unittest.TestCase):
    AWARDS = [
        {"season": 2027, "type": "Most Valuable Player"},
        {"season": 2028, "type": "Most Valuable Player"},
        {"season": 2028, "type": "Won Championship"},
        {"season": 2028, "type": "First Team All-League"},
        {"season": 2028, "type": "League Scoring Leader"},
    ]

    def test_hero_card_carries_compact_crest_strip_with_counts(self):
        teams_by_tid = {t["tid"]: t for t in TEAMS}
        html = pp.trading_card_html(_player(40, awards=self.AWARDS), teams_by_tid, 2031)
        self.assertIn("player-card-honors", html)
        self.assertIn("card-honor--gold", html)  # champion/MVP tier
        self.assertIn("×2", html)  # MVP twice
        self.assertIn("All-League 1st", html)
        # Champion (award order) leads the strip; stat titles stay off the hero.
        self.assertLess(html.index("Champion"), html.index("MVP"))
        self.assertNotIn("Scoring Leader", html)

    def test_no_awards_means_no_strip(self):
        teams_by_tid = {t["tid"]: t for t in TEAMS}
        self.assertNotIn("player-card-honors", pp.trading_card_html(_player(41), teams_by_tid, 2031))


class TestTrophyCase(unittest.TestCase):
    def test_groups_repeat_awards_with_counts(self):
        player = _player(5, awards=[
            {"season": 2027, "type": "Most Valuable Player"},
            {"season": 2028, "type": "Most Valuable Player"},
            {"season": 2028, "type": "Won Championship"},
            {"season": 2028, "type": "League Scoring Leader"},
        ])
        html = pp.trophy_case_html(player)
        self.assertIn("×2", html)
        self.assertIn("Most Valuable Player", html)  # crest aria/title
        self.assertIn("<svg", html)  # identity.crest_svg shelves, not a plain list
        self.assertIn("Scoring Leader", html)  # unmapped types become text chips
        self.assertIn("4 awards", html)

    def test_no_awards_renders_nothing(self):
        self.assertEqual(pp.trophy_case_html(_player(6)), "")


class TestFantasyPoints(unittest.TestCase):
    def test_summary_and_per_game_tables_have_integer_fpts_column(self):
        teams_by_tid = {t["tid"]: t for t in TEAMS}
        player = _player(7)
        summary = pp.player_summary_rows(player, teams_by_tid, 2030, 2026)
        self.assertIn(">FPTS<", summary)
        table = pp.per_game_table(player, player["stats"], teams_by_tid, "../", "Per Game", "t7")
        self.assertIn(">FPTS<", table)
        # Season aggregate: fantasy total / gp, shown as an integer.
        expected = lg.fantasy_pts(player["stats"][0]) / 10.0
        self.assertIn(f">{expected:.0f}<", table)
        self.assertNotIn(f">{expected:.1f}<", table)

    def test_integer_fpts_never_renders_minus_zero(self):
        self.assertEqual(pp._fmt_int(-0.4), "0")
        self.assertEqual(pp._fmt_int(-0.5), "0")
        self.assertEqual(pp._fmt_int(-1.6), "-2")
        self.assertEqual(pp._fmt_int(50.2), "50")

    def test_game_log_has_integer_fpts_and_no_gmsc(self):
        teams_by_tid = {t["tid"]: t for t in TEAMS}
        entry = _log_entry()
        html = pp.game_log_table(_player(8), [entry], teams_by_tid, 2031, "../")
        self.assertIn(">FPTS<", html)
        self.assertNotIn("GmSc", html)
        expected = lg.fantasy_pts(entry["box"])
        self.assertIn(f">{expected:.0f}<", html)


class TestLedLeague(unittest.TestCase):
    def _data(self, pts_leader):
        return {"seasonLeaders": [{"season": 2030, "regularSeason": {"pts": pts_leader}}]}

    def test_matching_value_gets_gold_star(self):
        teams_by_tid = {t["tid"]: t for t in TEAMS}
        player = _player(9)  # 300 pts / 10 gp = 30.0 per game
        led = pp._led_index(self._data(30.0))
        html = pp.per_game_table(player, player["stats"], teams_by_tid, "../", "Per Game", "t9", led=led)
        self.assertIn("led-league", html)
        self.assertIn("Led the league in scoring", html)
        self.assertIn("★", html)

    def test_non_leader_untouched(self):
        teams_by_tid = {t["tid"]: t for t in TEAMS}
        player = _player(10)
        led = pp._led_index(self._data(31.5))
        html = pp.per_game_table(player, player["stats"], teams_by_tid, "../", "Per Game", "t10", led=led)
        self.assertNotIn("led-league", html)

    def test_no_data_means_no_gold(self):
        self.assertEqual(pp._led_index(None), {})


class TestShotDiet(unittest.TestCase):
    def test_stacked_bar_from_box_scores(self):
        player = _player(11)
        data = {
            "games": [{
                "season": 2030,
                "teams": [{"players": [{
                    "pid": 11, "fgAtRim": 4, "fgaAtRim": 6, "fgLowPost": 1,
                    "fgaLowPost": 2, "fgMidRange": 2, "fgaMidRange": 5,
                    "tp": 1, "tpa": 4,
                }]}],
            }],
        }
        html = pp.shot_diet_html(player, data, 2026)
        self.assertIn("shotdiet-bar", html)
        self.assertIn("<svg", html)
        self.assertIn("At Rim: 4/6", html)  # hover title carries makes/attempts
        self.assertIn("17 FGA", html)

    def test_no_data_renders_nothing(self):
        self.assertEqual(pp.shot_diet_html(_player(12), None, 2026), "")
        self.assertEqual(pp.shot_diet_html(_player(13), {"games": []}, 2026), "")


class TestContractSection(unittest.TestCase):
    def test_salary_table_current_first_then_guaranteed_then_history(self):
        html = pp.salary_history_html(_player(14), 2031)
        # Current season leads (highlighted), guaranteed years ascend, the
        # UFA row (exp 2032 -> 2033) follows, then history newest-first.
        pos_2031 = html.index(">2031<")
        pos_2032 = html.index(">2032<")
        ufa_pos = html.index("UFA")
        pos_2030 = html.index(">2030<")
        self.assertLess(pos_2031, pos_2032)
        self.assertLess(pos_2032, ufa_pos)
        self.assertLess(ufa_pos, pos_2030)
        self.assertIn("salary-current", html)
        self.assertIn("guaranteed", html)
        self.assertIn("total-row", html)

    def test_salary_table_spans_through_season_plus_four(self):
        # Contract through 2038: rows stop at 2035, no UFA row (2039 > 2035).
        player = _player(19, contract={"amount": 20000, "exp": 2038})
        html = pp.salary_history_html(player, 2031)
        self.assertIn(">2035<", html)
        self.assertNotIn(">2036<", html)
        self.assertNotIn(">2037<", html)
        self.assertNotIn(">2038<", html)
        self.assertNotIn("UFA", html)
        # Total covers only the seasons shown: 2030 + 2031 + 2032..2035 filled.
        shown_total = 15000 + 20000 + 20000 + 20000 * 3
        self.assertIn(lg.fmt_money(shown_total), html)

    def test_free_agent_has_no_ufa_row_and_no_future_fill(self):
        html = pp.salary_history_html(_player(15, tid=-1), 2031)
        self.assertNotIn("UFA", html)
        self.assertNotIn("guaranteed", html)

    def test_contract_summary_labels_fa_asking_price(self):
        self.assertIn("Asking price", pp.contract_summary_html(_player(16, tid=-1), 2031))
        self.assertIn("Current deal", pp.contract_summary_html(_player(17), 2031))

    def test_fa_asking_price_is_the_priced_contract_not_a_curve(self):
        # scripts/price_contracts.py writes the ask into contract.amount; the page
        # must quote that number, or the site disagrees with the game.
        player = _player(19, tid=-1, contract={"amount": 24000, "exp": 2034})
        self.assertEqual(pp.fa_asking_price(player, 2031), 24000)
        html = pp.contract_summary_html(player, 2031)
        self.assertIn("$24M/yr", html)
        self.assertIn("thru 2034", html)

    def test_fa_asking_price_falls_back_to_the_curve_when_unpriced(self):
        player = _player(20, tid=-1, contract={})
        self.assertGreater(pp.fa_asking_price(player, 2031), 0)
        self.assertEqual(pp.fa_asking_term(player, 2031), "")

    def test_ovr_delta_carries_vs_last_season_tooltip(self):
        html = pp.player_ratings_html(_player(18), 2031)
        self.assertIn("Change vs last season", html)
        self.assertIn("vs last season", html)


class TestRatingPercentiles(unittest.TestCase):
    """Every rating is ranked against the same reference pool: the top 120 by ovr."""

    @staticmethod
    def _pool(n=200):
        # ovr/pot climb with pid, so the pool's top 120 is pids 80..199 and the
        # percentile of any value is predictable.
        return [
            {
                "pid": pid, "firstName": "P", "lastName": str(pid), "tid": -1,
                "retiredYear": None, "born": {"year": 2005},
                "ratings": [{"season": 2031, "pos": "SG", "ovr": pid % 100,
                             "pot": pid % 100, "drb": pid % 100}],
                "stats": [],
            }
            for pid in range(n)
        ]

    def test_ramps_cover_exactly_the_reference_pool(self):
        from smp.core import RATING_POOL_SIZE, rating_percentile_ramps
        ramps = rating_percentile_ramps(self._pool(), 2031)
        self.assertEqual(len(ramps["ovr"]), RATING_POOL_SIZE)
        self.assertIn("drb", ramps)

    def test_pool_smaller_than_120_uses_everyone(self):
        from smp.core import rating_percentile_ramps
        ramps = rating_percentile_ramps(self._pool(40), 2031)
        self.assertEqual(len(ramps["ovr"]), 40)

    def test_pct_rank_is_the_tied_run_midpoint(self):
        from smp.core import pct_rank
        self.assertEqual(pct_rank(5, [1, 2, 3, 4]), 100.0)     # above everyone
        self.assertEqual(pct_rank(0, [1, 2, 3, 4]), 0.0)       # below everyone
        self.assertEqual(pct_rank(2, [1, 2, 2, 4]), 50.0)      # midpoint of the tie
        self.assertIsNone(pct_rank(2, [1]))                    # no distribution
        self.assertIsNone(pct_rank(None, [1, 2, 3]))

    def test_ratings_card_shows_a_percentile_chip_per_rating(self):
        from smp.core import rating_percentile_ramps
        ramps = rating_percentile_ramps(self._pool(), 2031)
        player = _player(21, ratings=[{"season": 2031, "pos": "SG", "ovr": 90, "pot": 92, "drb": 90}])
        html = pp.player_ratings_html(player, 2031, ramps)
        self.assertIn("rating-pct", html)
        self.assertIn("percentile of the top 120 players", html)
        self.assertIn("chip = percentile of the top 120", html)
        # One chip per rating both the player and the reference pool carry: this
        # synthetic pool rates ovr/pot/drb, so the other 14 rows stay bare.
        self.assertEqual(html.count('class="rating-pct"'), 3)
        # ovr 90 tops a pool whose best is 99 -> high but not perfect.
        self.assertIn("percentile", html)

    def test_no_reference_pool_renders_the_card_unchanged(self):
        html = pp.player_ratings_html(_player(22), 2031)
        self.assertNotIn("rating-pct", html)
        self.assertNotIn("percentile", html)


class TestRatingDeltas(unittest.TestCase):
    def test_ratings_card_shows_green_deltas_for_all_rated_keys(self):
        ratings = [
            {"season": 2030, "pos": "SG", "ovr": 60, "pot": 66, "hgt": 50, "stre": 40, "tp": 70},
            {"season": 2031, "pos": "SG", "ovr": 63, "pot": 66, "hgt": 50, "stre": 44, "tp": 68},
        ]
        html = pp.player_ratings_html(_player(20, ratings=ratings), 2031)
        self.assertIn('delta-up">(+3)', html)   # ovr 60 -> 63
        self.assertIn('delta-up">(+4)', html)   # stre 40 -> 44
        self.assertIn('delta-down">(-2)', html)  # tp 70 -> 68

    def test_rookie_single_season_shows_no_delta(self):
        ratings = [{"season": 2031, "pos": "SG", "ovr": 55, "pot": 70, "stre": 40}]
        html = pp.player_ratings_html(_player(21, ratings=ratings), 2031)
        self.assertNotIn("delta-up", html)
        self.assertNotIn("delta-down", html)


class TestNoRatingTrajectories(unittest.TestCase):
    def test_unified_page_has_no_trajectory_grid(self):
        pages = pp.render_player_pages(_player(22), TEAMS, 2031, 2026, log_entries=[_log_entry()])
        self.assertNotIn("Rating Trajectories", pages[""])
        self.assertNotIn("data-subrating-grid", pages[""])


class TestPageComposition(unittest.TestCase):
    def test_overview_splits_into_main_and_sidebar_with_section_heads(self):
        pages = pp.render_player_pages(_player(23), TEAMS, 2031, 2026, log_entries=[_log_entry()])
        unified = pages[""]
        self.assertIn("overview-grid", unified)
        self.assertIn('class="ov-main"', unified)
        self.assertIn('class="ov-side"', unified)
        # Identity vars scope the whole page, not just the hero card.
        self.assertIn('class="player-scope"', unified)
        # Landmark heads for the anchored sections.
        for head in ("Stats", "Game Log", "Ratings", "Contract &amp; Injuries"):
            self.assertIn(f"<h2>{head}</h2>", unified)

    def test_free_agent_page_uses_neutral_scope(self):
        pages = pp.render_player_pages(_player(24, tid=-1), TEAMS, 2031, 2026)
        self.assertIn("player-scope player-scope--fa", pages[""])

    def test_summary_is_a_tile_strip_with_career_line(self):
        teams_by_tid = {t["tid"]: t for t in TEAMS}
        html = pp.player_summary_rows(_player(25), teams_by_tid, 2030, 2026)
        self.assertIn("sumtile-grid", html)
        self.assertIn("sumtile-career", html)
        self.assertIn(">PTS<", html)
        self.assertIn(">30.0<", html)  # 300 pts / 10 gp
        # No stats at all -> no card.
        self.assertEqual(pp.player_summary_rows(_player(26, with_stats=False), teams_by_tid, 2030, 2026), "")

    def test_per_game_table_defaults_to_key_columns(self):
        teams_by_tid = {t["tid"]: t for t in TEAMS}
        player = _player(27)
        html = pp.per_game_table(player, player["stats"], teams_by_tid, "../", "Per Game", "t27")
        self.assertIn('data-colgroup-toggle="t27"', html)
        self.assertIn('data-colgroup-default="key"', html)
        self.assertIn('data-colgroup="shooting"', html)

    def test_shot_diet_share_has_one_decimal(self):
        player = _player(28)
        data = {
            "games": [{
                "season": 2030,
                "teams": [{"players": [{
                    "pid": 28, "fgAtRim": 4, "fgaAtRim": 6, "fgLowPost": 1,
                    "fgaLowPost": 2, "fgMidRange": 2, "fgaMidRange": 5,
                    "tp": 1, "tpa": 4,
                }]}],
            }],
        }
        html = pp.shot_diet_html(player, data, 2026)
        self.assertIn("35.3% of attempts", html)  # 6/17 at the rim, one decimal


if __name__ == "__main__":
    unittest.main()
