"""Unit tests for scripts/projections.py (the projection engine).

Stdlib unittest only (pytest is NOT installed). Run from repo root:

    python3 -m unittest discover -s tests

These tests exercise the pure rating math (limit_rating, player_ovr,
player_ovr_vec, team_ovr, coaching_effect) against the league export and
hand-computed values, then check the structural / statistical properties of the
vectorized Monte Carlo development (determinism, shape, bounds, age direction,
and the shared-base_change correlation structure).
"""

import json
import math
import os
import sys
import unittest

import numpy as np

# --- make scripts/ importable -------------------------------------------------
_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_HERE)
_SCRIPTS = os.path.join(_REPO, "scripts")
if _SCRIPTS not in sys.path:
    sys.path.insert(0, _SCRIPTS)

import projections as proj  # noqa: E402
from projections import (  # noqa: E402
    RATINGS,
    bound,
    coaching_effect,
    develop_paths,
    limit_rating,
    percentiles,
    player_ovr,
    player_ovr_vec,
    simulate_player,
    team_ovr,
)

def _export_path():
    override = os.environ.get("CHRONICARIA_TEST_EXPORT")
    if override:
        return override if os.path.isabs(override) else os.path.join(_REPO, override)

    data_dir = os.path.join(_REPO, "league-data")
    candidates = [os.path.join(data_dir, n) for n in os.listdir(data_dir) if n.endswith(".json")]
    if not candidates:
        raise FileNotFoundError("no league-data/*.json fixtures found")
    # Largest export ~= furthest along (most games played); robust to file naming.
    return max(candidates, key=os.path.getsize)


_EXPORT_PATH = _export_path()


def _load_export():
    with open(_EXPORT_PATH) as f:
        return json.load(f)


def _all_keys(row):
    return all(k in row for k in RATINGS)


class TestOvrParity(unittest.TestCase):
    """1. player_ovr must reproduce every stored OVR value (zero mismatches)."""

    @classmethod
    def setUpClass(cls):
        cls.data = _load_export()

    def test_ovr_parity(self):
        players = self.data["players"]
        checked = 0
        mismatches = 0
        first_bad = None
        for p in players:
            for rr in p.get("ratings", []):
                if "ovr" not in rr or not _all_keys(rr):
                    continue
                checked += 1
                got = player_ovr(rr)
                if got != rr["ovr"]:
                    mismatches += 1
                    if first_bad is None:
                        first_bad = (p.get("pid"), rr.get("season"), got, rr["ovr"])
        # The SMP II export is a pre-draft snapshot: one rating row per player,
        # no season history. Guard that the loop actually checked the whole pool
        # rather than silently skipping every row.
        self.assertGreaterEqual(
            checked, len(players), "expected a rating row for every player in export"
        )
        self.assertEqual(
            mismatches,
            0,
            "OVR mismatches: {} of {} checked; first={}".format(
                mismatches, checked, first_bad
            ),
        )


class TestOvrVec(unittest.TestCase):
    """2. Vectorized player_ovr_vec must equal the scalar player_ovr."""

    def test_ovr_vec_matches_scalar_random_batch(self):
        rng = np.random.default_rng(2024)
        batch = rng.integers(0, 101, size=(500, 15)).astype(np.float64)
        vec = player_ovr_vec(batch)
        scal = np.array(
            [player_ovr(dict(zip(RATINGS, row))) for row in batch],
            dtype=np.int64,
        )
        self.assertEqual(vec.shape, (500,))
        self.assertTrue(
            np.array_equal(vec, scal),
            "vec vs scalar mismatches: {}".format(int(np.sum(vec != scal))),
        )

    def test_ovr_vec_matches_scalar_on_export(self):
        data = _load_export()
        rows = []
        for p in data["players"]:
            rr = p["ratings"][-1]
            if _all_keys(rr):
                rows.append([float(rr[k]) for k in RATINGS])
        arr = np.array(rows, dtype=np.float64)
        vec = player_ovr_vec(arr)
        scal = np.array(
            [player_ovr(dict(zip(RATINGS, row))) for row in arr], dtype=np.int64
        )
        self.assertTrue(np.array_equal(vec, scal))

    def test_ovr_vec_multidim(self):
        rng = np.random.default_rng(7)
        batch = rng.integers(0, 101, size=(4, 6, 15)).astype(np.float64)
        vec = player_ovr_vec(batch)
        self.assertEqual(vec.shape, (4, 6))
        # spot-check a few cells against the scalar path
        for i in range(4):
            for j in range(6):
                self.assertEqual(
                    int(vec[i, j]),
                    player_ovr(dict(zip(RATINGS, batch[i, j]))),
                )


