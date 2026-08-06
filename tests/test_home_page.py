"""Tests for scripts/smp/pages/home.py (phase-aware home page, W4/P8).

Covers the phase composition switch, the odds-river chart (including a
synthetic multi-point ledger and the graceful single-point state), the
fantasy-leaders card, the per-game projection cards, and the
offseason-digest event selection.
"""

import os
import sys
import unittest


_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_HERE)
_SCRIPTS = os.path.join(_REPO, "scripts")
if _SCRIPTS not in sys.path:
    sys.path.insert(0, _SCRIPTS)

from smp.core import SITE_META  # noqa: E402
from smp.identity import team_chart_color  # noqa: E402
from smp.pages import home  # noqa: E402


def _team(tid, abbrev, season=2031, stats=None, seasons=None):
    return {
        "tid": tid,
        "cid": 0,
        "abbrev": abbrev,
        "region": f"Region{tid}",
        "name": f"Name{tid}",
        "seasons": seasons if seasons is not None else [{"season": season, "won": 0, "lost": 0, "cid": 0}],
        "stats": stats or [],
    }


def _team_stat_row(season, gp=45, pts=5000, opp_pts=4900):
    return {
        "season": season, "playoffs": False, "gp": gp,
        "fg": 1800, "fga": 3900, "tp": 550, "tpa": 1500, "ft": 850, "fta": 1080,
        "orb": 500, "drb": 1450, "tov": 700, "pts": pts,
        "oppFg": 1780, "oppFga": 3880, "oppTp": 540, "oppFt": 840, "oppFta": 1075,
        "oppOrb": 470, "oppDrb": 1430, "oppTov": 680, "oppPts": opp_pts,
    }


def _snapshot(season, phase, games_played, odds_by_tid):
    return {
        "season": season,
        "phase": phase,
        "games_played": games_played,
        "teams": {
            str(tid): {"po": po, "finals": po / 2, "title": po / 4, "proj_w": 22.0, "proj_l": 23.0}
            for tid, po in odds_by_tid.items()
        },
    }


class TestHomePhaseKind(unittest.TestCase):
    def _data(self, phase, games=None):
        return {"gameAttributes": {"season": 2031, "phase": phase}, "games": games or []}

    def _completed_game(self, season):
        return {
            "gid": 1, "season": season, "day": 3, "playoffs": False,
            "teams": [
                {"tid": 0, "pts": 100, "players": []},
                {"tid": 1, "pts": 90, "players": []},
            ],
        }

    def test_preseason_phase(self):
        self.assertEqual(home.home_phase_kind(self._data(0), 2031), "preseason")

    def test_regular_phase_without_games_composes_as_preseason(self):
        self.assertEqual(home.home_phase_kind(self._data(1), 2031), "preseason")

    def test_regular_phase_with_games(self):
        data = self._data(1, games=[self._completed_game(2031)])
        self.assertEqual(home.home_phase_kind(data, 2031), "regular")

    def test_playoffs_phase(self):
        data = self._data(3, games=[self._completed_game(2031)])
        self.assertEqual(home.home_phase_kind(data, 2031), "playoffs")

    def test_offseason_phases(self):
        for phase in (4, 5, 6, 7, 8):
            self.assertEqual(home.home_phase_kind(self._data(phase), 2031), "offseason")

    def test_last_completed_season(self):
        data = {"gameAttributes": {"season": 2031, "phase": 0}, "games": [self._completed_game(2030)]}
        self.assertEqual(home.last_completed_season(data, 2031), 2030)


