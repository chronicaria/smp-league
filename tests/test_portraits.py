"""Tests for scripts/smp/portraits.py (fixture-based; no identity.py internals,
no network, no real rendered faces)."""

import json
import os
import shutil
import sys
import tempfile
import types
import unittest
from pathlib import Path


_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_HERE)
_SCRIPTS = os.path.join(_REPO, "scripts")
if _SCRIPTS not in sys.path:
    sys.path.insert(0, _SCRIPTS)

from smp import portraits  # noqa: E402


FIXTURE_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 400 600">'
    '<path fill="#F00BA1" d="M0 0h10v10H0z"/>'
    '<path fill="#F00BA2" stroke="#F00BA1" d="M10 0h10v10H10z"/>'
    '<text fill="#F00BA3">00</text>'
    "</svg>"
)

# A face object shaped like the ones facesjs puts in the export. Its contents
# never matter — only that it is a non-empty dict, which is what render.mjs
# needed to draw the rendered SVG in the first place.
FIXTURE_FACE = {"head": {"id": "head1"}, "eyes": [{"id": "eye1"}]}

FALLBACK_IDENTITY = {
    "abbrev": "SMP",
    "primary": "#3A4150",
    "secondary": "#8A93A5",
    "on_primary": "#FFFFFF",
    "chart": "#8A93A5",
}


class _FakeRegistry(dict):
    """Mirrors identity._IdentityRegistry: unknown tids resolve to the fallback."""

    def __missing__(self, key):
        return dict(FALLBACK_IDENTITY)

    def get(self, key, default=None):
        if key in self:
            return dict.__getitem__(self, key)
        return dict(FALLBACK_IDENTITY) if default is None else default


TEAM_IDENTITY = _FakeRegistry(
    {
        2: {
            "abbrev": "CAM",
            "primary": "#2C5545",
            "secondary": "#EAE4C8",
            "on_primary": "#F6F3E4",
            "chart": "#2F8C57",
        },
    }
)


def _fake_identity():
    mod = types.SimpleNamespace()
    mod.TEAM_IDENTITY = TEAM_IDENTITY
    mod.monogram_svg = lambda initials, tid, jersey_number=None, css_class="monogram": (
        '<svg data-monogram="%s" data-tid="%s" data-jersey="%s" data-class="%s"></svg>'
        % (initials, tid, jersey_number, css_class)
    )
    return mod


_UNSET = object()


def _player(pid, first="Test", last="Player", tid=2, img=None, jersey=None, face=_UNSET):
    """A player dict. ``face=None`` omits the key entirely (an export that never
    carried a face for this pid); pass a dict to control it."""
    p = {"pid": pid, "firstName": first, "lastName": last, "tid": tid}
    face = FIXTURE_FACE if face is _UNSET else face
    if face is not None:
        p["face"] = face
    if img is not None:
        p["imgURL"] = img
    if jersey is not None:
        p["jerseyNumber"] = jersey
    return p


class PortraitsFixtureCase(unittest.TestCase):
    """Points portraits at a temp scripts/faces/rendered/ fixture tree."""

    def setUp(self):
        self._tmp = Path(tempfile.mkdtemp(prefix="portraits-test-"))
        self.addCleanup(shutil.rmtree, self._tmp, True)
        self.rendered = self._tmp / "rendered"
        self.rendered.mkdir()
        self.out = self._tmp / "out"

        (self.rendered / "7.svg").write_text(FIXTURE_SVG, encoding="utf-8")
        (self.rendered / "8.svg").write_text(FIXTURE_SVG, encoding="utf-8")
        (self.rendered / "manifest.json").write_text(
            json.dumps({"pids": [7, 8], "sentinels": ["#F00BA1", "#F00BA2", "#F00BA3"]}),
            encoding="utf-8",
        )

        self._orig_dir = portraits.RENDERED_DIR
        self._orig_identity = portraits._identity
        portraits.RENDERED_DIR = self.rendered
        portraits._identity = _fake_identity
        portraits.load_face_manifest.cache_clear()

        def restore():
            portraits.RENDERED_DIR = self._orig_dir
            portraits._identity = self._orig_identity
            portraits.load_face_manifest.cache_clear()

        self.addCleanup(restore)


