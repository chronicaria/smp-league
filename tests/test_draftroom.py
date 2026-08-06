"""Tests for the League Draft page (scripts/smp/pages/draftroom.py).

Covers the two things the room actually reads: the snake board (who is on the clock,
which slots are filled) and the pool's default ordering, which follows the league's
own exported board rather than raw overall.
"""

import json
import os
import sys
import tempfile
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_HERE)
_SCRIPTS = os.path.join(_REPO, "scripts")
if _SCRIPTS not in sys.path:
    sys.path.insert(0, _SCRIPTS)

from smp.core import (  # noqa: E402
    current_season,
    free_agents,
    latest_rating,
    normalize_positions,
    player_name,
    team_sort_key,
)
from smp.pages import draftroom as dr  # noqa: E402

_EXPORT = os.path.join(_REPO, "league-data", "2004_predraft.json")
_BOARD = os.path.join(_REPO, "league-data", dr.BOARD_ORDER_FILE)

_CSV = "#,Name,Pos,Ovr\n1,Bench Warmer,SG,55\n2,Star Player,SF,80\n"


def _player(pid, first, last, ovr=60, pot=60, tid=-1):
    return {
        "pid": pid, "firstName": first, "lastName": last, "tid": tid,
        "retiredYear": None, "born": {"year": 1980},
        "contract": {"amount": 5000, "exp": 2007},
        "ratings": [{"season": 2004, "pos": "SF", "ovr": ovr, "pot": pot}],
        "stats": [],
    }


class TestBoardOrderFile(unittest.TestCase):
    def test_row_order_is_the_ranking(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, dr.BOARD_ORDER_FILE)
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(_CSV)
            self.assertEqual(dr.load_board_order(path), {"Bench Warmer": 0, "Star Player": 1})

    def test_utf8_bom_and_accents_survive(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, dr.BOARD_ORDER_FILE)
            with open(path, "w", encoding="utf-8-sig") as fh:
                fh.write("#,Name\n1,Peja Stojaković\n")
            self.assertEqual(dr.load_board_order(path), {"Peja Stojaković": 0})

    def test_a_missing_board_is_not_an_error(self):
        self.assertEqual(dr.load_board_order(None), {})
        self.assertEqual(dr.load_board_order("/nonexistent/board.csv"), {})

    def test_unlisted_players_sort_after_the_board(self):
        order = {"Star Player": 0}
        listed = _player(1, "Star", "Player")
        unlisted = _player(2, "Someone", "Else")
        self.assertLess(dr.board_rank(listed, order), dr.board_rank(unlisted, order))


class TestPoolOrdering(unittest.TestCase):
    def test_board_order_beats_overall(self):
        # The board says the 55 goes first; the pool must not re-sort by ovr.
        players = [_player(1, "Star", "Player", ovr=80), _player(2, "Bench", "Warmer", ovr=55)]
        order = {"Bench Warmer": 0, "Star Player": 1}
        html = dr.pool_html(players, 2004, order=order)
        self.assertLess(html.index("Bench Warmer"), html.index("Star Player"))
        self.assertIn("league board order", html)

    def test_falls_back_to_overall_without_a_board(self):
        players = [_player(1, "Star", "Player", ovr=80), _player(2, "Bench", "Warmer", ovr=55)]
        html = dr.pool_html(players, 2004)
        self.assertLess(html.index("Star Player"), html.index("Bench Warmer"))
        self.assertIn("by overall", html)

    def test_top_of_the_board_uses_the_same_order(self):
        players = [_player(1, "Star", "Player", ovr=80), _player(2, "Bench", "Warmer", ovr=55)]
        order = {"Bench Warmer": 0, "Star Player": 1}
        html = dr.top_board_html(players, 2004, order=order)
        self.assertLess(html.index("Bench Warmer"), html.index("Star Player"))

    def test_top_of_the_board_is_one_row(self):
        # The strip is meant to be a single row; league.css lays out exactly this
        # many columns, so the two numbers have to stay in step.
        pool = [_player(i, "Player", str(i), ovr=80 - i) for i in range(40)]
        html = dr.top_board_html(pool, 2004)
        self.assertEqual(html.count('class="fa-card"'), dr.TOP_BOARD_CARDS)
        self.assertEqual(dr.TOP_BOARD_CARDS, 8)
        with open(os.path.join(_REPO, "scripts", "smp", "static", "css", "league.css"),
                  encoding="utf-8") as fh:
            self.assertIn(f"repeat({dr.TOP_BOARD_CARDS}, minmax(0, 1fr))", fh.read())