class TestOddsRiverCard(unittest.TestCase):
    def setUp(self):
        self.teams = [_team(0, "AAA"), _team(1, "BBB")]
        self.data = {"gameAttributes": {"season": 2031, "phase": 1}, "games": []}

    def test_multi_point_ledger_draws_team_lines(self):
        history = [
            _snapshot(2031, 0, 0, {0: 0.60, 1: 0.40}),
            _snapshot(2031, 1, 10, {0: 0.70, 1: 0.30}),
            _snapshot(2031, 1, 20, {0: 0.80, 1: 0.20}),
        ]
        html = home.odds_river_card(self.data, self.teams, 2031, history=history)
        self.assertIn("<polyline", html)
        self.assertEqual(html.count('class="oddsr-line"'), 2)  # one line per team
        # Snapshot ticks: the preseason projection is the season's first RS tick,
        # so the run numbers straight through instead of starting on "Pre".
        self.assertNotIn(">Pre</text>", html)
        self.assertIn(">RS 1</text>", html)
        self.assertIn(">RS 2</text>", html)
        self.assertIn(">RS 3</text>", html)
        self.assertIn("Preseason", html)  # the long hover label still says what it is
        # Team-identity chart colors drive the strokes.
        self.assertIn(team_chart_color(0), html)
        self.assertIn(team_chart_color(1), html)
        # Hover plumbing (payload + crosshair + tooltip) is emitted.
        self.assertIn('id="oddsr-data"', html)
        self.assertIn("data-oddsr", html)
        self.assertIn("data-oddsr-hline", html)
        self.assertIn("data-oddsr-tooltip", html)

    def test_missing_snapshot_breaks_line_instead_of_faking_data(self):
        history = [
            _snapshot(2031, 0, 0, {0: 0.60, 1: 0.40}),
            _snapshot(2031, 1, 10, {0: 0.70}),  # team 1 missing mid-season
            _snapshot(2031, 1, 20, {0: 0.80, 1: 0.20}),
        ]
        html = home.odds_river_card(self.data, self.teams, 2031, history=history)
        # Team 0 keeps its full line; team 1 gets no bridged polyline.
        self.assertEqual(html.count('class="oddsr-line"'), 1)
        self.assertIn('class="oddsr-dot"', html)

    def test_single_point_ledger_renders_graceful_state(self):
        history = [_snapshot(2031, 0, 0, {0: 0.55, 1: 0.45})]
        html = home.odds_river_card(self.data, self.teams, 2031, history=history)
        self.assertNotIn("<polyline", html)
        self.assertIn("one snapshot so far", html)
        self.assertIn('class="oddsr-dot"', html)
        self.assertIn(">AAA</text>", html)  # labels sit next to the dots
        self.assertNotIn("data-oddsr", html)  # no hover plumbing for one point
        self.assertNotIn('id="oddsr-data"', html)

    def test_no_snapshots_for_season_renders_nothing(self):
        history = [_snapshot(2030, 1, 10, {0: 0.5, 1: 0.5})]
        self.assertEqual(home.odds_river_card(self.data, self.teams, 2031, history=history), "")


class TestFantasyLeadersCard(unittest.TestCase):
    def _player(self, pid, name, tid, season, gp, stat_overrides=None):
        stat = {
            "season": season, "playoffs": False, "tid": tid, "gp": gp,
            "pts": 20 * gp, "fg": 8 * gp, "fga": 16 * gp, "tp": 2 * gp,
            "ft": 2 * gp, "fta": 3 * gp, "trb": 8 * gp, "ast": 5 * gp,
            "stl": 1 * gp, "blk": 1 * gp, "tov": 2 * gp, "min": 30 * gp,
        }
        stat.update(stat_overrides or {})
        first, last = name.split(" ", 1)
        return {
            "pid": pid, "firstName": first, "lastName": last, "tid": tid,
            "retiredYear": None, "born": {"year": 2000},
            "ratings": [{"season": season, "pos": "G", "ovr": 60, "pot": 65}],
            "stats": [stat],
        }

    def setUp(self):
        self.teams = [_team(0, "AAA", stats=[_team_stat_row(2030)]),
                      _team(1, "BBB", stats=[_team_stat_row(2030)])]
        self.data = {"gameAttributes": {"season": 2031, "phase": 0}, "games": []}

    def test_orders_by_fantasy_points_per_game_with_min_gp_filter(self):
        star = self._player(1, "Big Star", 0, 2030, 40, {"pts": 30 * 40, "ast": 8 * 40})
        role = self._player(2, "Role Guy", 1, 2030, 40)
        cameo = self._player(3, "Small Sample", 1, 2030, 5, {"pts": 60 * 5})  # under min GP
        html = home.fantasy_leaders_card(self.data, [star, role, cameo], self.teams, 2030, 2031)
        self.assertIn("Big Star", html)
        self.assertIn("Role Guy", html)
        self.assertNotIn("Small Sample", html)
        self.assertLess(html.find("Big Star"), html.find("Role Guy"))
        # Preseason fallback is labeled honestly; the stat is plain FPTS.
        self.assertIn("2030 · last completed season", html)
        self.assertIn("FPTS/G", html)
        self.assertNotIn("ESPN", html)

    def test_fantasy_scoring_value_has_one_decimal(self):
        # Per game: pts20 fg8 fga16 tp2 ft2 fta3 trb8 ast5 stl1 blk1 tov2
        # = 20 + 2 + 16 - 16 + 2 - 3 + 8 + 10 + 4 + 4 - 4 = 43 FPTS/G, shown as 43.0
        player = self._player(1, "Known Line", 0, 2030, 40)
        html = home.fantasy_leaders_card(self.data, [player], self.teams, 2030, 2031)
        self.assertIn(">43.0</span>", html)
        self.assertNotIn(">43</span>", html)

    def test_no_team_games_renders_nothing(self):
        teams = [_team(0, "AAA"), _team(1, "BBB")]  # no 2030 stat rows
        player = self._player(1, "Someone Good", 0, 2030, 40)
        self.assertEqual(home.fantasy_leaders_card(self.data, [player], teams, 2030, 2031), "")


