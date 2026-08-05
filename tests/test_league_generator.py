"""Focused regression tests for scripts/league_generator.py."""

import os
import sys
import unittest


_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_HERE)
_SCRIPTS = os.path.join(_REPO, "scripts")
if _SCRIPTS not in sys.path:
    sys.path.insert(0, _SCRIPTS)

import league_generator as lg  # noqa: E402


def _team(tid, abbrev, region="Test", name=None):
    return {"tid": tid, "abbrev": abbrev, "region": region, "name": name or abbrev}


def _player(pid, first, last, tid=0, exp=2030, amount=10000, ovr=60):
    return {
        "pid": pid,
        "firstName": first,
        "lastName": last,
        "tid": tid,
        "retiredYear": None,
        "born": {"year": 2000},
        "contract": {"exp": exp, "amount": amount},
        "ratings": [{"season": 2029, "pos": "G", "ovr": ovr, "pot": ovr + 2}],
    }


class TestFreeAgentSalary(unittest.TestCase):
    def test_worked_examples_from_formula(self):
        # 1-year asking salary ($M). The curve passes through FA_PRICE_AT_PIVOT at
        # FA_PRICE_PIVOT overall for a peak-age player and doubles every
        # FA_PRICE_WIDTH points; a one-year deal then pays the 1-year premium.
        one_yr = lg.FA_DURATION_PREMIUM[1]
        pivot = lg.FA_PRICE_AT_PIVOT
        self.assertEqual(lg.fa_salary_millions(60, 60, 28), round(pivot * one_yr, 2))
        self.assertEqual(lg.fa_salary_millions(65, 70, 28), round(pivot * 2 * one_yr, 2))
        self.assertEqual(lg.fa_salary_millions(70, 70, 28), 21.33)  # 4.266 x 4 x 1.25
        # Age is a straight multiplier on the same curve; potential never moves the ask.
        self.assertEqual(lg.fa_salary_millions(60, 60, 22),
                         round(pivot * lg.fa_age_factor(22) * one_yr, 2))
        self.assertEqual(lg.fa_salary_millions(60, 99, 28), lg.fa_salary_millions(60, 60, 28))

    def test_bounds_and_curve_ends(self):
        self.assertEqual(lg.fa_salary_millions(40, 40, 30), lg.FA_MIN_CONTRACT)  # $1M floor
        self.assertEqual(lg.fa_salary_millions(90, 90, 27), lg.FA_MAX_CONTRACT)  # $50M cap

    def test_by_length_first_year_matches_single(self):
        vals = lg.fa_salary_by_length(67, 73, 24)
        self.assertEqual(len(vals), 5)
        self.assertEqual(vals[0], lg.fa_salary_millions(67, 73, 24))  # 1-yr == pure formula
        # aging a 24yo whose upside premium fades should not raise the annual on longer deals
        self.assertLessEqual(vals[4], vals[0])


class TestContractExpiryMarket(unittest.TestCase):
    def test_rostered_expiring_contracts_exclude_free_agents_and_retired_players(self):
        players = [
            _player(1, "Rostered", "Guard", tid=0, exp=2029),
            _player(2, "Free", "Agent", tid=lg.FREE_AGENT_TID, exp=2029),
            _player(3, "Future", "Deal", tid=1, exp=2030),
            {**_player(4, "Retired", "Player", tid=lg.RETIRED_TID, exp=2029), "retiredYear": 2028},
        ]

        rows = lg.contract_expiring_players(players, 2029, rostered_only=True)

        self.assertEqual([p["pid"] for p in rows], [1])

