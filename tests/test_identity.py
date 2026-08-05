"""Tests for scripts/smp/identity.py (TEAM_IDENTITY registry + SVG builders)."""

import json
import os
import sys
import unittest
import xml.etree.ElementTree as ET


_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_HERE)
_SCRIPTS = os.path.join(_REPO, "scripts")
if _SCRIPTS not in sys.path:
    sys.path.insert(0, _SCRIPTS)

from smp import identity  # noqa: E402


_EXPORT = os.path.join(_REPO, "league-data", "2004_predraft.json")

# TEAM_IDENTITY is process-global and any build (core.normalize_positions) re-keys
# it from whatever export that build loaded. Other test modules load real exports,
# so pin the registry back to the compiled-in defaults for this module and hand it
# back untouched afterwards -- otherwise these tests pass or fail on module order.
_LEAKED_REGISTRY = None


def setUpModule():
    global _LEAKED_REGISTRY
    _LEAKED_REGISTRY = dict(identity.TEAM_IDENTITY)
    _restore_default_registry()


def tearDownModule():
    identity.TEAM_IDENTITY.clear()
    identity.TEAM_IDENTITY.update(_LEAKED_REGISTRY)


def _restore_default_registry():
    identity.TEAM_IDENTITY.clear()
    identity.TEAM_IDENTITY.update(
        (tid, identity._make_identity(abbrev))
        for tid, abbrev in enumerate(identity._DEFAULT_TID_ABBREVS)
    )


_HEX = frozenset("0123456789ABCDEFabcdef")


def _is_hex_color(value):
    return (
        isinstance(value, str)
        and value.startswith("#")
        and len(value) == 7
        and all(c in _HEX for c in value[1:])
    )


def _parse_svg(markup):
    """Round-trip through an XML parser; raises if the SVG is malformed."""
    return ET.fromstring(markup)


class TestRegistry(unittest.TestCase):
    def test_registry_complete_for_tids_0_through_9(self):
        for tid in range(10):
            self.assertIn(tid, identity.TEAM_IDENTITY)
            ident = identity.TEAM_IDENTITY[tid]
            for key in ("primary", "secondary", "chart", "on_primary"):
                self.assertTrue(
                    _is_hex_color(ident[key]),
                    "tid %d key %s not a hex color: %r" % (tid, key, ident[key]),
                )
            self.assertEqual(len(ident["abbrev"]), 3)
            self.assertEqual(ident["abbrev"], ident["abbrev"].upper())

    def test_expected_abbrevs(self):
        # SMP II kept all ten franchises but renumbered eight of ten tids, and
        # Queens' abbrev moved QNS -> QUE.
        expected = ["ROC", "WAL", "CAM", "DUR", "TOR", "ITH", "GOO", "MAN", "STO", "QUE"]
        got = [identity.TEAM_IDENTITY[t]["abbrev"] for t in range(10)]
        self.assertEqual(got, expected)

    def test_defaults_match_the_real_exports_tid_mapping(self):
        # The compiled-in default keying is only useful if it agrees with the
        # export a build actually loads before register_team_identities runs.
        if not os.path.exists(_EXPORT):
            self.skipTest("2004 pre-draft export not present")
        with open(_EXPORT, encoding="utf-8") as fh:
            teams = json.load(fh)["teams"]
        mapping = {t["tid"]: t["abbrev"].upper() for t in teams}
        self.assertEqual(
            mapping, {t: identity.TEAM_IDENTITY[t]["abbrev"] for t in range(10)}
        )

    def test_every_franchise_has_its_own_hue_family(self):
        # Colors belong to a franchise, not a tid slot: each abbrev appears once
        # and no two teams share a primary/secondary/chart color.
        abbrevs = [identity.TEAM_IDENTITY[t]["abbrev"] for t in range(10)]
        self.assertEqual(len(set(abbrevs)), 10)
        for key in ("primary", "secondary", "chart"):
            colors = [identity.TEAM_IDENTITY[t][key] for t in range(10)]
            self.assertEqual(len(set(colors)), 10, "duplicate %s color" % key)

    def test_unknown_tid_falls_back_without_crashing(self):
        for tid in (10, 99, -1, None):
            ident = identity.TEAM_IDENTITY[tid]
            self.assertEqual(ident, identity.FALLBACK_IDENTITY)
            self.assertTrue(_is_hex_color(ident["primary"]))
        # .get is fallback-aware too
        self.assertEqual(identity.TEAM_IDENTITY.get(42), identity.FALLBACK_IDENTITY)
        # fallback lookups must not pollute the registry
        self.assertNotIn(99, identity.TEAM_IDENTITY)
        self.assertEqual(sorted(dict.keys(identity.TEAM_IDENTITY)), list(range(10)))

    def test_fallback_copies_are_independent(self):
        a = identity.team_identity(1234)
        a["primary"] = "#000000"
        self.assertEqual(identity.team_identity(1234)["primary"],
                         identity.FALLBACK_IDENTITY["primary"])


