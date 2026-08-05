"""Tests for scripts/smp/derived.py and scripts/smp/appdata.py."""

import json
import math
import os
import sys
import tempfile
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_HERE)
_SCRIPTS = os.path.join(_REPO, "scripts")
if _SCRIPTS not in sys.path:
    sys.path.insert(0, _SCRIPTS)

from smp import appdata, derived  # noqa: E402
from smp.core import ALL_PLAYERS_BY_PID, RATING_LABELS  # noqa: E402
from smp.finance import FIN_CAP  # noqa: E402
from smp.simmodel import (  # noqa: E402
    ROTATION_SLOTS,
    REPLACEMENT_OVR,
    SIM_HCA,
    SIM_LOGISTIC_K,
    game_win_prob,
    league_bench_ovrs,
    player_game_impact,
    projected_margin,
    projected_spread,
    rotation_weight,
    sim_client_inputs,
    sim_strengths,
    simulate_league,
)


# ---------------------------------------------------------------------------
# fantasy_pts
# ---------------------------------------------------------------------------

class TestFantasyPts(unittest.TestCase):
    def test_hand_computed_example(self):
        # 30 pts / 10 reb / 5 ast on 12-20 FG, 3-5 3P, 3-4 FT, 2 TOV, 1 STL, 1 BLK:
        #   PTS 30 + 3PM 3 + FGM 24 - FGA 20 + FTM 3 - FTA 4 + REB 10
        #   + AST 10 + STL 4 + BLK 4 - TOV 4 = 60
        row = {
            "pts": 30, "fg": 12, "fga": 20, "tp": 3, "tpa": 5, "ft": 3, "fta": 4,
            "orb": 3, "drb": 7, "ast": 5, "stl": 1, "blk": 1, "tov": 2,
        }
        self.assertEqual(derived.fantasy_pts(row), 60.0)

    def test_accepts_trb_style_rows(self):
        # Season-aggregate style rows that carry trb instead of orb/drb split.
        row = {
            "pts": 30, "fg": 12, "fga": 20, "tp": 3, "ft": 3, "fta": 4,
            "trb": 10, "ast": 5, "stl": 1, "blk": 1, "tov": 2,
        }
        self.assertEqual(derived.fantasy_pts(row), 60.0)

    def test_missing_inputs_return_none(self):
        self.assertIsNone(derived.fantasy_pts(None))
        self.assertIsNone(derived.fantasy_pts({}))
        self.assertIsNone(derived.fantasy_pts({"pts": 10, "fg": 4}))  # no fga


# ---------------------------------------------------------------------------
# four_factors
# ---------------------------------------------------------------------------

class TestFourFactors(unittest.TestCase):
    def test_known_values(self):
        row = {
            "fg": 40, "tp": 10, "fga": 90, "tov": 15, "fta": 20, "ft": 16,
            "orb": 12, "drb": 33,
            "oppFg": 35, "oppTp": 8, "oppFga": 88, "oppTov": 12, "oppFta": 25,
            "oppFt": 18, "oppOrb": 10, "oppDrb": 30,
        }
        ff = derived.four_factors(row)
        self.assertAlmostEqual(ff["efg"], 100 * (40 + 5) / 90)          # 50.0
        self.assertAlmostEqual(ff["tov_pct"], 100 * 15 / (90 + 0.44 * 20 + 15))
        self.assertAlmostEqual(ff["orb_pct"], 100 * 12 / (12 + 30))
        self.assertAlmostEqual(ff["ft_rate"], 16 / 90)
        self.assertAlmostEqual(ff["opp_efg"], 100 * (35 + 4) / 88)
        self.assertAlmostEqual(ff["opp_tov_pct"], 100 * 12 / (88 + 0.44 * 25 + 12))
        self.assertAlmostEqual(ff["opp_orb_pct"], 100 * 10 / (10 + 33))
        self.assertAlmostEqual(ff["opp_ft_rate"], 18 / 88)

    def test_zero_denominators_yield_none(self):
        ff = derived.four_factors({"fg": 0, "fga": 0})
        self.assertIsNone(ff["efg"])
        self.assertIsNone(ff["ft_rate"])
        self.assertIsNone(ff["orb_pct"])