class TestGameProjectionCards(unittest.TestCase):
    """One card per next-slate game: color chips, one-decimal win probability
    for both sides, a spread quoted for the favorite, and each team's
    conditional playoff-odds swing — all straight from the sim payload."""

    def setUp(self):
        self._real_league_sim = home.league_sim
        home.league_sim = lambda data, teams, season: {
            "teams": {0: {"po": 0.489}, 1: {"po": 0.623}},
            "stakes": [{
                "gid": "704", "day": 1, "home_tid": 0, "away_tid": 1,
                "home_wp": 0.553, "spread": -1.5,
                "home_po_win": 0.552, "home_po_loss": 0.417,
                "away_po_win": 0.66, "away_po_loss": 0.581,
            }],
            "day": 1,
            "fresh": True,
        }

    def tearDown(self):
        home.league_sim = self._real_league_sim

    def _teams(self):
        return [_team(0, "AAA"), _team(1, "BBB")]

    def test_card_links_to_preview_and_shows_all_projection_numbers(self):
        data = {
            "gameAttributes": {"season": 2031, "phase": 1, "numGames": 45},
            "games": [],
            "schedule": [{"gid": 704, "season": 2031, "day": 1, "homeTid": 0, "awayTid": 1}],
        }
        html = home.game_projection_cards(data, self._teams(), 2031)
        self.assertIn("Game Projections · Opening Day", html)
        # The scheduled game has a real gid: the card links to its preview page.
        self.assertIn('href="games/704.html"', html)
        # One-decimal win probability for BOTH teams; away is the exact complement.
        self.assertIn(">55.3%</strong>", html)
        self.assertIn(">44.7%</strong>", html)
        # Spread is quoted for the favorite (home, tid 0 -> AAA) in half points.
        self.assertIn("AAA -1.5", html)
        # Playoff-odds swing: current PO% -> if-win / if-lose, all one decimal.
        self.assertIn("62.3%", html)   # away current PO
        self.assertIn(">66.0</span>", html)
        self.assertIn(">58.1</span>", html)
        self.assertIn("48.9%", html)   # home current PO
        self.assertIn(">55.2</span>", html)
        self.assertIn(">41.7</span>", html)
        # Team color chips carry each side's chart color.
        self.assertIn(team_chart_color(0), html)
        self.assertIn(team_chart_color(1), html)

    def test_projected_filler_game_renders_static_card_and_pick_line(self):
        # A generated round-robin gid has no game page; the card must not link.
        stub = home.league_sim(None, None, None)
        stub["stakes"][0].update({"gid": "proj-1", "spread": 0.0, "home_wp": 0.5,
                                  "home_po_win": None, "home_po_loss": None})
        home.league_sim = lambda data, teams, season: stub
        data = {"gameAttributes": {"season": 2031, "phase": 1, "numGames": 45}, "games": []}
        html = home.game_projection_cards(data, self._teams(), 2031)
        self.assertIn("gp-static", html)
        self.assertNotIn("<a class=\"gp-card\"", html)
        self.assertNotIn('href="#"', html)
        self.assertIn(">Pick</span>", html)          # dead-even line
        self.assertIn(">50.0%</strong>", html)
        self.assertIn(">—</span>", html)             # missing conditional odds stay honest

    def test_no_stakes_renders_nothing(self):
        home.league_sim = lambda data, teams, season: {"teams": {}, "stakes": [], "day": None, "fresh": False}
        data = {"gameAttributes": {"season": 2031, "phase": 1}, "games": []}
        self.assertEqual(home.game_projection_cards(data, self._teams(), 2031), "")