class TestTeamGameViews(unittest.TestCase):
    def test_team_finances_limit_years_and_omit_expiry_badges(self):
        short = _player(21, "Short", "Deal", tid=0, exp=2029, amount=5000)
        long = _player(22, "Long", "Deal", tid=0, exp=2034, amount=7000)

        html = lg.team_finances_table([short, long], 2029)

        self.assertIn("2033", html)      # salary charts run five seasons wide
        self.assertNotIn("2034", html)
        self.assertNotIn("2029 expiring", html)
        self.assertNotIn(">exp</span>", html)
        self.assertNotIn("expiring-cell", html)

    def test_team_finances_window_starts_at_the_current_season(self):
        # The window is season .. season+4. It used to start at season+1, which
        # blanked out every expiring deal on an export of an unplayed season.
        player = _player(23, "Future", "Season", tid=0, exp=2035, amount=5000)

        html = lg.team_finances_table([player], 2034)

        self.assertIn("2034", html)     # the current season is column one
        self.assertIn("2035", html)
        self.assertIn("2038", html)
        self.assertNotIn("2039", html)

    def test_depth_chart_assigns_each_player_once(self):
        players = [
            {**_player(31, "Combo", "Guard", ovr=70), "hgt": 75},
            {**_player(32, "Swing", "Wing", ovr=68), "hgt": 80},
            {**_player(33, "Front", "Court", ovr=66), "hgt": 83},
        ]
        players[0]["ratings"][-1].update({"pos": "G", "pss": 80, "drb": 72, "tp": 45, "fg": 50})
        players[1]["ratings"][-1].update({"pos": "GF"})
        players[2]["ratings"][-1].update({"pos": "FC"})

        html = lg.depth_chart_card(players, 2029)

        for player in players:
            self.assertEqual(html.count(lg.player_url(player, "../")), 1)

    def test_team_games_table_includes_completed_and_upcoming_regular_games(self):
        teams_by_tid = {0: _team(0, "AAA"), 1: _team(1, "BBB")}
        game_items = [
            {
                "gid": 1,
                "day": 1,
                "season": 2029,
                "home_tid": 0,
                "away_tid": 1,
                "home_pts": 101,
                "away_pts": 99,
                "home_box": {"tid": 0, "pts": 101},
                "away_box": {"tid": 1, "pts": 99},
                "game": {"gid": 1},
                "playoffs": False,
            },
            {
                "gid": 2,
                "day": 2,
                "season": 2029,
                "home_tid": 1,
                "away_tid": 0,
                "home_pts": None,
                "away_pts": None,
                "playoffs": False,
            },
            {
                "gid": 3,
                "day": 3,
                "season": 2029,
                "home_tid": 0,
                "away_tid": 1,
                "home_pts": 80,
                "away_pts": 90,
                "home_box": {"tid": 0, "pts": 80},
                "away_box": {"tid": 1, "pts": 90},
                "game": {"gid": 3},
                "playoffs": True,
            },
        ]

        html = lg.team_games_table(_team(0, "AAA"), game_items, teams_by_tid, 2029)

        self.assertIn("1 completed · 1 upcoming", html)
        self.assertIn("AAA current-season game log", html)
        self.assertEqual(html.count('class="click-row'), 2)
        self.assertIn("Upcoming", html)

    def test_rotation_map_uses_logged_team_not_current_roster_team(self):
        current_guard = _player(1, "Current", "Guard", tid=0)
        former_wing = _player(2, "Former", "Wing", tid=1)
        current_forward = _player(4, "Current", "Forward", tid=0)
        original_players = dict(lg.ALL_PLAYERS_BY_PID)
        lg.ALL_PLAYERS_BY_PID.clear()
        lg.ALL_PLAYERS_BY_PID.update({
            1: current_guard,
            2: former_wing,
            4: current_forward,
        })

        def restore_players():
            lg.ALL_PLAYERS_BY_PID.clear()
            lg.ALL_PLAYERS_BY_PID.update(original_players)

        self.addCleanup(restore_players)
        data = {
            "games": [
                {
                    "gid": 101,
                    "season": 2029,
                    "day": 1,
                    "playoffs": False,
                    "teams": [
                        {
                            "tid": 0,
                            "pts": 100,
                            "players": [
                                {"pid": 1, "name": "Current Guard", "min": 10},
                                {"pid": 2, "name": "Former Wing", "min": 22},
                            ],
                        },
                        {"tid": 1, "pts": 90, "players": [{"pid": 3, "name": "Opponent", "min": 30}]},
                    ],
                },
                {
                    "gid": 102,
                    "season": 2029,
                    "day": 2,
                    "playoffs": False,
                    "teams": [
                        {"tid": 1, "pts": 110, "players": [{"pid": 1, "name": "Current Guard", "min": 33}]},
                        {"tid": 0, "pts": 95, "players": [{"pid": 4, "name": "Current Forward", "min": 12}]},
                    ],
                },
            ]
        }
        teams_by_tid = {0: _team(0, "AAA"), 1: _team(1, "BBB")}
        game_items = lg.completed_game_items(data, season=2029, playoffs=False)
        logs = lg.build_game_logs(data, 2029)

        html = lg.rotation_map_card(_team(0, "AAA"), [current_guard, current_forward], game_items, logs, 2029, teams_by_tid)

        self.assertEqual([entry["tid"] for entry in logs[1]], [0, 1])
        self.assertIn("Former Wing", html)
        self.assertIn("Current Forward", html)
        self.assertIn(">10</td>", html)
        self.assertNotIn(">33</td>", html)
        self.assertIn("hsla(", html)
        self.assertIn("red to green = minutes", html)