# ---------------------------------------------------------------------------
# drama_index
# ---------------------------------------------------------------------------

def _game(gid, home_qtrs, away_qtrs, overtimes=0, clutch=0):
    return {
        "gid": gid,
        "season": 2030,
        "overtimes": overtimes,
        "clutchPlays": ["play"] * clutch,
        "teams": [
            {"tid": 0, "pts": sum(home_qtrs), "ptsQtrs": list(home_qtrs)},
            {"tid": 1, "pts": sum(away_qtrs), "ptsQtrs": list(away_qtrs)},
        ],
    }


class TestDramaIndex(unittest.TestCase):
    def test_ot_comeback_beats_blowout(self):
        # Home trails by 20 after two quarters, forces OT, wins by 2.
        thriller = _game(1, [15, 20, 30, 25, 12], [30, 25, 20, 15, 10], overtimes=1, clutch=2)
        # 40-point wire-to-wire blowout: no OT, no comeback, no clutch plays.
        blowout = _game(2, [35, 30, 28, 27], [20, 20, 20, 20])
        hi = derived.drama_index(thriller)
        lo = derived.drama_index(blowout)
        self.assertGreater(hi, lo)
        self.assertGreater(hi, 50.0)
        self.assertLess(lo, 10.0)

    def test_comeback_size_from_quarter_margins(self):
        thriller = _game(1, [15, 20, 30, 25, 12], [30, 25, 20, 15, 10])
        self.assertEqual(derived.comeback_size(thriller), 20.0)

    def test_bounded_and_feats_counted(self):
        game = _game(3, [25, 25, 25, 26], [25, 25, 25, 25], overtimes=3, clutch=9)
        feats = {"3": [{"pid": 1}, {"pid": 2}, {"pid": 3}]}
        score = derived.drama_index(game, feats)
        self.assertLessEqual(score, 100.0)
        self.assertGreater(score, derived.drama_index(game))  # feats add drama

    def test_unfinished_game_scores_zero(self):
        self.assertEqual(derived.drama_index({"teams": [{"tid": 0}, {"tid": 1}]}), 0.0)


# ---------------------------------------------------------------------------
# led_league
# ---------------------------------------------------------------------------

class TestLedLeague(unittest.TestCase):
    def test_shape_and_values(self):
        data = {
            "seasonLeaders": [
                {"season": 2029, "regularSeason": {"pts": 31.2, "trb": 13.1, "ast": 10.4}},
                {"season": 2030, "regularSeason": {"pts": 33.0, "trb": 12.0, "ast": 9.8, "bad": "x"}},
            ]
        }
        led = derived.led_league(data)
        self.assertEqual(sorted(led.keys()), [2029, 2030])
        self.assertEqual(led[2030]["pts"], 33.0)
        self.assertNotIn("bad", led[2030])  # non-numeric values dropped
        marks = derived.led_league_stats(led, 2030, {"pts": 33.0, "ast": 5.0}, ["pts", "ast"])
        self.assertEqual(marks, {"pts"})

    def test_empty_export(self):
        self.assertEqual(derived.led_league({}), {})


# ---------------------------------------------------------------------------
# shot zones
# ---------------------------------------------------------------------------