class TestOffseasonEvents(unittest.TestCase):
    def test_boundary_keeps_offseason_moves_and_drops_in_season_ones(self):
        data = {
            "events": [
                {"type": "freeAgent", "season": 2030, "eid": 5},               # in-season signing
                {"type": "trade", "season": 2030, "eid": 6, "phase": 1},       # deadline trade
                {"type": "trade", "season": 2030, "eid": 7, "phase": 5},       # offseason trade (phase)
                {"type": "playoffs", "season": 2030, "eid": 10},               # boundary marker
                {"type": "freeAgent", "season": 2030, "eid": 12},              # offseason signing
                {"type": "draft", "season": 2030, "eid": 3},                   # draft is always offseason
                {"type": "retired", "season": 2030, "eid": 4},                 # retirement news is excluded
                {"type": "hallOfFame", "season": 2030, "eid": 8},              # HoF news is excluded
                {"type": "freeAgent", "season": 2029, "eid": 99},              # wrong season
                {"type": "injured", "season": 2030, "eid": 13},                # not a transaction
            ]
        }
        eids = [e["eid"] for e in home.offseason_events(data, 2030)]
        self.assertEqual(eids, [3, 7, 12])


class TestPreseasonComposition(unittest.TestCase):
    """The dash-wall acceptance test: a preseason render must not emit the
    zero-data standings/team-stats/award-sentiment tables, and no card may
    emit a dead '#' link."""

    def setUp(self):
        SITE_META.pop("sim", None)
        SITE_META["prev_ranks"] = None
        self._real_league_sim = home.league_sim
        # simulate_league runs 10,000 Monte Carlo sims — stub it for the
        # composition test (its own behavior is covered elsewhere).
        home.league_sim = lambda data, teams, season: {
            "teams": {
                0: {"po": 0.6, "finals": 0.3, "champ": 0.2, "seeds": [0.5, 0.5], "proj_w": 24.0, "games_left": 45},
                1: {"po": 0.4, "finals": 0.2, "champ": 0.1, "seeds": [0.5, 0.5], "proj_w": 21.0, "games_left": 45},
            },
            "stakes": [{"gid": "proj-1", "day": 1, "home_tid": 0, "away_tid": 1,
                        "home_wp": 0.58, "spread": -2.0,
                        "home_po_win": 0.66, "home_po_loss": 0.52,
                        "away_po_win": 0.49, "away_po_loss": 0.33}],
            "day": 1,
            "fresh": True,
        }

    def tearDown(self):
        home.league_sim = self._real_league_sim
        SITE_META.pop("sim", None)

    def _data(self):
        game = {
            "gid": 1, "season": 2030, "day": 3, "playoffs": False,
            "teams": [
                {"tid": 0, "pts": 100, "ptsQtrs": [25, 25, 25, 25], "players": []},
                {"tid": 1, "pts": 90, "ptsQtrs": [22, 23, 22, 23], "players": []},
            ],
        }
        return {
            "gameAttributes": {"season": 2031, "phase": 0, "numGames": 45,
                               "confs": [{"cid": 0, "name": "League"}]},
            "games": [game],
            "events": [
                {"type": "playoffs", "season": 2030, "eid": 10, "text": "Race note."},
                {"type": "freeAgent", "season": 2030, "eid": 12, "pids": [1], "tids": [0],
                 "contract": {"amount": 30000, "exp": 2033}},
            ],
            "players": [],
            "awards": [],
        }

    def test_preseason_page_has_no_dash_walls_and_no_dead_links(self):
        teams = [
            _team(0, "AAA", stats=[_team_stat_row(2030), _team_stat_row(2031, gp=0)],
                  seasons=[{"season": 2030, "won": 30, "lost": 15, "cid": 0},
                           {"season": 2031, "won": 0, "lost": 0, "cid": 0}]),
            _team(1, "BBB", stats=[_team_stat_row(2030), _team_stat_row(2031, gp=0)],
                  seasons=[{"season": 2030, "won": 15, "lost": 30, "cid": 0},
                           {"season": 2031, "won": 0, "lost": 0, "cid": 0}]),
        ]
        html = home.render_home_page(self._data(), teams, [], 2031, 2026, odds_history=[])
        # Phase banner replaces the zero-data cards with one line of copy.
        self.assertIn("hm-banner", html)
        self.assertIn("season hasn't tipped off yet", html)
        # The dash walls are gone.
        self.assertNotIn('id="standings-', html)
        self.assertNotIn('id="team-stats"', html)
        self.assertNotIn('id="award-sentiment"', html)
        # Projection cards for a filler game stay unlinked — never '#'.
        self.assertNotIn('href="#"', html)
        self.assertIn("gp-card", html)
        self.assertIn("Game Projections", html)
        # Team links elsewhere (odds table) still point at real team pages.
        self.assertIn('href="teams/region0-name0-0.html"', html)
        # The offseason digest replaces the empty in-season news feed.
        self.assertIn("Offseason Digest", html)
        # No hollow side-column markup when cards are missing.
        self.assertNotIn('<div class="home-side"></div>', html)