class TestLimitRating(unittest.TestCase):
    """3. limit_rating clamps to [0,100] and FLOORS."""

    def test_limit_rating(self):
        self.assertEqual(limit_rating(150), 100)
        self.assertEqual(limit_rating(-5), 0)
        self.assertEqual(limit_rating(73.9), 73)
        self.assertEqual(limit_rating(100.0), 100)
        self.assertEqual(limit_rating(0), 0)
        # extra: floors, never rounds
        self.assertEqual(limit_rating(0.99), 0)
        self.assertEqual(limit_rating(99.999), 99)
        for v in (limit_rating(73.9), limit_rating(100.0), limit_rating(0)):
            self.assertIsInstance(v, int)

    def test_bound(self):
        self.assertEqual(bound(5, 0, 10), 5)
        self.assertEqual(bound(-3, 0, 10), 0)
        self.assertEqual(bound(99, 0, 10), 10)


class TestTeamOvr(unittest.TestCase):
    """4. team_ovr against hand-computed formula, padding, monotonicity."""

    @staticmethod
    def _hand_team_ovr(ovrs, playoffs=False):
        s = sorted((float(o) for o in ovrs), reverse=True)[:10]
        while len(s) < 10:
            s.append(0.0)
        if playoffs:
            a, b, k = 0.6388, -0.2245, 157.43
        else:
            a, b, k = 0.3334, -0.1609, 102.98
        mov = -k
        for i in range(10):
            mov += a * math.exp(b * i) * s[i]
        raw = mov * 50.0 / 15.0 + 50.0
        if playoffs:
            raw -= 40.0
        return int(math.floor(raw + 0.5))

    def test_team_ovr_known_regular(self):
        ovrs = [70, 65, 60, 58, 55, 52, 50, 48, 45, 40]
        expected = self._hand_team_ovr(ovrs, playoffs=False)
        self.assertEqual(team_ovr(ovrs, playoffs=False), expected)

    def test_team_ovr_known_playoffs(self):
        ovrs = [70, 65, 60, 58, 55, 52, 50, 48, 45, 40]
        expected = self._hand_team_ovr(ovrs, playoffs=True)
        self.assertEqual(team_ovr(ovrs, playoffs=True), expected)

    def test_team_ovr_explicit_value(self):
        # Fully hand-computed from the formula for a known input.
        ovrs = [80, 70, 60, 50, 40]  # 5 players, padded to 10 zeros
        a, b, k = 0.3334, -0.1609, 102.98
        mov = -k
        for i, o in enumerate([80, 70, 60, 50, 40, 0, 0, 0, 0, 0]):
            mov += a * math.exp(b * i) * o
        raw = mov * 50.0 / 15.0 + 50.0
        expected = int(math.floor(raw + 0.5))
        self.assertEqual(team_ovr(ovrs), expected)

    def test_team_ovr_padding(self):
        three = [70, 60, 50]
        padded = [70, 60, 50, 0, 0, 0, 0]
        self.assertEqual(team_ovr(three), team_ovr(padded))

    def test_team_ovr_takes_top_10(self):
        # An 11th low player must not change the result (only top 10 count).
        base = [80, 75, 70, 68, 65, 60, 58, 55, 50, 45]
        with_extra = base + [10]
        self.assertEqual(team_ovr(base), team_ovr(with_extra))

    def test_team_ovr_monotonic(self):
        low = [60, 55, 50, 48, 45, 42, 40, 38, 35, 30]
        high = [o + 5 for o in low]
        self.assertGreater(team_ovr(high), team_ovr(low))