class TestShotZones(unittest.TestCase):
    def test_aggregation_and_league_average(self):
        box = {"pid": 7, "fgAtRim": 4, "fgaAtRim": 5, "fgLowPost": 1, "fgaLowPost": 2,
               "fgMidRange": 2, "fgaMidRange": 6, "tp": 3, "tpa": 8}
        data = {"games": [
            {"season": 2030, "teams": [{"tid": 0, "players": [dict(box)]}, {"tid": 1, "players": []}]},
            {"season": 2030, "teams": [{"tid": 0, "players": [dict(box)]}, {"tid": 1, "players": []}]},
        ]}
        zones = derived.player_shot_zones(data, 7, 2030)
        self.assertEqual(zones["rim"]["fg"], 8)
        self.assertEqual(zones["rim"]["fga"], 10)
        self.assertAlmostEqual(zones["rim"]["pct"], 80.0)
        # The only shooter IS the league here, so lg_pct matches his pct.
        self.assertAlmostEqual(zones["rim"]["lg_pct"], 80.0)
        self.assertAlmostEqual(zones["three"]["pct"], 100 * 6 / 16)
        self.assertIsNone(derived.player_shot_zones(data, 7, 2029))  # no boxes that season
        self.assertIsNone(derived.player_shot_zones(data, 99, 2030))  # unknown pid


# ---------------------------------------------------------------------------
# app-data payload
# ---------------------------------------------------------------------------

_RATING_KEYS = list(RATING_LABELS)


def _rating_row(season, ovr, pot, pos="PG"):
    row = {"season": season, "pos": pos, "ovr": ovr, "pot": pot, "skills": []}
    for key in _RATING_KEYS:
        row[key] = 50
    return row


def _league_player(pid, tid, ovr, season=2030):
    return {
        "pid": pid,
        "firstName": "Player",
        "lastName": str(pid),
        "tid": tid,
        "retiredYear": None,
        "born": {"year": season - 25},
        "jerseyNumber": str(pid),
        "value": 40.0 + pid,
        "contract": {"amount": 10000 + 100 * pid, "exp": season + 2},
        "ratings": [_rating_row(season, ovr, ovr + 2)],
        "stats": [{
            "season": season - 1, "playoffs": False, "tid": tid, "gp": 10,
            "min": 300, "pts": 150, "fg": 60, "fga": 120, "tp": 10, "tpa": 30,
            "ft": 20, "fta": 25, "orb": 10, "drb": 40, "ast": 30, "stl": 8,
            "blk": 5, "tov": 12, "obpm": 1.0, "dbpm": 0.5, "ows": 1.5, "dws": 0.5,
        }],
    }


def _league_export():
    teams = []
    for tid, abbrev in enumerate(["AAA", "BBB", "CCC", "DDD"]):
        teams.append({
            "tid": tid,
            "abbrev": abbrev,
            "region": f"Region{tid}",
            "name": f"Name{tid}",
            "seasons": [{"season": 2029, "won": 20 + tid, "lost": 25 - tid}],
            "stats": [{"season": 2029, "playoffs": False, "gp": 45,
                       "pts": 45 * (110 + 2 * tid), "oppPts": 45 * 110}],
        })
    players = []
    pid = 0
    for tid in range(4):
        for _ in range(6):
            # team 3 gets the strongest roster, team 0 the weakest
            players.append(_league_player(pid, tid, 55 + 6 * tid))
            pid += 1
    return {
        # salaryCapType "none": SMP II is uncapped, so there is no cap figure and
        # no tax line to publish.
        "gameAttributes": {"season": 2030, "phase": 0, "numGames": 6,
                           "salaryCapType": "none"},
        "teams": teams,
        "players": players,
        "games": [],
        "seasonLeaders": [],
    }


def _completed_game(gid, day, home_tid, away_tid, home_pts, away_pts, season=2030):
    return {
        "gid": gid, "day": day, "season": season, "playoffs": False,
        "teams": [
            {"tid": home_tid, "pts": home_pts, "players": []},
            {"tid": away_tid, "pts": away_pts, "players": []},
        ],
    }


