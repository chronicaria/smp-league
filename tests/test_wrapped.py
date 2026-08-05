"""Tests for scripts/smp/pages/wrapped.py (SMP Wrapped)."""

import os
import shutil
import sys
import tempfile
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_HERE)
_SCRIPTS = os.path.join(_REPO, "scripts")
if _SCRIPTS not in sys.path:
    sys.path.insert(0, _SCRIPTS)

from smp.pages import wrapped  # noqa: E402


def _team(tid, abbrev, seasons=None):
    return {
        "tid": tid,
        "abbrev": abbrev,
        "region": "Test",
        "name": abbrev.title(),
        "seasons": seasons or [],
    }


def _season_row(season, won=30, lost=15, playoff_rounds_won=-1, att=100000):
    return {
        "season": season,
        "won": won,
        "lost": lost,
        "playoffRoundsWon": playoff_rounds_won,
        "att": att,
    }


def _series(home_tid, home_seed, home_won, away_tid, away_seed, away_won):
    return {
        "home": {"tid": home_tid, "cid": 0, "seed": home_seed, "won": home_won},
        "away": {"tid": away_tid, "cid": 0, "seed": away_seed, "won": away_won},
    }


def _synthetic_data(phase, season=2027, champion_decided=True):
    """Two-team league: 2026 playoffs finished (tid 0 champs), 2027 in flight."""
    teams = [
        _team(0, "AAA", seasons=[
            _season_row(2026, won=35, lost=10, playoff_rounds_won=1),
            _season_row(2027, won=20, lost=5, playoff_rounds_won=1 if champion_decided else 0),
        ]),
        _team(1, "BBB", seasons=[
            _season_row(2026, won=25, lost=20, playoff_rounds_won=0),
            _season_row(2027, won=15, lost=10, playoff_rounds_won=0),
        ]),
    ]
    return {
        "gameAttributes": {"season": season, "phase": phase},
        "teams": teams,
        "players": [],
        "games": [],
        "playoffSeries": [
            {"season": 2026, "currentRound": 0, "series": [[_series(0, 1, 3, 1, 2, 1)]]},
            {"season": 2027, "currentRound": 0, "series": [[_series(0, 1, 2, 1, 2, 2)]]},
        ],
    }


class TestSeasonGating(unittest.TestCase):
    def test_real_export_newest_completed_season(self):
        self.assertEqual(wrapped.newest_completed_season(_REAL_DATA), 2030)

    def test_preseason_phase_caps_at_prior_season(self):
        # 2027 export still in the regular season: only 2026 is complete.
        data = _synthetic_data(phase=1, champion_decided=True)
        self.assertEqual(wrapped.newest_completed_season(data), 2026)

    def test_post_lottery_phase_unlocks_current_season(self):
        data = _synthetic_data(phase=4, champion_decided=True)
        self.assertEqual(wrapped.newest_completed_season(data), 2027)

    def test_undecided_playoffs_fall_back_to_last_complete_season(self):
        # Phase says done but no team banked enough playoffRoundsWon -> not complete.
        data = _synthetic_data(phase=4, champion_decided=False)
        self.assertEqual(wrapped.newest_completed_season(data), 2026)

    def test_no_playoffs_ever_renders_empty_state(self):
        data = {"gameAttributes": {"season": 2026, "phase": 0}, "teams": [], "players": [], "games": []}
        self.assertIsNone(wrapped.newest_completed_season(data))
        html = wrapped.render_wrapped_page(data, [])
        self.assertIn("empty-state", html)
        self.assertIn("Wrapped", html)
        self.assertNotIn("wr-deck", html)


class TestLabels(unittest.TestCase):
    def test_playoff_result_labels(self):
        self.assertEqual(wrapped.playoff_result_label(-1, 2), "Missed the playoffs")
        self.assertEqual(wrapped.playoff_result_label(0, 2), "Semifinals exit")
        self.assertEqual(wrapped.playoff_result_label(1, 2), "Runners-up")
        self.assertEqual(wrapped.playoff_result_label(2, 2), "League champions")
        self.assertEqual(wrapped.playoff_result_label(0, 3), "Quarterfinals exit")

    def test_round_names(self):
        self.assertEqual(wrapped._round_name(1, 2), "Finals")
        self.assertEqual(wrapped._round_name(0, 2), "Semifinals")
        self.assertEqual(wrapped._round_name(0, 1), "Finals")