class TestCoachingEffect(unittest.TestCase):
    """5. coaching_effect(34) == 0 (DEFAULT_LEVEL)."""

    def test_coaching_effect_default(self):
        self.assertAlmostEqual(coaching_effect(34), 0.0, delta=1e-12)

    def test_coaching_effect_signs(self):
        # Below default level -> negative effect; above -> positive.
        self.assertLess(coaching_effect(1), 0.0)
        self.assertGreater(coaching_effect(100), 0.0)


class TestDeterminism(unittest.TestCase):
    """6. Same seed -> byte-identical; different seed -> not identical."""

    def setUp(self):
        self.r = {k: 50 for k in RATINGS}

    def test_same_seed_identical(self):
        d1 = develop_paths(self.r, 22, 6, 500, seed=12345)
        d2 = develop_paths(self.r, 22, 6, 500, seed=12345)
        self.assertTrue(np.array_equal(d1["ratings"], d2["ratings"]))
        self.assertTrue(np.array_equal(d1["ovr"], d2["ovr"]))

    def test_different_seed_differs(self):
        d1 = develop_paths(self.r, 22, 6, 500, seed=1)
        d2 = develop_paths(self.r, 22, 6, 500, seed=2)
        self.assertFalse(np.array_equal(d1["ratings"], d2["ratings"]))


class TestPathsShape(unittest.TestCase):
    """7. Shape (n_sims, n_years+1, 15) and index 0 == undeveloped start."""

    def test_shape_and_index0(self):
        start = {k: float(40 + i) for i, k in enumerate(RATINGS)}
        n_sims, n_years = 200, 5
        d = develop_paths(start, 24, n_years, n_sims, seed=99)
        self.assertEqual(d["ratings"].shape, (n_sims, n_years + 1, 15))
        self.assertEqual(d["ovr"].shape, (n_sims, n_years + 1))
        base = np.array([start[k] for k in RATINGS], dtype=np.float64)
        # index 0 (undeveloped) equals the start ratings for every sim
        self.assertTrue(np.all(d["ratings"][:, 0, :] == base))
        # and the ovr at index 0 matches player_ovr of the start
        self.assertTrue(np.all(d["ovr"][:, 0] == player_ovr(start)))


class TestRatingsBounded(unittest.TestCase):
    """8. All developed ratings are integers in [0,100]."""

    def test_ratings_bounded_integers(self):
        start = {k: 55 for k in RATINGS}
        d = develop_paths(start, 20, 8, 400, seed=3)
        rat = d["ratings"]
        self.assertTrue(np.all(rat >= 0.0))
        self.assertTrue(np.all(rat <= 100.0))
        # integral (the engine floors every season)
        self.assertTrue(np.all(rat == np.floor(rat)))


class TestAgeDirection(unittest.TestCase):
    """9. Young player improves (median), old player declines (median)."""

    def test_young_improves(self):
        start = {k: 45 for k in RATINGS}
        start_ovr = player_ovr(start)
        sim = simulate_player(start, 19, 2029, seasons_ahead=6, n_sims=600, seed=11)
        self.assertGreaterEqual(sim["ovr"]["p50"][-1], start_ovr)

    def test_old_declines(self):
        start = {k: 60 for k in RATINGS}
        start_ovr = player_ovr(start)
        sim = simulate_player(start, 36, 2029, seasons_ahead=6, n_sims=600, seed=13)
        self.assertLess(sim["ovr"]["p50"][-1], start_ovr)