class TestManifest(PortraitsFixtureCase):
    def test_load_and_has_face(self):
        manifest = portraits.load_face_manifest()
        self.assertEqual(manifest["pids"], frozenset({7, 8}))
        self.assertEqual(manifest["sentinels"], ("#F00BA1", "#F00BA2", "#F00BA3"))
        self.assertTrue(portraits.has_face(_player(7)))
        self.assertFalse(portraits.has_face(_player(999)))
        self.assertFalse(portraits.has_face(None))
        # has_face takes the player, not a bare pid
        self.assertFalse(portraits.has_face(7))

    def test_has_face_requires_a_face_in_this_export(self):
        # pids are league-local: a manifest left over from another league would
        # otherwise paint a stranger's portrait onto whoever holds pid 7 now.
        self.assertFalse(portraits.has_face(_player(7, face=None)))
        self.assertFalse(portraits.has_face(_player(7, face={})))
        self.assertFalse(portraits.has_face(_player(7, face="yes")))
        self.assertFalse(portraits.has_face({"pid": "7", "face": FIXTURE_FACE}))

    def test_manifest_is_cached(self):
        first = portraits.load_face_manifest()
        (self.rendered / "manifest.json").write_text(
            json.dumps({"pids": [], "sentinels": ["#A", "#B", "#C"]}), encoding="utf-8"
        )
        self.assertIs(portraits.load_face_manifest(), first)

    def test_missing_manifest_is_empty(self):
        (self.rendered / "manifest.json").unlink()
        portraits.load_face_manifest.cache_clear()
        manifest = portraits.load_face_manifest()
        self.assertEqual(manifest["pids"], frozenset())
        self.assertFalse(portraits.has_face(_player(7)))


class TestEmitFaces(PortraitsFixtureCase):
    def test_sentinels_swapped_for_team_colors(self):
        portraits.emit_faces(self.out, {7: _player(7, tid=2), 8: _player(8, tid=-1)})
        svg = (self.out / "assets" / "faces" / "7.svg").read_text(encoding="utf-8")
        self.assertNotIn("#F00BA", svg)
        self.assertIn('fill="#2C5545"', svg)  # primary
        self.assertIn('fill="#EAE4C8"', svg)  # secondary
        self.assertIn('stroke="#2C5545"', svg)  # every occurrence swapped
        self.assertIn('fill="#F6F3E4"', svg)  # on_primary
        # Everything else untouched.
        self.assertIn('viewBox="0 0 400 600"', svg)

    def test_free_agent_gets_neutral_grays(self):
        portraits.emit_faces(self.out, {7: _player(7, tid=2), 8: _player(8, tid=-1)})
        svg = (self.out / "assets" / "faces" / "8.svg").read_text(encoding="utf-8")
        self.assertNotIn("#F00BA", svg)
        for gray in portraits.FA_COLORS:
            self.assertIn(gray, svg)

    def test_unknown_tid_gets_the_neutral_fallback_identity(self):
        # An expansion tid the identity table has never heard of resolves to the
        # neutral fallback rather than inheriting another franchise's colors.
        portraits.emit_faces(self.out, {8: _player(8, tid=42)})
        svg = (self.out / "assets" / "faces" / "8.svg").read_text(encoding="utf-8")
        self.assertNotIn("#F00BA", svg)
        self.assertIn(FALLBACK_IDENTITY["primary"], svg)
        self.assertNotIn(TEAM_IDENTITY[2]["primary"], svg)

    def test_player_missing_from_the_export_is_skipped(self):
        # pid 7 is in the manifest but not in this export at all.
        portraits.emit_faces(self.out, {8: _player(8)})
        self.assertFalse((self.out / "assets" / "faces" / "7.svg").exists())
        self.assertTrue((self.out / "assets" / "faces" / "8.svg").exists())

    def test_player_without_a_face_in_this_export_is_skipped(self):
        # Same has_face provenance gate the pages use: emitting a face no page
        # can reach would just be a stale manifest leaking into the output.
        portraits.emit_faces(self.out, {7: _player(7, face=None), 8: _player(8)})
        self.assertFalse((self.out / "assets" / "faces" / "7.svg").exists())
        self.assertTrue((self.out / "assets" / "faces" / "8.svg").exists())

    def test_accepts_player_iterable(self):
        portraits.emit_faces(self.out, [_player(7, tid=2), _player(8, tid=-1)])
        svg = (self.out / "assets" / "faces" / "7.svg").read_text(encoding="utf-8")
        self.assertIn("#2C5545", svg)

    def test_idempotent_only_writes_changed_files(self):
        players = {7: _player(7, tid=2), 8: _player(8, tid=-1)}
        portraits.emit_faces(self.out, players)
        path = self.out / "assets" / "faces" / "7.svg"
        before = path.read_text(encoding="utf-8")
        os.utime(path, (1, 1))  # sentinel mtime; a rewrite would bump it
        portraits.emit_faces(self.out, players)
        self.assertEqual(path.stat().st_mtime, 1)
        self.assertEqual(path.read_text(encoding="utf-8"), before)
        # A changed input DOES rewrite.
        portraits.emit_faces(self.out, {7: _player(7, tid=-1)})
        self.assertIn(portraits.FA_COLORS[0], path.read_text(encoding="utf-8"))

    def test_missing_source_svg_is_skipped(self):
        # Both players are present and faced; only the source file has drifted.
        (self.rendered / "8.svg").unlink()
        portraits.emit_faces(self.out, {7: _player(7, tid=2), 8: _player(8, tid=2)})
        self.assertTrue((self.out / "assets" / "faces" / "7.svg").exists())
        self.assertFalse((self.out / "assets" / "faces" / "8.svg").exists())


