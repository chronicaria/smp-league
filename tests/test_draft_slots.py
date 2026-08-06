"""Draft slots: turning what an export records back into "4.07".

A ROOKIE draft stamps the slot straight onto ``player["draft"]``. A FANTASY draft --
which is what an SMP redraft is -- does not touch that object at all, and records the
pick only as a transaction carrying an OVERALL pick number. Both have to come out the
same way on a roster's Acquired column.
"""

import json
import os
import sys
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_HERE)
_SCRIPTS = os.path.join(_REPO, "scripts")
if _SCRIPTS not in sys.path:
    sys.path.insert(0, _SCRIPTS)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from current_export import load_current_export  # noqa: E402

from smp.core import (  # noqa: E402
    SITE_META,
    acquisition_html,
    draft_slot,
    fmt_draft_slot,
    register_site_meta,
    team_sort_key,
)

FANTASY, ROOKIE, EXPANSION = -1, 5, -2


def _drafted(overall, phase=FANTASY, season=2004, tid=0, draft_year=1998):
    """A player recorded the way the named draft phase records one."""
    return {
        "pid": 1, "firstName": "Test", "lastName": "Player", "tid": tid,
        "retiredYear": None, "born": {"year": 1980}, "stats": [],
        "ratings": [{"season": season, "pos": "SF", "ovr": 60, "pot": 60}],
        # Untouched by a fantasy draft: his real-life draft, years before this league.
        "draft": {"round": 0, "pick": 0, "tid": -1, "originalTid": -1, "year": draft_year},
        "transactions": [{"season": season, "phase": phase, "tid": tid,
                          "type": "draft", "pickNum": overall}],
    }


class TestDraftSlot(unittest.TestCase):
    def test_overall_pick_becomes_round_and_pick(self):
        self.assertEqual(draft_slot(_drafted(1), 10), (1, 1))
        self.assertEqual(draft_slot(_drafted(10), 10), (1, 10))
        self.assertEqual(draft_slot(_drafted(11), 10), (2, 1))
        self.assertEqual(draft_slot(_drafted(37), 10), (4, 7))
        self.assertEqual(draft_slot(_drafted(120), 10), (12, 10))

    def test_round_size_is_respected(self):
        self.assertEqual(draft_slot(_drafted(37), 12), (4, 1))
        self.assertEqual(draft_slot(_drafted(37), 6), (7, 1))

    def test_a_stamped_rookie_slot_wins_over_the_transaction(self):
        player = _drafted(37, phase=ROOKIE)
        player["draft"].update({"round": 2, "pick": 3, "year": 2004})
        self.assertEqual(draft_slot(player, 10), (2, 3))

    def test_expansion_draft_is_not_a_draft_slot(self):
        self.assertIsNone(draft_slot(_drafted(4, phase=EXPANSION), 10))

    def test_undraftable_inputs_give_none(self):
        self.assertIsNone(draft_slot({}, 10))
        self.assertIsNone(draft_slot(_drafted(0), 10))          # no pick number
        self.assertIsNone(draft_slot(_drafted(37), 0))          # no round size

    def test_formatting_zero_pads_the_pick_only(self):
        self.assertEqual(fmt_draft_slot((4, 7)), "4.07")
        self.assertEqual(fmt_draft_slot((12, 10)), "12.10")
        self.assertEqual(fmt_draft_slot(None), "")


class TestAcquiredColumn(unittest.TestCase):
    def setUp(self):
        self._season, self._size = SITE_META.get("season"), SITE_META.get("draft_round_size")
        SITE_META["season"], SITE_META["draft_round_size"] = 2004, 10

        def restore():
            SITE_META["season"], SITE_META["draft_round_size"] = self._season, self._size
        self.addCleanup(restore)

    def test_reads_as_round_and_pick_not_an_overall_number(self):
        html = acquisition_html(_drafted(37), {})
        self.assertIn("Draft &#x27;04 4.07", html)
        self.assertNotIn("#37", html)

    def test_a_redrafted_veteran_is_not_blanked_by_his_real_draft_year(self):
        # The old rule required the transaction's season to equal player.draft.year,
        # which no redrafted veteran can satisfy — it blanked the whole league.
        self.assertIn("4.07", acquisition_html(_drafted(37, draft_year=1998), {}))

    def test_expansion_draft_still_shows_nothing(self):
        self.assertNotIn("Draft", acquisition_html(_drafted(4, phase=EXPANSION), {}))

    def test_smp1_inaugural_seeding_draft_still_shows_nothing(self):
        SITE_META["season"] = 2026
        self.assertNotIn("Draft", acquisition_html(_drafted(4, season=2026), {}))


class TestAgainstTheLiveExport(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.path, cls.data = load_current_export()
        register_site_meta(cls.data)
        cls.teams = sorted(cls.data["teams"], key=team_sort_key)

    def test_round_size_is_the_number_of_teams(self):
        self.assertEqual(SITE_META["draft_round_size"], len(self.teams))

    def test_every_rostered_player_has_a_slot_and_they_are_all_distinct(self):
        rostered = [p for p in self.data["players"] if p["tid"] >= 0]
        slots = [draft_slot(p) for p in rostered]
        self.assertTrue(rostered)
        self.assertNotIn(None, slots, "a rostered player has no draft slot")
        self.assertEqual(len(set(slots)), len(slots), "two players share a slot")

    def test_slots_cover_the_snake_exactly(self):
        # A finished redraft fills every slot: no gaps, no strays past the last round.
        rostered = [p for p in self.data["players"] if p["tid"] >= 0]
        rounds, remainder = divmod(len(rostered), len(self.teams))
        self.assertEqual(remainder, 0, "rosters are not an even number of rounds")
        self.assertEqual(
            {draft_slot(p) for p in rostered},
            {(r, pick) for r in range(1, rounds + 1) for pick in range(1, len(self.teams) + 1)})

    def test_the_first_overall_pick_reads_as_1_01(self):
        first = next(p for p in self.data["players"]
                     if p["tid"] >= 0 and draft_slot(p) == (1, 1))
        self.assertIn("Draft &#x27;04 1.01", acquisition_html(first, {}))


if __name__ == "__main__":
    unittest.main()