class TestCorrelationStructure(unittest.TestCase):
    """10. ovr variance reflects the shared base_change component.

    The real engine draws ONE base_change per (sim, season), shared across all
    14 non-hgt ratings, so a good/bad year moves the whole player together and
    inflates the variance of the aggregate OVR. A model that instead draws an
    independent base_change per rating would diversify that noise away and
    produce a materially SMALLER OVR std at a mid horizon. We build that
    independent-per-rating reference locally and assert real_std > ref_std.
    """

    def _independent_per_rating_paths(self, start, start_age, n_years, n_sims, seed):
        """Reference model: base_change drawn INDEPENDENTLY per rating.

        Mirrors develop_paths exactly except base_change has shape
        (n_sims, 14) instead of (n_sims,) -- i.e. no shared-season component.
        """
        rng = np.random.default_rng(seed)
        ce = proj.coaching_effect(34)
        non_hgt = proj._NON_HGT
        non_hgt_idx = proj._NON_HGT_IDX
        base = np.array([float(start[k]) for k in RATINGS], dtype=np.float64)
        ratings = np.empty((n_sims, n_years + 1, 15), dtype=np.float64)
        ratings[:, 0, :] = base
        cur = np.tile(base, (n_sims, 1))
        nkey = len(non_hgt)

        for t in range(1, n_years + 1):
            age = start_age + t
            # height bump (young)
            if age <= 21:
                hr = rng.random(n_sims)
                hgt = cur[:, proj._HGT]
                if age <= 20:
                    hgt = hgt + ((hr > 0.99) & (hgt <= 99)).astype(np.float64)
                hgt = hgt + ((hr > 0.999) & (hgt <= 99)).astype(np.float64)
                cur[:, proj._HGT] = hgt

            age_curve = proj._age_curve_base(age)
            if age <= 23:
                noise = np.clip(rng.normal(0.0, 5.0, (n_sims, nkey)), -4.0, 20.0)
            elif age <= 25:
                noise = np.clip(rng.normal(0.0, 5.0, (n_sims, nkey)), -4.0, 10.0)
            else:
                noise = np.clip(rng.normal(0.0, 3.0, (n_sims, nkey)), -2.0, 4.0)
            base_change = age_curve + noise  # (n_sims, nkey)  <-- per-rating
            sign = np.where(base_change > 0, 1.0, -1.0)
            base_change = base_change * (1.0 + sign * ce)

            umult = rng.uniform(0.4, 1.4, (n_sims, nkey))
            age_mods = np.empty((n_sims, nkey), dtype=np.float64)
            lo = np.empty(nkey, dtype=np.float64)
            hi = np.empty(nkey, dtype=np.float64)
            for j, key in enumerate(non_hgt):
                if key in ("ins", "ft", "fg", "tp", "drb", "pss", "reb"):
                    age_mods[:, j] = proj._shooting_age_mod(age)
                elif key in ("oiq", "diq"):
                    age_mods[:, j] = proj._iq_age_mod(age)
                elif key == "spd":
                    age_mods[:, j] = proj._spd_age_mod(age)
                elif key == "jmp":
                    age_mods[:, j] = proj._jmp_age_mod(age)
                elif key == "dnk":
                    age_mods[:, j] = proj._dnk_age_mod(age)
                elif key == "stre":
                    age_mods[:, j] = 0.0
                elif key == "endu":
                    if age <= 23:
                        age_mods[:, j] = rng.uniform(0.0, 9.0, n_sims)
                    else:
                        age_mods[:, j] = proj._endu_age_mod_old(age)
                if key in ("oiq", "diq"):
                    klo, khi = proj._iq_limits(age)
                else:
                    klo, khi = proj._CONST_LIMITS[key]
                lo[j] = klo
                hi[j] = khi

            delta = base_change * umult + age_mods * umult
            delta = np.clip(delta, lo, hi)
            vals = cur[:, non_hgt_idx] + delta
            vals = np.floor(np.clip(vals, 0.0, 100.0))
            cur[:, non_hgt_idx] = vals
            ratings[:, t, :] = cur

        return player_ovr_vec(ratings)

    def test_shared_base_change_inflates_variance(self):
        start = {k: 50 for k in RATINGS}
        start_age, n_years, n_sims = 22, 5, 4000
        mid = n_years  # use the horizon end (mid->far horizon)

        real = develop_paths(start, start_age, n_years, n_sims, seed=42)["ovr"]
        ref = self._independent_per_rating_paths(
            start, start_age, n_years, n_sims, seed=42
        )

        real_std = float(np.std(real[:, mid]))
        ref_std = float(np.std(ref[:, mid]))
        self.assertGreater(
            real_std,
            ref_std,
            "expected shared base_change to inflate ovr std: "
            "real={:.3f} ref={:.3f}".format(real_std, ref_std),
        )
        # and materially so (not a coincidental sliver)
        self.assertGreater(real_std, ref_std * 1.3)