class TestTeamFinances(unittest.TestCase):
    SEASON = 2004   # SMP II is the 2003-04 NBA
    GAMES = 36      # 36-game regular season -> 180 league wins

    def _ga(self):
        # SMP II rules as the export states them: no cap, best-of-5 every round.
        return {"season": self.SEASON, "salaryCap": 0, "salaryCapType": "none",
                "numGamesPlayoffSeries": [5, 5]}

    def _team_s(self, tid, abbrev, won, lost=None):
        return {"tid": tid, "abbrev": abbrev, "region": "City", "name": abbrev,
                "seasons": [{"season": self.SEASON, "won": won,
                             "lost": self.GAMES - won if lost is None else lost}]}

    def _pl(self, tid, amount):
        return {"pid": tid * 100, "firstName": "P", "lastName": str(tid), "tid": tid,
                "contract": {"amount": amount, "exp": self.SEASON + 1},
                "ratings": [{"season": self.SEASON, "ovr": 60}]}

    def _data(self, teams, players, series=None):
        return {"gameAttributes": self._ga(), "teams": teams, "players": players,
                "playoffSeries": list(series or []), "releasedPlayers": []}

    def test_regular_season_ledger_is_uncapped_and_untaxed(self):
        teams = [self._team_s(0, "AAA", 20), self._team_s(1, "BBB", 5)]
        players = [self._pl(0, 320000), self._pl(1, 200000)]  # no cap: any payroll is legal
        data = self._data(teams, players)
        lf = lg.compute_league_finances(data, teams, players, self.SEASON, odds={})
        a, b = lf["teams"][0], lf["teams"][1]
        # no playoff bonus during the regular season
        self.assertEqual(a["earned_playoff"], 0)
        # revenue = a flat $5M per win, every win worth the same — no base, no league share
        self.assertEqual(a["revenue_now"], lg.FIN_PER_WIN * 20)
        self.assertEqual(a["win_rev_now"], lg.win_revenue(20))
        self.assertEqual(a["base_rev"], lg.FIN_BASE)
        # net revenue = the whole next-season budget; nothing is netted out of it
        self.assertAlmostEqual(a["net_revenue_now"], a["revenue_now"])
        self.assertAlmostEqual(a["season_balance_now"], a["net_revenue_now"] - 320000)
        self.assertAlmostEqual(b["net_revenue_now"], lg.FIN_PER_WIN * 5)
        # surplus vs the committed next-season payroll (contracts run through exp)
        self.assertAlmostEqual(b["committed_next"], 200000)
        self.assertAlmostEqual(b["surplus_next"], b["net_revenue_proj"] - 200000)
        # SMP II has no cap and no luxury tax: no tax pool, no tax keys, nobody over the line
        self.assertEqual(lf["cap"], lg.FIN_CAP)
        self.assertEqual(lf["cap_type"], "none")
        self.assertNotIn("pool", lf)
        self.assertFalse(a["over_cap"])
        for key in ("luxtax", "tax_share_in", "cash_now", "cash_proj", "payroll_next", "avail"):
            self.assertNotIn(key, a)

    def test_manual_adjustment_moves_cash_and_nets_to_zero(self):
        # Mechanism test: FIN_ADJUSTMENTS is injected here so it doesn't depend on live
        # trade data. SMP II ships with no rows — the SMP I ones referenced a league
        # that no longer exists — but the ledger still has to fold cash trades in.
        teams = [self._team_s(2, "CAM", 18), self._team_s(6, "WAL", 18)]
        players = [self._pl(2, 100000), self._pl(6, 100000)]
        data = self._data(teams, players)
        saved_adj = {s: dict(e) for s, e in lg.FIN_ADJUSTMENTS.items()}
        lg.FIN_ADJUSTMENTS.clear()
        lg.FIN_ADJUSTMENTS.update({self.SEASON: {
            2: {"amount": -1000, "note": "cash to Waltham"},
            6: {"amount": 1000, "note": "cash from Cambridge"},
        }})
        try:
            lf = lg.compute_league_finances(data, teams, players, self.SEASON, odds={})
            # an adjustment must not leak into another season's ledger
            lf_next = lg.compute_league_finances(data, teams, players, self.SEASON + 1, odds={})
        finally:
            lg.FIN_ADJUSTMENTS.clear()
            lg.FIN_ADJUSTMENTS.update(saved_adj)
        cam, wal = lf["teams"][2], lf["teams"][6]
        self.assertEqual(cam["adj"], -1000)
        self.assertEqual(wal["adj"], 1000)
        self.assertIn("Waltham", cam["adj_note"])
        # adjustment is baked into revenue/net revenue and conserved across the two teams
        self.assertAlmostEqual(cam["revenue_now"], lg.FIN_PER_WIN * 18 - 1000)
        self.assertAlmostEqual(cam["net_revenue_now"] + wal["net_revenue_now"],
                               2 * (lg.FIN_PER_WIN * 18))
        self.assertAlmostEqual(cam["adj"] + wal["adj"], 0)
        self.assertEqual(lf_next["teams"][2]["adj"], 0)

    def test_adjustments_net_to_zero_every_season(self):
        for season, entries in lg.FIN_ADJUSTMENTS.items():
            net = sum(e.get("amount", 0) for e in entries.values())
            self.assertEqual(net, 0, f"FIN_ADJUSTMENTS for {season} must net to zero")

    def test_salary_retention_moves_payroll_between_teams(self):
        # Mechanism test: a player (pid 1789) sits on tid 5 at $42M; tid 6 retains $17M.
        # FIN_RETENTION is injected here so the test doesn't depend on live trade data.
        cody = {"pid": 1789, "firstName": "Cody", "lastName": "Williams", "tid": 5,
                "contract": {"amount": 42000, "exp": self.SEASON + 4},
                "ratings": [{"season": self.SEASON, "ovr": 65}]}
        teams = [self._team_s(5, "GOO", 18), self._team_s(6, "WAL", 18)]
        players = [cody, self._pl(6, 50000)]
        data = self._data(teams, players)
        saved = dict(lg.ALL_PLAYERS_BY_PID)
        saved_ret = dict(lg.FIN_RETENTION)
        lg.ALL_PLAYERS_BY_PID.clear()
        lg.ALL_PLAYERS_BY_PID.update({1789: cody})
        lg.FIN_RETENTION.clear()
        lg.FIN_RETENTION.update({1789: {"held_by": 6, "amount": 17000, "note": "Waltham (trade)"}})
        try:
            lf = lg.compute_league_finances(data, teams, players, self.SEASON, odds={})
        finally:
            lg.ALL_PLAYERS_BY_PID.clear()
            lg.ALL_PLAYERS_BY_PID.update(saved)
            lg.FIN_RETENTION.clear()
            lg.FIN_RETENTION.update(saved_ret)
        goo, wal = lf["teams"][5], lf["teams"][6]
        # Gooners are relieved of $17M: they pay $25M of Cody's $42M
        self.assertAlmostEqual(goo["retained"], -17000)
        self.assertAlmostEqual(goo["payroll"], 42000 - 17000)
        # Waltham carries the retained $17M on top of its own $50M roster
        self.assertAlmostEqual(wal["retained"], 17000)
        self.assertAlmostEqual(wal["payroll"], 50000 + 17000)
        # retention nets to zero across the league
        self.assertAlmostEqual(sum(t["retained"] for t in lf["teams"].values()), 0)

    def test_finals_length_and_playoff_win_money_read_the_export(self):
        # SMP II plays [5, 5], so three wins take the title where SMP I's [7, 7] needed four.
        self.assertEqual(lg.finals_games_to_win(self._data([], []), self.SEASON), 3)
        self.assertEqual(
            lg.finals_games_to_win({"gameAttributes": {"numGamesPlayoffSeries": [7, 7]}}, self.SEASON), 4)
        # per-playoff-win money counts games won in every round, by winners and losers alike
        series = {"season": self.SEASON, "series": [
            [{"home": {"tid": 0, "won": 3}, "away": {"tid": 3, "won": 2}}],
            [{"home": {"tid": 0, "won": 1}, "away": {"tid": 1, "won": 0}}],
        ]}
        data = {"gameAttributes": self._ga(), "playoffSeries": [series]}
        self.assertEqual(lg.playoff_wins(data, 0, self.SEASON), 4)
        self.assertEqual(lg.playoff_wins(data, 3, self.SEASON), 2)
        self.assertEqual(lg.playoff_wins(data, 0, self.SEASON + 1), 0)

    def test_playoff_bonuses_stack_only_when_earned(self):
        complete = {"season": self.SEASON, "series": [
            [{"home": {"tid": 0, "won": 3}, "away": {"tid": 3, "won": 1}},
             {"home": {"tid": 1, "won": 3}, "away": {"tid": 2, "won": 2}}],
            [{"home": {"tid": 0, "won": 3}, "away": {"tid": 1, "won": 2}}],
        ]}
        data = {"gameAttributes": self._ga(), "playoffSeries": [complete]}
        s = self.SEASON
        self.assertEqual(lg.playoff_status(data, 0, s), (True, True, True))    # champion -> 10+7.5+15
        self.assertEqual(lg.playoff_status(data, 1, s), (True, True, False))   # finalist -> 10+7.5
        self.assertEqual(lg.playoff_status(data, 2, s), (True, False, False))  # 1st-round out -> 10

    def test_no_false_finalists_mid_round_one(self):
        # Only round 1 exists; tid0 has already clinched its series 3-1. The Finals
        # round does not exist yet, so nobody may be crowned finalist/champion.
        midway = {"season": self.SEASON, "series": [
            [{"home": {"tid": 0, "won": 3}, "away": {"tid": 3, "won": 1}},
             {"home": {"tid": 1, "won": 2}, "away": {"tid": 2, "won": 1}}],
        ]}
        data = {"gameAttributes": self._ga(), "playoffSeries": [midway]}
        self.assertEqual(lg.playoff_status(data, 0, self.SEASON), (True, False, False))
        self.assertEqual(lg.playoff_status(data, 1, self.SEASON), (True, False, False))

    def test_finals_in_progress_is_not_yet_a_championship(self):
        inprog = {"season": self.SEASON, "series": [
            [{"home": {"tid": 0, "won": 3}, "away": {"tid": 3, "won": 0}},
             {"home": {"tid": 1, "won": 3}, "away": {"tid": 2, "won": 1}}],
            [{"home": {"tid": 0, "won": 2}, "away": {"tid": 1, "won": 2}}],  # 2-2, unclinched
        ]}
        data = {"gameAttributes": self._ga(), "playoffSeries": [inprog]}
        self.assertEqual(lg.playoff_status(data, 0, self.SEASON), (True, True, False))
        self.assertEqual(lg.playoff_status(data, 1, self.SEASON), (True, True, False))

    def test_average_net_revenue_identity_is_100m(self):
        # Synthetic full league: 180 total wins (10 teams x 36 games), 4 playoff teams,
        # 12 playoff game wins, 2 finalists, 1 champion. Average net revenue (= the
        # next-season budget) must land exactly on the target payroll:
        #   180*$5M + (4*$10M + 12*$2.5M + 2*$7.5M + $15M) = $900M + $100M = $1,000M
        #   -> $100.0M each. Manual adjustments net to zero league-wide; there is no
        #   league share, no base, and no tax to net out.
        wins = [28, 26, 24, 22, 20, 16, 14, 12, 10, 8]
        self.assertEqual(sum(wins), self.GAMES * 10 // 2)
        teams = [self._team_s(tid, f"T{tid}", w) for tid, w in enumerate(wins)]
        # every team at the target payroll, so the league-average team breaks even
        players = [self._pl(tid, lg.FIN_TARGET_PAYROLL) for tid in range(10)]
        finished = {"season": self.SEASON, "series": [
            [{"home": {"tid": 0, "won": 3}, "away": {"tid": 3, "won": 1}},
             {"home": {"tid": 1, "won": 3}, "away": {"tid": 2, "won": 1}}],
            [{"home": {"tid": 0, "won": 3}, "away": {"tid": 1, "won": 1}}],
        ]}
        data = self._data(teams, players, [finished])
        lf = lg.compute_league_finances(data, teams, players, self.SEASON, odds={})
        self.assertEqual(len(lf["teams"]), 10)
        # 12 playoff game wins across the bracket -> $30M of per-win money
        self.assertEqual(sum(lg.playoff_wins(data, tid, self.SEASON) for tid in range(10)), 12)
        # champion stacks berth + 6 playoff wins + finals + title = $47.5M
        self.assertEqual(lf["teams"][0]["earned_playoff"],
                         lg.FIN_PLAYOFF + 6 * lg.FIN_PLAYOFF_WIN + lg.FIN_FINALS + lg.FIN_CHAMP)
        self.assertEqual(lf["teams"][0]["earned_playoff"], 47500)
        avg_net = sum(f["net_revenue_now"] for f in lf["teams"].values()) / 10
        self.assertAlmostEqual(avg_net, float(lg.FIN_TARGET_PAYROLL))
        self.assertAlmostEqual(avg_net, 100000.0)
        # season balance = net revenue − payroll: at the target payroll the league breaks even
        avg_balance = sum(f["season_balance_now"] for f in lf["teams"].values()) / 10
        self.assertAlmostEqual(avg_balance, 0.0)


class TestCanonicalPositions(unittest.TestCase):
    def _rating(self, pos, **kw):
        return {"season": 2031, "pos": pos, "pss": 40, "drb": 40, "tp": 40, "fg": 40, **kw}

    def test_canonical_labels_pass_through(self):
        for pos in ("PG", "SG", "SF", "PF", "C"):
            self.assertEqual(lg.canonical_pos({"hgt": 78}, self._rating(pos)), pos)

    def test_guard_splits_on_playmaking_vs_scoring(self):
        pg = self._rating("G", pss=60, drb=60, tp=30, fg=30)
        sg = self._rating("G", pss=30, drb=30, tp=60, fg=60)
        self.assertEqual(lg.canonical_pos({"hgt": 74}, pg), "PG")
        self.assertEqual(lg.canonical_pos({"hgt": 74}, sg), "SG")

    def test_frontcourt_middles_round_by_height(self):
        self.assertEqual(lg.canonical_pos({"hgt": 78}, self._rating("GF")), "SG")
        self.assertEqual(lg.canonical_pos({"hgt": 80}, self._rating("GF")), "SF")
        self.assertEqual(lg.canonical_pos({"hgt": 80}, self._rating("F")), "SF")
        self.assertEqual(lg.canonical_pos({"hgt": 82}, self._rating("F")), "PF")
        self.assertEqual(lg.canonical_pos({"hgt": 82}, self._rating("FC")), "PF")
        self.assertEqual(lg.canonical_pos({"hgt": 84}, self._rating("FC")), "C")

    def test_normalize_rewrites_ratings_and_box_scores_in_place(self):
        data = {
            "players": [{"pid": 7, "hgt": 84, "ratings": [self._rating("FC"), self._rating("F", tp=30, fg=30)]}],
            "games": [{"teams": [{"players": [{"pid": 7, "pos": "GF"}, {"pid": 99, "pos": "SF"}]}]}],
        }
        lg.normalize_positions(data)
        self.assertEqual([r["pos"] for r in data["players"][0]["ratings"]], ["C", "PF"])
        # box score maps by pid to the player's latest canonical pos; unknown pid untouched
        box = data["games"][0]["teams"][0]["players"]
        self.assertEqual(box[0]["pos"], "PF")
        self.assertEqual(box[1]["pos"], "SF")

    def test_no_middle_labels_survive_on_the_real_export(self):
        import glob, json
        matches = glob.glob(os.path.join(_REPO, "league-data", "2004_predraft.json"))
        if not matches:
            self.skipTest("2004 predraft export not present")
        with open(matches[0], "r", encoding="utf-8") as fh:
            data = json.load(fh)
        lg.normalize_positions(data)
        seen = {r.get("pos") for p in data["players"] for r in (p.get("ratings") or [])}
        self.assertTrue(seen.issubset(set(lg.CANONICAL_POS)), seen)


if __name__ == "__main__":
    unittest.main()