def _league_export_in_season():
    """The fresh fixture two game days in: completed 2030 games, 2030 team
    season/stat rows, and an exported schedule with remaining games."""
    data = _league_export()
    data["gameAttributes"]["phase"] = 1
    completed = [
        (1, 1, 0, 1, 100, 90),
        (2, 1, 2, 3, 110, 100),
        (3, 2, 0, 2, 95, 105),
        (4, 2, 1, 3, 101, 99),
    ]
    data["games"] = [
        _completed_game(gid, day, h, a, hp, ap) for gid, day, h, a, hp, ap in completed
    ]
    records = {0: (1, 1), 1: (1, 1), 2: (2, 0), 3: (0, 2)}
    totals = {0: (195, 195), 1: (191, 199), 2: (215, 195), 3: (199, 211)}
    for team in data["teams"]:
        tid = team["tid"]
        won, lost = records[tid]
        pts, opp = totals[tid]
        team["seasons"].append({"season": 2030, "won": won, "lost": lost})
        team["stats"].append({"season": 2030, "playoffs": False, "gp": 2,
                              "pts": pts, "oppPts": opp})
    remaining = [
        (5, 3, 1, 0), (6, 3, 3, 2), (7, 4, 2, 0), (8, 4, 3, 1),
    ]
    all_entries = [(gid, day, h, a) for gid, day, h, a, _, _ in completed] + remaining
    data["schedule"] = [
        {"gid": gid, "day": day, "season": 2030, "homeTid": h, "awayTid": a}
        for gid, day, h, a in all_entries
    ]
    return data


class TestAppData(unittest.TestCase):
    def setUp(self):
        ALL_PLAYERS_BY_PID.clear()

    def tearDown(self):
        ALL_PLAYERS_BY_PID.clear()

    def test_schema_keys_present(self):
        data = _league_export()
        app = appdata.build_app_data(data)
        self.assertEqual(sorted(app.keys()), ["finance", "players", "season", "sim", "teams", "ws_season"])
        self.assertEqual(app["season"], 2030)
        # phase 0 (preseason): the newest COMPLETED season is the previous one
        self.assertEqual(app["ws_season"], 2029)
        # Uncapped league: cap and tax_line are both the (absent) cap figure, and
        # cap_type reports the export's rule rather than a hardcoded default.
        self.assertEqual(app["finance"], {"cap": FIN_CAP, "cap_type": "none",
                                          "tax_line": FIN_CAP, "notes": "thousands"})

        player = app["players"][0]
        for key in ["pid", "name", "pos", "age", "tid", "jersey", "ovr", "pot",
                    "salary", "exp", "value", "ws", "pg", "ratings", "skills"]:
            self.assertIn(key, player)
        # "ws" = ows + dws from the ws_season stat row (1.5 + 0.5 in the fixture)
        self.assertEqual(player["ws"], 2.0)
        self.assertEqual(
            sorted(player["pg"].keys()),
            sorted(["pts", "trb", "ast", "stl", "blk", "tov", "min",
                    "fg_pct", "tp_pct", "ft_pct", "fpts"]),
        )
        self.assertEqual(sorted(player["ratings"].keys()), sorted(_RATING_KEYS))
        # players sorted by ovr desc: top player is from the strongest team (tid 3)
        self.assertEqual(player["tid"], 3)
        self.assertEqual(player["ovr"], 73)
        # per-game averages come from the 10-gp stat row: 150 pts -> 15.0/g
        self.assertEqual(player["pg"]["pts"], 15.0)
        self.assertEqual(player["pg"]["trb"], 5.0)
        self.assertAlmostEqual(player["pg"]["fg_pct"], 50.0)
        self.assertIsNotNone(player["pg"]["fpts"])

        team = app["teams"][0]
        for key in ["tid", "abbrev", "region", "name", "colors", "strength", "payroll", "record"]:
            self.assertIn(key, team)
        self.assertEqual(sorted(team["colors"].keys()), ["chart", "primary", "secondary"])
        self.assertEqual(team["record"], {"w": 0, "l": 0})  # fresh season starts 0-0
        # payroll: 6 rostered players on tid 0 -> pids 0..5
        self.assertEqual(team["payroll"], sum(10000 + 100 * p for p in range(6)))

        sim = app["sim"]
        self.assertEqual(sorted(sim.keys()), ["bench_ovrs", "hca", "logistic_k", "schedule", "season_games", "strengths"])
        self.assertEqual(sim["hca"], SIM_HCA)
        self.assertEqual(sim["logistic_k"], SIM_LOGISTIC_K)
        self.assertEqual(sim["season_games"], 6)  # the fixture's numGames
        self.assertEqual(sorted(sim["strengths"].keys()), ["0", "1", "2", "3"])
        self.assertTrue(sim["schedule"])
        for entry in sim["schedule"]:
            self.assertEqual(len(entry), 3)  # [day, home_tid, away_tid]
        # strongest roster should carry the highest strength
        self.assertEqual(max(sim["strengths"], key=lambda t: sim["strengths"][t]), "3")
        # bench_ovrs: 6th-best is each 6-man team's flat ovr -> mean 64.0;
        # no roster is deeper than 6, so ranks 7..10 fall back to replacement.
        self.assertEqual(sim["bench_ovrs"], [64.0] + [REPLACEMENT_OVR] * 4)
        self.assertEqual(sim["bench_ovrs"], sorted(sim["bench_ovrs"], reverse=True))

    def test_deterministic_double_build_and_write(self):
        data = _league_export()
        first = json.dumps(appdata.build_app_data(data), sort_keys=True)
        ALL_PLAYERS_BY_PID.clear()
        second = json.dumps(appdata.build_app_data(_league_export()), sort_keys=True)
        self.assertEqual(first, second)

        with tempfile.TemporaryDirectory() as tmp:
            path_a = appdata.write_app_data(os.path.join(tmp, "a"), _league_export())
            path_b = appdata.write_app_data(os.path.join(tmp, "b"), _league_export())
            self.assertTrue(str(path_a).endswith(os.path.join("assets", "app-data.json")))
            with open(path_a, encoding="utf-8") as fh:
                blob_a = fh.read()
            with open(path_b, encoding="utf-8") as fh:
                blob_b = fh.read()
            self.assertEqual(blob_a, blob_b)
            parsed = json.loads(blob_a)
            self.assertEqual(parsed["season"], 2030)