class TestPercentilesHelper(unittest.TestCase):
    """Sanity check on the percentiles() helper shape/ordering."""

    def test_percentiles_monotone(self):
        rng = np.random.default_rng(0)
        arr = rng.normal(50, 10, (1000, 4))
        out = percentiles(arr)
        for key in ("p10", "p25", "p50", "p75", "p90"):
            self.assertEqual(len(out[key]), 4)
        for j in range(4):
            self.assertLessEqual(out["p10"][j], out["p50"][j])
            self.assertLessEqual(out["p50"][j], out["p90"][j])


class TestTeamOvrPaths(unittest.TestCase):
    """team_ovr_paths must reproduce scalar team_ovr exactly, vectorized."""

    def test_parity_with_scalar(self):
        rng = np.random.default_rng(7)
        mism = 0
        for _ in range(120):
            n_players = int(rng.integers(1, 16))
            n_sims = int(rng.integers(1, 5))
            n_seasons = int(rng.integers(1, 4))
            stack = rng.uniform(0, 100, size=(n_players, n_sims, n_seasons))
            vec = proj.team_ovr_paths(stack)
            for s in range(n_sims):
                for t in range(n_seasons):
                    if proj.team_ovr(list(stack[:, s, t])) != int(vec[s, t]):
                        mism += 1
        self.assertEqual(mism, 0)

    def test_playoffs_parity(self):
        rng = np.random.default_rng(8)
        stack = rng.uniform(0, 100, size=(12, 3, 2))
        vec = proj.team_ovr_paths(stack, playoffs=True)
        for s in range(3):
            for t in range(2):
                self.assertEqual(
                    proj.team_ovr(list(stack[:, s, t]), playoffs=True), int(vec[s, t])
                )

    def test_shape_and_monotonic(self):
        # A uniformly stronger roster yields a >= team OVR everywhere.
        base = np.full((10, 50, 3), 55.0)
        strong = base + 10.0
        tb = proj.team_ovr_paths(base)
        ts = proj.team_ovr_paths(strong)
        self.assertEqual(tb.shape, (50, 3))
        self.assertTrue(np.all(ts >= tb))

    def test_requires_3d(self):
        with self.assertRaises(ValueError):
            proj.team_ovr_paths(np.zeros((10, 5)))


class TestProjectedWinPct(unittest.TestCase):
    """projected_win_pct: round-robin expected win% from team OVRs."""

    def test_equal_strength(self):
        wp = proj.projected_win_pct({1: 90, 2: 90, 3: 90})
        for v in wp.values():
            self.assertAlmostEqual(v, 0.5, delta=1e-9)

    def test_conservation(self):
        # Every game has exactly one winner -> win%s sum to n/2.
        ovrs = {i: 60 + 4 * i for i in range(10)}
        wp = proj.projected_win_pct(ovrs)
        self.assertAlmostEqual(sum(wp.values()), len(ovrs) / 2.0, delta=1e-9)

    def test_monotonic(self):
        ovrs = {"a": 110, "b": 95, "c": 80}
        wp = proj.projected_win_pct(ovrs)
        self.assertGreater(wp["a"], wp["b"])
        self.assertGreater(wp["b"], wp["c"])
        self.assertGreater(wp["a"], 0.5)
        self.assertLess(wp["c"], 0.5)

    def test_single_team(self):
        self.assertEqual(proj.projected_win_pct({1: 100}), {1: 0.5})


if __name__ == "__main__":
    unittest.main(verbosity=2)