class TestRegisterTeamIdentities(unittest.TestCase):
    """The curated table is keyed by abbrev; a build re-keys it by the export's tids."""

    def setUp(self):
        snapshot = dict(identity.TEAM_IDENTITY)

        def restore():
            identity.TEAM_IDENTITY.clear()
            identity.TEAM_IDENTITY.update(snapshot)

        self.addCleanup(restore)

    def test_rekeys_by_the_exports_own_tids(self):
        identity.register_team_identities(
            [{"tid": 5, "abbrev": "ROC"}, {"tid": 0, "abbrev": "que"}]
        )
        self.assertEqual(identity.TEAM_IDENTITY[5]["abbrev"], "ROC")
        self.assertEqual(identity.TEAM_IDENTITY[0]["abbrev"], "QUE")
        self.assertEqual(sorted(dict.keys(identity.TEAM_IDENTITY)), [0, 5])
        # tids no longer in the export fall back rather than keeping stale colors
        self.assertEqual(identity.team_identity(9), identity.FALLBACK_IDENTITY)

    def test_a_franchise_keeps_its_colors_across_a_renumber(self):
        before = dict(identity.TEAM_IDENTITY[0])  # ROC at tid 0 by default
        identity.register_team_identities([{"tid": 7, "abbrev": "ROC"}])
        self.assertEqual(identity.TEAM_IDENTITY[7], before)

    def test_unknown_abbrev_falls_through_to_fallback(self):
        identity.register_team_identities(
            [{"tid": 0, "abbrev": "ROC"}, {"tid": 1, "abbrev": "XPN"}]
        )
        self.assertNotIn(1, identity.TEAM_IDENTITY)
        self.assertEqual(identity.team_identity(1), identity.FALLBACK_IDENTITY)

    def test_unusable_input_keeps_compiled_in_defaults(self):
        before = dict(identity.TEAM_IDENTITY)
        for teams in (None, [], [{"tid": 0, "abbrev": "XPN"}], ["not a dict"],
                      [{"tid": True, "abbrev": "ROC"}], [{"abbrev": "ROC"}]):
            identity.register_team_identities(teams)
            self.assertEqual(dict(identity.TEAM_IDENTITY), before, "clobbered by %r" % (teams,))


class TestValidation(unittest.TestCase):
    def test_validate_identity_passes(self):
        self.assertTrue(identity.validate_identity())

    def test_on_primary_contrast_meets_aa(self):
        for tid in range(10):
            ident = identity.TEAM_IDENTITY[tid]
            ratio = identity.contrast_ratio(ident["on_primary"], ident["primary"])
            self.assertGreaterEqual(
                ratio, 4.5, "tid %d contrast %.2f below AA" % (tid, ratio)
            )

    def test_chart_colors_pairwise_distinct(self):
        charts = [identity.TEAM_IDENTITY[t]["chart"] for t in range(10)]
        self.assertEqual(len(set(charts)), 10)
        for i in range(10):
            for j in range(i + 1, 10):
                d = identity._chart_distance(charts[i], charts[j])
                self.assertGreaterEqual(
                    d,
                    identity.CHART_DISTINCT_MIN,
                    "tids %d/%d chart colors too close (%.1f)" % (i, j, d),
                )

    def test_contrast_ratio_sanity(self):
        self.assertAlmostEqual(identity.contrast_ratio("#FFFFFF", "#000000"), 21.0, places=1)
        self.assertAlmostEqual(identity.contrast_ratio("#123456", "#123456"), 1.0, places=3)