class TestPortraitHtml(PortraitsFixtureCase):
    def test_photo_wins(self):
        html = portraits.portrait_html(
            _player(7, "Ana", "Boone", img="https://cdn.example/x.png"), "hero-pic", "../", 96
        )
        self.assertIn('src="https://cdn.example/x.png"', html)
        self.assertIn('class="hero-pic"', html)
        self.assertIn('alt="Ana Boone"', html)
        self.assertIn('loading="lazy"', html)
        self.assertIn('decoding="async"', html)
        self.assertIn('width="96"', html)
        self.assertIn('height="96"', html)
        # onerror hook class + fallback to the face SVG this pid has.
        self.assertIn("portrait-broken", html)
        self.assertIn("this.src='../assets/faces/7.svg'", html)

    def test_photo_without_face_swaps_to_monogram_on_error(self):
        html = portraits.portrait_html(_player(999, img="https://cdn.example/x.png"))
        # dead photo with no face SVG: onerror replaces the img with the
        # percent-encoded monogram markup so the slot never renders empty
        self.assertIn("this.outerHTML=decodeURIComponent(", html)
        self.assertIn("portrait-monogram", html)  # encoded payload decodes to it
        self.assertNotIn("assets/faces/", html)

    def test_stale_manifest_pid_never_borrows_the_face(self):
        # pid 7 owns a rendered SVG, but this export's pid 7 carries no face, so
        # it is a different player: monogram, never assets/faces/7.svg.
        stale = _player(7, "Cy", "Dunn", face=None)
        self.assertNotIn("assets/faces/", portraits.portrait_html(stale))
        self.assertIn(
            "portrait-monogram",
            portraits.portrait_html(_player(7, "Cy", "Dunn", face=None,
                                            img="https://cdn.example/x.png")),
        )

    def test_face_when_no_photo(self):
        html = portraits.portrait_html(_player(8, "Bo", "Cruz"), "portrait", "../../", 48)
        self.assertIn('src="../../assets/faces/8.svg"', html)
        self.assertIn('alt="Bo Cruz"', html)
        self.assertIn('width="48"', html)
        self.assertNotIn("onerror", html)

    def test_blank_img_url_falls_through_to_face(self):
        html = portraits.portrait_html(_player(7, img="  "))
        self.assertIn("assets/faces/7.svg", html)

    def test_monogram_when_no_photo_or_face(self):
        html = portraits.portrait_html(_player(999, "Cy", "Dunn", tid=2, jersey="11"), size=40)
        self.assertIn('data-monogram="CD"', html)
        self.assertIn('data-tid="2"', html)
        self.assertIn('data-jersey="11"', html)
        self.assertIn('aria-label="Cy Dunn"', html)
        self.assertIn('role="img"', html)
        self.assertNotIn("<img", html)

    def test_alt_text_is_escaped_player_name(self):
        html = portraits.portrait_html(_player(7, 'A"B', "C", img="https://cdn.example/x.png"))
        self.assertIn("alt=\"A&quot;B C\"", html)


if __name__ == "__main__":
    unittest.main()