class TestPlayoffOddsPrecision(unittest.TestCase):
    """PO% / Finals% / Title% show one decimal; the ten seed-distribution cells
    round to whole percents while sorting on the full-precision value."""

    def setUp(self):
        self._real_league_sim = home.league_sim
        home.league_sim = lambda data, teams, season: {
            "teams": {
                0: {"po": 0.745, "finals": 0.475, "champ": 0.301, "seeds": [0.62, 0.38], "proj_w": 24.0, "games_left": 40},
                1: {"po": 0.2551, "finals": 0.0004, "champ": 0.0, "seeds": [0.38, 0.62], "proj_w": 21.0, "games_left": 40},
            },
            "stakes": [], "day": 5, "fresh": False,
        }

    def tearDown(self):
        home.league_sim = self._real_league_sim

    def test_headline_odds_have_one_decimal(self):
        teams = [_team(0, "AAA"), _team(1, "BBB")]
        data = {"gameAttributes": {"season": 2031, "phase": 1, "numGames": 45}, "games": []}
        html = home.playoff_odds_card(data, teams, 2031)
        self.assertIn("74.5%", html)
        self.assertIn("47.5%", html)
        self.assertIn("30.1%", html)
        self.assertIn("25.5%", html)     # rounds to one decimal, not an int
        self.assertIn("&lt;0.1%", html)  # trace odds floor, not "0.0%"
        self.assertIn(">—<", html)       # exactly zero stays a dash
        # Seed-distribution cells: compact whole percents, in tight seed cells.
        self.assertIn(">62<", html)
        self.assertIn(">38<", html)
        self.assertNotIn(">62.0<", html)
        self.assertIn('data-sort="62.0"', html)  # sorting keeps the full value
        self.assertIn('class="seed-cell', html)

    def test_odds_pct_formatter(self):
        self.assertEqual(home._odds_pct(0.0), "—")
        self.assertEqual(home._odds_pct(0.04), "&lt;0.1%")
        self.assertEqual(home._odds_pct(0.05), "0.1%")
        self.assertEqual(home._odds_pct(74.5), "74.5%")
        self.assertEqual(home._odds_pct(100.0), "100.0%")

    def test_compact_pct_formatter(self):
        self.assertEqual(home._pct1(0.0), "—")
        self.assertEqual(home._pct1(0.04), "&lt;0.1")
        self.assertEqual(home._pct1(31.44), "31.4")
        self.assertEqual(home._pct1(100.0), "100.0")

    def test_whole_pct_formatter(self):
        self.assertEqual(home._pct0(0.0), "—")        # impossible seed stays a dash
        self.assertEqual(home._pct0(0.4), "&lt;1")    # a trace never rounds down to "0"
        self.assertEqual(home._pct0(31.44), "31")
        self.assertEqual(home._pct0(31.6), "32")
        self.assertEqual(home._pct0(100.0), "100")