class TestCssVars(unittest.TestCase):
    def test_team_css_vars_fragment(self):
        frag = identity.team_css_vars(0)
        ident = identity.TEAM_IDENTITY[0]
        for var, key in (
            ("--team-primary", "primary"),
            ("--team-secondary", "secondary"),
            ("--team-on-primary", "on_primary"),
            ("--team-chart", "chart"),
        ):
            self.assertIn("%s:%s" % (var, ident[key]), frag)
        self.assertNotIn('"', frag)  # must be safe inside style="..."

    def test_team_css_vars_fallback_tid(self):
        frag = identity.team_css_vars(777)
        self.assertIn("--team-primary:%s" % identity.FALLBACK_IDENTITY["primary"], frag)

    def test_team_chart_color(self):
        self.assertEqual(identity.team_chart_color(7), identity.TEAM_IDENTITY[7]["chart"])
        self.assertEqual(identity.team_chart_color(500), identity.FALLBACK_IDENTITY["chart"])

    def test_chart_palette_is_the_chart_colors_in_abbrev_order(self):
        palette = identity.chart_palette()
        by_abbrev = {
            identity.TEAM_IDENTITY[t]["abbrev"]: identity.TEAM_IDENTITY[t]["chart"]
            for t in range(10)
        }
        self.assertEqual(palette, [by_abbrev[a] for a in sorted(by_abbrev)])
        self.assertEqual(len(set(palette)), len(palette))


class TestMonogram(unittest.TestCase):
    def test_monogram_is_valid_svg_with_team_vars(self):
        svg = identity.monogram_svg("ROC", 0)
        root = _parse_svg(svg)
        self.assertTrue(root.tag.endswith("svg"))
        # The palette is free to change; the wiring is not.
        self.assertIn("--team-primary:%s" % identity.TEAM_IDENTITY[0]["primary"], svg)
        self.assertIn("var(--team-primary)", svg)
        self.assertIn("var(--team-on-primary)", svg)
        self.assertIn(">ROC</text>", svg)
        self.assertIn('viewBox="0 0 64 64"', svg)
        # sized by CSS class, not fixed pixels
        self.assertNotIn("width=", svg.split(">")[0])
        self.assertIn('class="monogram"', svg)

    def test_monogram_jersey_number_and_class(self):
        svg = identity.monogram_svg("AB", 4, jersey_number=23, css_class="monogram monogram--lg")
        _parse_svg(svg)
        self.assertIn(">23</text>", svg)
        self.assertIn('class="monogram monogram--lg"', svg)
        # no jersey bubble when omitted
        plain = identity.monogram_svg("AB", 4)
        self.assertNotIn(">23</text>", plain)

    def test_monogram_escapes_and_truncates(self):
        svg = identity.monogram_svg('<x>&"', 1)
        _parse_svg(svg)
        self.assertNotIn("<x>", svg)

    def test_monogram_fallback_tid_and_empty_text(self):
        svg = identity.monogram_svg("", 999)
        _parse_svg(svg)
        self.assertIn(">?</text>", svg)
        self.assertIn("--team-primary:%s" % identity.FALLBACK_IDENTITY["primary"], svg)


class TestCrests(unittest.TestCase):
    def test_all_twelve_plus_kinds_render_valid_svg(self):
        self.assertGreaterEqual(len(identity.CREST_KINDS), 12)
        for kind in identity.CREST_KINDS:
            svg = identity.crest_svg(kind)
            root = _parse_svg(svg)
            self.assertTrue(root.tag.endswith("svg"))
            self.assertIn("currentColor", svg)
            self.assertIn('class="crest crest-%s"' % kind, svg)
            self.assertIn('viewBox="0 0 24 24"', svg)
            self.assertIn("aria-label=", svg)
            # tintable: no hardcoded hex colors inside crests
            self.assertNotIn("#", svg.replace("&#", ""))

    def test_crest_custom_class(self):
        svg = identity.crest_svg("mvp", css_class="crest crest--gold")
        self.assertIn('class="crest crest--gold"', svg)

    def test_unknown_crest_kind_raises(self):
        with self.assertRaises(KeyError):
            identity.crest_svg("nope")


if __name__ == "__main__":
    unittest.main()