class TestSimStrength(unittest.TestCase):
    """Team strength: current-roster signal, blended with CURRENT-season MOV only."""

    def setUp(self):
        ALL_PLAYERS_BY_PID.clear()

    def tearDown(self):
        ALL_PLAYERS_BY_PID.clear()

    def _roster_signal(self, players, season):
        # Rank-decayed rotation sum: the best man on the roster is worth
        # rotation_weight(0) per point of overall, each slot below him less.
        totals = {}
        for tid in range(4):
            roster = [p for p in players if p["tid"] == tid]
            rotation = sorted(roster, key=lambda p: -player_game_impact(p, season))
            rotation = rotation[:ROTATION_SLOTS]
            totals[tid] = sum(
                player_game_impact(p, season, rank) for rank, p in enumerate(rotation)
            )
        mean = sum(totals.values()) / len(totals)
        return {tid: value - mean for tid, value in totals.items()}

    def test_rotation_weight_decays_by_slot(self):
        weights = [rotation_weight(rank) for rank in range(ROTATION_SLOTS)]
        self.assertEqual(weights, sorted(weights, reverse=True))
        self.assertEqual(rotation_weight(-1), rotation_weight(0))  # clamped

    def test_fresh_season_is_pure_roster(self):
        data = _league_export()
        inputs = sim_client_inputs(data, data["teams"], data["players"], 2030)
        self.assertTrue(inputs["fresh"])
        expected = self._roster_signal(data["players"], 2030)
        for tid, value in expected.items():
            self.assertAlmostEqual(inputs["strengths"][tid], value, places=9)

    def test_last_season_margin_never_seeds_strength(self):
        # Inflate team 0's PREVIOUS-season scoring margin absurdly; a fresh
        # season's strengths must not move at all.
        data = _league_export()
        base = sim_client_inputs(data, data["teams"], data["players"], 2030)["strengths"]
        data["teams"][0]["stats"][0]["pts"] += 45 * 60  # +60 MOV in 2029
        inflated = sim_client_inputs(data, data["teams"], data["players"], 2030)["strengths"]
        self.assertEqual(base, inflated)

    def test_in_season_blends_current_mov_by_gp(self):
        # At gp=2 the MOV weight is 2/(2+K); strengths must equal the exact blend.
        from smp.simmodel import SIM_MOV_BLEND_K

        data = _league_export_in_season()
        inputs = sim_client_inputs(data, data["teams"], data["players"], 2030)
        self.assertFalse(inputs["fresh"])
        self.assertEqual(inputs["wins"], {0: 1, 1: 1, 2: 2, 3: 0})
        self.assertEqual(inputs["losses"], {0: 1, 1: 1, 2: 0, 3: 2})
        # remaining schedule: only the four unplayed exported games
        self.assertEqual(len(inputs["schedule"]), 4)
        roster = self._roster_signal(data["players"], 2030)
        movs = {0: 0.0, 1: -4.0, 2: 10.0, 3: -6.0}
        w = 2.0 / (2.0 + SIM_MOV_BLEND_K)
        for tid in range(4):
            expected = (1.0 - w) * roster[tid] + w * movs[tid]
            self.assertAlmostEqual(inputs["strengths"][tid], expected, places=9)