class TestHomeFinancesTable(unittest.TestCase):
    """The home finance table reads the ledger defensively and shows payroll
    against the cap anchor. SMP II has no luxury tax and no carried cash, so the
    revenue / budget / surplus columns are gone."""

    def setUp(self):
        self._real_fin = home.compute_league_finances
        self._real_sim = home.league_sim
        home.league_sim = lambda data, teams, season: {"teams": {}}
        self.ledger = {
            "teams": {
                0: {"won": 30, "lost": 15, "payroll": 60000, "cap_room": 40000,
                    "committed_next": 90000},
                1: {"won": 15, "lost": 30, "payroll": 95000, "cap_room": 5000,
                    "committed_next": 105000},
            }
        }
        home.compute_league_finances = lambda *args: self.ledger

    def tearDown(self):
        home.compute_league_finances = self._real_fin
        home.league_sim = self._real_sim

    def _data(self):
        # The cap anchor is read from the export, never a literal.
        return {"gameAttributes": {"salaryCap": 100000, "salaryCapType": "none"}}

    def _teams(self):
        return [_team(0, "AAA"), _team(1, "BBB")]

    def test_columns_and_color_coded_cap_room(self):
        html = home.home_finances_table(self._data(), self._teams(), [], 2031)
        self.assertIn('id="home-finances"', html)
        for header in ("Payroll", "Cap room", "2032 committed", "2032 cap room"):
            self.assertIn(header, html)
        # The cash/tax economy is gone: no revenue, budget or surplus columns.
        for gone in ("Proj revenue", "2032 budget", "Surplus", "Cash on Hand",
                     "bankroll", "Luxury tax"):
            self.assertNotIn(gone, html)
        # Signed, color-coded cap room; team 1 is committed past the anchor next season.
        self.assertIn('<span class="delta-up">+$40M</span>', html)
        self.assertIn('<span class="delta-down">-$5M</span>', html)
        # Sorted by cap room, most room first.
        self.assertLess(html.find("Region0"), html.find("Region1"))

    def test_no_cap_in_export_blanks_the_room_columns(self):
        # An export with no salaryCap has nothing to compare payroll against.
        html = home.home_finances_table({}, self._teams(), [], 2031)
        self.assertIn("$60M", html)
        self.assertIn(">—<", html)
        self.assertNotIn("delta-up", html)

    def test_falls_back_to_legacy_ledger_keys(self):
        # Older ledger shape (payroll_next, no cap_room): the table must still
        # compose the committed column and derive cap room from the cap itself.
        self.ledger = {
            "teams": {
                0: {"won": 20, "lost": 25, "payroll": 88000, "payroll_next": 70000},
            }
        }
        html = home.home_finances_table(self._data(), [_team(0, "AAA")], [], 2031)
        self.assertIn("$88M", html)                                 # payroll
        self.assertIn('<span class="delta-up">+$12M</span>', html)  # room = 100 − 88
        self.assertIn("$70M", html)                                 # 2032 committed
        self.assertIn('<span class="delta-up">+$30M</span>', html)  # 2032 room = 100 − 70


class TestHomeColumns(unittest.TestCase):
    def test_empty_side_collapses_wrapper(self):
        out = home._home_columns(["<section>a</section>"], ["", ""])
        self.assertNotIn("home-side", out)
        self.assertNotIn("home-columns", out)
        self.assertIn("<section>a</section>", out)

    def test_both_sides_render_columns(self):
        out = home._home_columns(["<section>a</section>"], ["<section>b</section>"])
        self.assertIn("home-columns", out)
        self.assertIn("home-main", out)
        self.assertIn("home-side", out)


if __name__ == "__main__":
    unittest.main()