class TestShippedBoardMatchesTheExport(unittest.TestCase):
    """The board file and the league JSON have to name the same people."""

    @classmethod
    def setUpClass(cls):
        with open(_EXPORT, encoding="utf-8") as fh:
            cls.data = json.load(fh)
        normalize_positions(cls.data)
        cls.season = current_season(cls.data)
        cls.order = dr.load_board_order(_BOARD)

    def test_every_board_name_exists_in_the_export(self):
        names = {f"{p['firstName']} {p['lastName']}".strip() for p in self.data["players"]}
        self.assertTrue(self.order)
        self.assertEqual(sorted(set(self.order) - names), [])

    def test_undrafted_players_are_all_on_the_board(self):
        # Anyone still unsigned should have a board slot; only drafted players drop off.
        missing = [f"{p['firstName']} {p['lastName']}".strip()
                   for p in self.data["players"]
                   if p["tid"] < 0 and f"{p['firstName']} {p['lastName']}".strip() not in self.order]
        self.assertEqual(missing, [])

    def test_board_order_outranks_overall_somewhere_in_the_live_pool(self):
        """The board is not just an ovr sort — find a live pair where they disagree.

        Derived from whoever is still unsigned rather than named players, so the
        assertion survives draft night instead of failing every time a pick lands.
        """
        pool = free_agents(self.data)
        by_rank = sorted(pool, key=lambda p: dr.board_rank(p, self.order))
        pairs = [(a, b) for a, b in zip(by_rank, by_rank[1:])
                 if latest_rating(a, self.season)["ovr"] < latest_rating(b, self.season)["ovr"]]
        self.assertTrue(pairs, "board order is indistinguishable from an overall sort")
        ahead, behind = pairs[0]
        html = dr.pool_html(pool, self.season, order=self.order)
        self.assertLess(html.index(player_name(ahead)), html.index(player_name(behind)))


class TestBoardSlots(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(_EXPORT, encoding="utf-8") as fh:
            cls.data = json.load(fh)
        normalize_positions(cls.data)
        cls.season = current_season(cls.data)
        cls.teams = sorted(cls.data["teams"], key=team_sort_key)

    def _picks_made(self):
        """(round, pick) -> "Team Player", straight from the export."""
        by_tid = {t["tid"]: t for t in self.teams}
        out = {}
        for p in self.data["players"]:
            d = p.get("draft") or {}
            if d.get("round", 0) >= 1 and p["tid"] >= 0:
                out[(d["round"], d["pick"])] = (by_tid[d["tid"]]["abbrev"], player_name(p))
        return out

    def test_every_recorded_pick_shows_in_its_slot(self):
        picks = self._picks_made()
        self.assertTrue(picks, "no picks recorded in the export")
        html = dr.board_html(self.data, self.teams, self.season)
        for (rnd, pick), (abbrev, name) in sorted(picks.items()):
            slot = html.split(f'title="Round {rnd}, pick {pick} ')[1].split("</td>")[0]
            self.assertIn(name, slot)
            self.assertIn(abbrev, slot)
        self.assertIn(f"{len(picks)} of 120 picks made", html)

    def test_rochester_holds_the_first_overall_pick(self):
        self.assertEqual(self._picks_made().get((1, 1)), ("ROC", "Andrei Kirilenko"))

    def test_drafted_players_leave_the_pool(self):
        html = dr.pool_html(free_agents(self.data), self.season)
        for _, name in self._picks_made().values():
            self.assertNotIn(name, html)


if __name__ == "__main__":
    unittest.main()