class TestBenchOvrs(unittest.TestCase):
    def _player(self, pid, tid, ovr):
        return {"pid": pid, "tid": tid, "ratings": [{"season": 2030, "ovr": ovr}]}

    def test_rank_wise_league_average(self):
        players = []
        pid = 0
        for ovr in [80, 75, 70, 65, 60, 55, 50, 45, 42, 41]:  # 10-man roster
            players.append(self._player(pid, 0, ovr))
            pid += 1
        for ovr in [70, 68, 66, 64, 62, 60, 58]:  # 7-man roster
            players.append(self._player(pid, 1, ovr))
            pid += 1
        players.append(self._player(pid, -1, 99))  # free agent: ignored
        bench = league_bench_ovrs(players, 2030)
        # rank 6: (55+60)/2, rank 7: (50+58)/2, ranks 8-10: team 0 only
        self.assertEqual(bench, [57.5, 54.0, 45.0, 42.0, 41.0])
        self.assertEqual(bench, sorted(bench, reverse=True))
        self.assertEqual(len(bench), 5)

    def test_empty_league_falls_back_to_replacement(self):
        self.assertEqual(league_bench_ovrs([], 2030), [REPLACEMENT_OVR] * 5)


class TestSimParity(unittest.TestCase):
    """The client logistic model must agree with simulate_league's Monte Carlo."""

    def setUp(self):
        ALL_PLAYERS_BY_PID.clear()

    def tearDown(self):
        ALL_PLAYERS_BY_PID.clear()

    def _assert_parity(self, data, season=2030, sims=4000):
        teams = data["teams"]
        players = data["players"]
        inputs = sim_client_inputs(data, teams, players, season)
        strengths = inputs["strengths"]

        # Client-side expectation: banked wins + sum of logistic win probs
        # over the remaining schedule.
        expected = {tid: float(inputs["wins"].get(tid, 0)) for tid in strengths}
        for day, home, away in inputs["schedule"]:
            diff = (strengths[home] - strengths[away]) + inputs["hca"]
            p_home = 1.0 / (1.0 + math.exp(-diff * inputs["logistic_k"]))
            expected[home] += p_home
            expected[away] += 1.0 - p_home

        results = simulate_league(data, teams, players, season, sims=sims)["teams"]
        for tid, exp_wins in expected.items():
            proj_w = results[tid]["proj_w"]
            # Monte Carlo std error over `sims` runs is well under 0.05 wins here.
            self.assertLess(abs(proj_w - exp_wins), 0.2,
                            msg=f"tid {tid}: client {exp_wins:.3f} vs server {proj_w:.3f}")

    def test_expected_wins_match_server_sim_fresh_season(self):
        self._assert_parity(_league_export())

    def test_expected_wins_match_server_sim_in_season(self):
        self._assert_parity(_league_export_in_season())