class TestRenderedPage(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = wrapped.render_wrapped_page(_REAL_DATA, _REAL_TEAMS)

    def test_one_slide_per_team_plus_story_slides(self):
        self.assertEqual(self.html.count("wr-slide-team"), 10)
        for slide_id in ("wr-title", "wr-numbers", "wr-fantasy",
                        "wr-leaders", "wr-playoffs", "wr-champion", "wr-outro"):
            self.assertIn(f'id="{slide_id}"', self.html)
        # P6-H3: attendance and development-riser slides were removed.
        self.assertNotIn('id="wr-risers"', self.html)
        self.assertNotIn("fans in the stands", self.html)
        # Leaders wall no longer includes a Threes entry; no ESPN mentions.
        self.assertNotIn("3PM/G", self.html)
        self.assertNotIn("ESPN", self.html)

    def test_champion_and_share_cards_linked(self):
        self.assertIn("Cambridge Platypuses", self.html)
        self.assertEqual(self.html.count('href="assets/wrapped/2030-'), 10)
        self.assertIn("Save / share card", self.html)

    def test_wrapped_season_is_computed_not_current(self):
        # The export is the 2031 preseason; Wrapped must recap completed 2030.
        self.assertIn("SMP Wrapped 2030", self.html)
        self.assertIn("Season 2030", self.html)

    def test_deterministic(self):
        self.assertEqual(self.html, wrapped.render_wrapped_page(_REAL_DATA, _REAL_TEAMS))


class TestShareCards(unittest.TestCase):
    def test_cards_are_standalone_and_deterministic(self):
        tmp_a = tempfile.mkdtemp()
        tmp_b = tempfile.mkdtemp()
        try:
            paths_a = wrapped.emit_wrapped_cards(tmp_a, _REAL_DATA, _REAL_TEAMS)
            paths_b = wrapped.emit_wrapped_cards(tmp_b, _REAL_DATA, _REAL_TEAMS)
            self.assertEqual(len(paths_a), 10)
            self.assertEqual([p.name for p in paths_a], [p.name for p in paths_b])
            for path_a, path_b in zip(paths_a, paths_b):
                svg = path_a.read_text(encoding="utf-8")
                self.assertEqual(svg, path_b.read_text(encoding="utf-8"))
                # Standalone: fixed viewBox, hardcoded colors, no site CSS vars,
                # no external references beyond the SVG namespace.
                self.assertTrue(svg.startswith("<svg "))
                self.assertIn('viewBox="0 0 1200 630"', svg)
                self.assertNotIn("var(", svg)
                self.assertNotIn("class=", svg)
                self.assertNotIn("http", svg.replace("http://www.w3.org/2000/svg", ""))
                self.assertIn("SMP WRAPPED", svg)
        finally:
            shutil.rmtree(tmp_a, ignore_errors=True)
            shutil.rmtree(tmp_b, ignore_errors=True)

    def test_no_cards_before_first_completed_season(self):
        data = {"gameAttributes": {"season": 2026, "phase": 0}, "teams": [], "players": [], "games": []}
        tmp = tempfile.mkdtemp()
        try:
            self.assertEqual(wrapped.emit_wrapped_cards(tmp, data, []), [])
            self.assertFalse(os.path.exists(os.path.join(tmp, "assets", "wrapped")))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


def _load_real_export():
    import json

    from smp.core import current_season, normalize_positions, team_sort_key

    # Wrapped recaps a COMPLETED season. The SMP II export is a pre-draft snapshot
    # with no season behind it, so the real-data fixture is SMP I's final export,
    # archived under league-data/smp1/.
    path = os.path.join(_REPO, "league-data", "smp1", "2031_preseason.json")
    with open(path, "r", encoding="utf-8") as handle:
        data = json.load(handle)
    normalize_positions(data)
    teams = sorted(data.get("teams", []), key=team_sort_key)
    assert current_season(data) >= 2031
    return data, teams


_REAL_DATA, _REAL_TEAMS = _load_real_export()


if __name__ == "__main__":
    unittest.main()