class TestGameModelHelpers(unittest.TestCase):
    """Read-only helpers (game_win_prob / projected_margin / projected_spread /
    sim_strengths) expose the sim's exact numbers to other pages."""

    def setUp(self):
        ALL_PLAYERS_BY_PID.clear()

    def tearDown(self):
        ALL_PLAYERS_BY_PID.clear()

    def test_game_win_prob_is_the_sims_logistic(self):
        # Even strengths: home edge only.
        expected = 1.0 / (1.0 + math.exp(-SIM_HCA * SIM_LOGISTIC_K))
        self.assertAlmostEqual(game_win_prob(0.0, 0.0), expected, places=12)
        self.assertGreater(game_win_prob(0.0, 0.0), 0.5)  # HCA favors the host
        # Arbitrary strengths follow the documented formula exactly.
        self.assertAlmostEqual(
            game_win_prob(3.2, -1.1),
            1.0 / (1.0 + math.exp(-(3.2 - (-1.1) + SIM_HCA) * SIM_LOGISTIC_K)),
            places=12,
        )

    def test_projected_margin_is_strength_gap_plus_hca(self):
        self.assertAlmostEqual(projected_margin(2.0, -1.0), 3.0 + SIM_HCA)
        self.assertAlmostEqual(projected_margin(0.0, 0.0), SIM_HCA)

    def test_projected_spread_quotes_half_points_for_the_favorite(self):
        self.assertEqual(projected_spread(2.9, 0.0), -4.5)   # margin +4.4 -> HOME -4.5
        self.assertEqual(projected_spread(0.0, 3.6), 2.0)    # margin -2.1 -> AWAY -2.0
        self.assertEqual(projected_spread(-SIM_HCA, 0.0), 0.0)  # dead even -> pick'em

    def test_sim_strengths_matches_client_inputs(self):
        data = _league_export_in_season()
        self.assertEqual(
            sim_strengths(data, data["teams"], data["players"], 2030),
            sim_client_inputs(data, data["teams"], data["players"], 2030)["strengths"],
        )

    def test_stakes_payload_reuses_the_same_strengths(self):
        # The next-slate projection payload must agree with the helpers when fed
        # sim_client_inputs strengths (no injuries in this fixture).
        data = _league_export_in_season()
        teams, players = data["teams"], data["players"]
        strengths = sim_strengths(data, teams, players, 2030)
        result = simulate_league(data, teams, players, 2030, sims=200)
        stakes = result["stakes"]
        self.assertEqual(result["day"], 3)
        self.assertEqual([s["gid"] for s in stakes], ["5", "6"])  # both day-3 games
        for stake in stakes:
            home, away = stake["home_tid"], stake["away_tid"]
            self.assertAlmostEqual(
                stake["home_wp"], game_win_prob(strengths[home], strengths[away]), places=12)
            self.assertEqual(
                stake["spread"], projected_spread(strengths[home], strengths[away]))
            for key in ("home_po_win", "home_po_loss", "away_po_win", "away_po_loss"):
                value = stake[key]
                if value is not None:
                    self.assertGreaterEqual(value, 0.0)
                    self.assertLessEqual(value, 1.0)


if __name__ == "__main__":
    unittest.main()
