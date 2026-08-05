"""TEAM_IDENTITY registry: team colors, css-var emission, monograms, award crests.

Hand-curated brand colors (colors only — no logo images, per league rules), and
the site's single source of team color: charts, dots, css vars and recolored
faces all resolve here. Unknown tids get a neutral slate identity so future
expansion teams never crash the build.

The curated table is keyed by ABBREV because colors belong to a franchise, not
to a slot in the teams array — SMP II kept all ten names but renumbered eight of
ten tids. ``register_team_identities`` re-keys it by tid from the export itself.

Public API (other modules code against this):
    TEAM_IDENTITY: dict[int, dict]   keys: primary, secondary, chart, on_primary, abbrev
    register_team_identities(teams)  re-key TEAM_IDENTITY from the export's tids
    team_identity(tid) -> dict       fallback-aware lookup (never raises)
    team_css_vars(tid) -> str        style-attr fragment with --team-* variables
    team_chart_color(tid) -> str
    chart_palette() -> list[str]     chart colors in abbrev order
    monogram_svg(text, tid, jersey_number=None, css_class="monogram") -> str
    crest_svg(kind, css_class=None) -> str
    validate_identity() -> True      raises AssertionError on contrast/distinctness fail
"""

from __future__ import annotations

import html
import math
import colorsys
from typing import Any, Dict, Optional

# ---------------------------------------------------------------------------
# Color math helpers (local on purpose — identity.py stays dependency-free)
# ---------------------------------------------------------------------------

_NEAR_BLACK = "#10131A"  # matches the site's dark bg family better than pure black
_WHITE = "#FFFFFF"

# Minimum pairwise chart-color distance (weighted-HSL heuristic, see
# _chart_distance). Tuned so clearly-confusable hues fail and everything the
# eye separates at line-chart weight passes.
CHART_DISTINCT_MIN = 24.0


def _hex_to_rgb(color: str) -> tuple:
    c = color.lstrip("#")
    if len(c) == 3:
        c = "".join(ch * 2 for ch in c)
    return tuple(int(c[i : i + 2], 16) for i in (0, 2, 4))


def _rel_luminance(color: str) -> float:
    def chan(v: int) -> float:
        s = v / 255.0
        return s / 12.92 if s <= 0.04045 else ((s + 0.055) / 1.055) ** 2.4

    r, g, b = _hex_to_rgb(color)
    return 0.2126 * chan(r) + 0.7152 * chan(g) + 0.0722 * chan(b)


def contrast_ratio(a: str, b: str) -> float:
    """WCAG 2.x contrast ratio between two hex colors (>= 1.0)."""
    la, lb = _rel_luminance(a), _rel_luminance(b)
    if la < lb:
        la, lb = lb, la
    return (la + 0.05) / (lb + 0.05)


def _pick_on_color(bg: str) -> str:
    """White or near-black, whichever contrasts more against bg."""
    if contrast_ratio(_WHITE, bg) >= contrast_ratio(_NEAR_BLACK, bg):
        return _WHITE
    return _NEAR_BLACK


def _chart_distance(a: str, b: str) -> float:
    """Weighted-HSL perceptual distance heuristic between two hex colors.

    Hue difference (degrees) weighted 1.2, lightness (0-100) weighted 1.6,
    saturation (0-100) weighted 0.6 — lightness dominates because it is what
    survives both themes and color-vision deficiencies.
    """
    ra = tuple(v / 255.0 for v in _hex_to_rgb(a))
    rb = tuple(v / 255.0 for v in _hex_to_rgb(b))
    ha, la, sa = colorsys.rgb_to_hls(*ra)
    hb, lb, sb = colorsys.rgb_to_hls(*rb)
    dh = min(abs(ha - hb), 1.0 - abs(ha - hb)) * 360.0
    dl = abs(la - lb) * 100.0
    ds = abs(sa - sb) * 100.0
    return math.sqrt((dh * 1.2) ** 2 + (dl * 1.6) ** 2 + (ds * 0.6) ** 2)


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

# abbrev -> (primary, secondary, chart). on_primary is computed below.
# ONE HUE FAMILY PER TEAM, deliberately.
#
# The SMP I table put five of ten primaries in the same dark-navy band (DUR #1B2440,
# ITH #232F55, GOO #1F2E4E, MAN #1C3557, QUE #23305A) so half the league looked
# identical on team pages, dots and headers. Every primary below now sits in its own
# hue family -- blue, teal, green, gold, brown, red, magenta, purple, slate, and one
# deliberately achromatic near-black -- and the chart colors are spread even wider,
# because those are what the scatter and the standings dots actually key on.
_BASE = {
    "TOR": ("#1D4F91", "#7FB2E5", "#3B82F6"),   # blue
    "CAM": ("#0F766E", "#7FD8CF", "#14B8A6"),   # teal
    "STO": ("#15803D", "#86E5A4", "#22C55E"),   # green
    "ITH": ("#8A6508", "#FFD23F", "#EAB308"),   # gold
    "WAL": ("#7A3E12", "#E0A76B", "#8B5A2B"),   # brown
    "GOO": ("#B01818", "#FF9A9A", "#EF4444"),   # red
    "ROC": ("#9D174D", "#F9A8C8", "#EC4899"),   # magenta
    "MAN": ("#6B21A8", "#D4A5F5", "#A855F7"),   # purple
    "QUE": ("#455A70", "#B9C7D6", "#93A9C0"),   # slate
    "DUR": ("#242A31", "#E0531F", "#F97316"),   # near-black w/ orange accent
}

# SMP II's tid assignment, in tid order — the compiled-in default so the module
# is usable before a build registers the export's own mapping.
_DEFAULT_TID_ABBREVS = ("ROC", "WAL", "CAM", "DUR", "TOR", "ITH", "GOO", "MAN", "STO", "QUE")

# Neutral slate identity for unknown tids (expansion teams, FA/retired sentinels).
FALLBACK_IDENTITY: Dict[str, Any] = {
    "abbrev": "SMP",
    "primary": "#3A4150",
    "secondary": "#8A93A5",
    "chart": "#8A93A5",
    "on_primary": _pick_on_color("#3A4150"),
}


class _IdentityRegistry(dict):
    """dict keyed by tid; unknown tids resolve to a copy of FALLBACK_IDENTITY."""

    def __missing__(self, key: Any) -> Dict[str, Any]:
        return dict(FALLBACK_IDENTITY)

    def get(self, key: Any, default: Any = None) -> Any:  # keep .get fallback-aware
        if key in self:
            return dict.__getitem__(self, key)
        return dict(FALLBACK_IDENTITY) if default is None else default


def _make_identity(abbrev: str) -> Dict[str, Any]:
    primary, secondary, chart = _BASE[abbrev]
    return {
        "abbrev": abbrev,
        "primary": primary,
        "secondary": secondary,
        "chart": chart,
        "on_primary": _pick_on_color(primary),
    }


TEAM_IDENTITY: Dict[int, Dict[str, Any]] = _IdentityRegistry(
    (tid, _make_identity(abbrev)) for tid, abbrev in enumerate(_DEFAULT_TID_ABBREVS)
)


def register_team_identities(teams: Any) -> None:
    """Re-key TEAM_IDENTITY from the export's own tid -> abbrev mapping.

    Run once per build (from core.normalize_positions) before anything renders.
    Teams whose abbrev is not in the curated table are simply left out and fall
    through to FALLBACK_IDENTITY, so an expansion franchise never crashes and
    never inherits somebody else's colors.
    """
    mapped: Dict[int, Dict[str, Any]] = {}
    for team in teams or []:
        if not isinstance(team, dict):
            continue
        tid = team.get("tid")
        abbrev = str(team.get("abbrev") or "").strip().upper()
        if isinstance(tid, int) and not isinstance(tid, bool) and abbrev in _BASE:
            mapped[tid] = _make_identity(abbrev)
    if not mapped:
        return  # no usable abbrevs in the export: keep the compiled-in defaults
    TEAM_IDENTITY.clear()
    TEAM_IDENTITY.update(mapped)


def team_identity(tid: Any) -> Dict[str, Any]:
    """Fallback-aware identity lookup. Never raises."""
    return TEAM_IDENTITY[tid]


def team_css_vars(tid: Any) -> str:
    """Style-attribute fragment carrying the team's --team-* custom properties."""
    ident = team_identity(tid)
    return (
        "--team-primary:{primary};--team-secondary:{secondary};"
        "--team-on-primary:{on_primary};--team-chart:{chart}".format(**ident)
    )


def team_chart_color(tid: Any) -> str:
    return team_identity(tid)["chart"]


def chart_palette() -> list[str]:
    """The curated chart colors in abbrev order.

    For the handful of charts that color a series by a team's position in an
    abbrev-sorted list rather than by tid; indexing this with that position
    hands each team its own identity color.
    """
    return [_BASE[abbrev][2] for abbrev in sorted(_BASE)]


# ---------------------------------------------------------------------------
# Monogram roundel (portrait fallback)
# ---------------------------------------------------------------------------


def monogram_svg(
    initials_or_abbrev: str,
    tid: Any,
    jersey_number: Optional[Any] = None,
    css_class: str = "monogram",
) -> str:
    """Roundel SVG: team-primary disc, secondary ring, on-primary initials.

    Sized entirely by CSS (viewBox only — no fixed pixels); pass css_class to
    pick a size class from identity.css (.monogram, .monogram--sm, --lg, --xl).
    Optional jersey_number renders as a small secondary-colored bubble.
    """
    text = str(initials_or_abbrev or "").strip()[:3].upper() or "?"
    font = {1: 26, 2: 22, 3: 17}[len(text)]
    parts = [
        '<svg class="{cls}" viewBox="0 0 64 64" style="{vars}" '
        'aria-hidden="true" focusable="false" xmlns="http://www.w3.org/2000/svg">'.format(
            cls=html.escape(css_class, quote=True), vars=team_css_vars(tid)
        ),
        '<circle cx="32" cy="32" r="31" fill="var(--team-primary)"/>',
        '<circle cx="32" cy="32" r="28.5" fill="none" '
        'stroke="var(--team-secondary)" stroke-width="2"/>',
        '<text x="32" y="33.5" text-anchor="middle" dominant-baseline="central" '
        'font-family="\'Helvetica Neue\',Helvetica,Arial,sans-serif" '
        'font-weight="700" font-size="{f}" letter-spacing=".5" '
        'fill="var(--team-on-primary)">{t}</text>'.format(f=font, t=html.escape(text)),
    ]
    if jersey_number is not None and str(jersey_number).strip() != "":
        num = html.escape(str(jersey_number).strip()[:2])
        parts.append(
            '<circle cx="49" cy="49" r="11" fill="var(--team-secondary)"/>'
            '<text x="49" y="50" text-anchor="middle" dominant-baseline="central" '
            'font-family="\'Helvetica Neue\',Helvetica,Arial,sans-serif" '
            'font-weight="700" font-size="11" '
            'fill="var(--team-primary)">{n}</text>'.format(n=num)
        )
    parts.append("</svg>")
    return "".join(parts)


# ---------------------------------------------------------------------------
# Award crests — hand-drawn 24x24 symbols, single color via currentColor.
# Subtle depth comes from opacity layers only, so callers tint with CSS color.
# ---------------------------------------------------------------------------


def _star_path(cx: float, cy: float, r_outer: float, r_inner: float, points: int = 5) -> str:
    """Closed path for an upright star centered at (cx, cy)."""
    coords = []
    for i in range(points * 2):
        r = r_outer if i % 2 == 0 else r_inner
        ang = math.pi / points * i - math.pi / 2.0
        coords.append((cx + r * math.cos(ang), cy + r * math.sin(ang)))
    d = "M" + "L".join("{:.2f} {:.2f}".format(x, y) for x, y in coords) + "Z"
    return d


def _sparkle_path(cx: float, cy: float, r: float) -> str:
    """4-point concave sparkle (rookie 'new star' motif)."""
    q = r * 0.28
    return (
        "M{cx} {t}Q{qx1} {qy1} {r_} {cy}Q{qx1} {qy2} {cx} {b}"
        "Q{qx2} {qy2} {l} {cy}Q{qx2} {qy1} {cx} {t}Z"
    ).format(
        cx="{:.2f}".format(cx),
        cy="{:.2f}".format(cy),
        t="{:.2f}".format(cy - r),
        b="{:.2f}".format(cy + r),
        l="{:.2f}".format(cx - r),
        r_="{:.2f}".format(cx + r),
        qx1="{:.2f}".format(cx + q),
        qx2="{:.2f}".format(cx - q),
        qy1="{:.2f}".format(cy - q),
        qy2="{:.2f}".format(cy + q),
    )


_LAUREL = (
    '<path d="M5.2 21c-2.6-2.6-3.6-6.9-2.4-10.6" fill="none" stroke="currentColor" '
    'stroke-width="1.5" stroke-linecap="round" opacity=".75"/>'
    '<path d="M18.8 21c2.6-2.6 3.6-6.9 2.4-10.6" fill="none" stroke="currentColor" '
    'stroke-width="1.5" stroke-linecap="round" opacity=".75"/>'
    '<circle cx="3.4" cy="13.6" r="1.1" opacity=".55"/>'
    '<circle cx="4.1" cy="17.3" r="1.1" opacity=".55"/>'
    '<circle cx="20.6" cy="13.6" r="1.1" opacity=".55"/>'
    '<circle cx="19.9" cy="17.3" r="1.1" opacity=".55"/>'
)

_SHIELD_D = "M12 2l8 3v6.2c0 5-3.3 8.7-8 10.8-4.7-2.1-8-5.8-8-10.8V5z"


def _numeral(n: int) -> str:
    return (
        '<text x="12" y="14.9" text-anchor="middle" dominant-baseline="central" '
        'font-family="\'Helvetica Neue\',Helvetica,Arial,sans-serif" '
        'font-weight="700" font-size="9.5" fill="currentColor">{n}</text>'.format(n=n)
    )


CREST_KINDS = (
    "mvp",
    "dpoy",
    "roy",
    "mip",
    "smoy",
    "finals_mvp",
    "sfmvp",
    "all_league_1",
    "all_league_2",
    "all_league_3",
    "all_defensive",
    "all_rookie",
    "champion",
)

_CREST_LABELS = {
    "mvp": "Most Valuable Player",
    "dpoy": "Defensive Player of the Year",
    "roy": "Rookie of the Year",
    "mip": "Most Improved Player",
    "smoy": "Sixth Man of the Year",
    "finals_mvp": "Finals MVP",
    "sfmvp": "Semifinals MVP",
    "all_league_1": "All-League First Team",
    "all_league_2": "All-League Second Team",
    "all_league_3": "All-League Third Team",
    "all_defensive": "All-Defensive Team",
    "all_rookie": "All-Rookie Team",
    "champion": "League Champion",
}

_CREST_BODIES = {
    # Star on a plinth, faint halo behind — the headline individual award.
    "mvp": (
        '<circle cx="12" cy="10.6" r="8.8" opacity=".14"/>'
        '<path d="{star}"/>'
        '<rect x="7.2" y="19.6" width="9.6" height="2" rx="1" opacity=".6"/>'.format(
            star=_star_path(12, 10.6, 7.4, 2.9)
        )
    ),
    # Filled shield with a bright inner keep.
    "dpoy": (
        '<path d="{sh}" opacity=".3"/>'
        '<path d="{sh}" fill="none" stroke="currentColor" stroke-width="1.6"/>'
        '<path d="M12 6.2l4.6 1.7v3.6c0 2.9-1.9 5.1-4.6 6.4-2.7-1.3-4.6-3.5-4.6-6.4V7.9z"/>'.format(
            sh=_SHIELD_D
        )
    ),
    # A new star ascending: big sparkle plus trailing small ones.
    "roy": (
        '<path d="{big}"/>'
        '<path d="{s1}" opacity=".6"/>'
        '<path d="{s2}" opacity=".4"/>'.format(
            big=_sparkle_path(13.6, 9.2, 6.8),
            s1=_sparkle_path(5.6, 16.4, 2.8),
            s2=_sparkle_path(8.6, 5.0, 2.0),
        )
    ),
    # Rising trend line with an arrowhead.
    "mip": (
        '<path d="M3 18.5l5.2-5.2 3.6 3.6 8-8" fill="none" stroke="currentColor" '
        'stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"/>'
        '<path d="M14.6 8.2h5.6v5.6" fill="none" stroke="currentColor" '
        'stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"/>'
        '<circle cx="3" cy="18.5" r="1.6" opacity=".5"/>'
    ),
    # Torch: spark off the bench. Asymmetric flame + inner lick + handle.
    "smoy": (
        '<path d="M13.4 1.5c1.4 2.4.4 4-.9 5.7-1.2 1.6-2.6 2.9-2.6 4.9'
        'a2.5 2.5 0 0 0 .3 1.2c-1-.5-1.7-1.6-1.9-2.9-.7 1-1.1 1.9-1.1 3.1'
        'a4.9 4.9 0 0 0 9.8 0c0-2-.9-3.3-1.8-4.8-.9-1.6-1.9-3.9-1.8-7.2z"/>'
        '<path d="M12.3 9.6c.1 1.7-1.9 2.5-1.9 4.4a2.2 2.2 0 0 0 4.4 0c0-1.8-1.4-2.3-2.5-4.4z" '
        'opacity=".38"/>'
        '<rect x="10.9" y="17.8" width="2.2" height="4.6" rx="1" opacity=".6"/>'
    ),
    # Star wreathed in laurel — the championship-round MVP.
    "finals_mvp": '<path d="{star}"/>{laurel}'.format(
        star=_star_path(12, 11.4, 5.8, 2.3), laurel=_LAUREL
    ),
    # Star over a chevron — one round shy of the Finals.
    "sfmvp": (
        '<path d="{star}"/>'
        '<path d="M6 17.4l6 3.4 6-3.4" fill="none" stroke="currentColor" '
        'stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" opacity=".7"/>'.format(
            star=_star_path(12, 9.6, 6.2, 2.45)
        )
    ),
    # Shield outline with a star inside.
    "all_defensive": (
        '<path d="{sh}" fill="none" stroke="currentColor" stroke-width="1.7"/>'
        '<path d="{star}"/>'.format(sh=_SHIELD_D, star=_star_path(12, 11.2, 4.6, 1.85))
    ),
    # Hexagonal badge with a sparkle — the freshman honor roll.
    "all_rookie": (
        '<path d="M12 2.2l8.3 4.8v9.6L12 21.4l-8.3-4.8V7z" opacity=".22"/>'
        '<path d="M12 2.2l8.3 4.8v9.6L12 21.4l-8.3-4.8V7z" fill="none" '
        'stroke="currentColor" stroke-width="1.6"/>'
        '<path d="{sp}"/>'.format(sp=_sparkle_path(12, 11.8, 5.2))
    ),
    # Trophy cup with handles and base.
    "champion": (
        '<path d="M7.6 2.8h8.8v5.4a4.4 4.4 0 0 1-8.8 0z"/>'
        '<path d="M7.6 4H4.4v1.6a3.6 3.6 0 0 0 3.4 3.6M16.4 4h3.2v1.6a3.6 3.6 0 0 1-3.4 3.6" '
        'fill="none" stroke="currentColor" stroke-width="1.5"/>'
        '<path d="M10.9 12.4h2.2v3h-2.2z" opacity=".7"/>'
        '<rect x="7.6" y="15.4" width="8.8" height="2.1" rx=".8" opacity=".8"/>'
        '<rect x="6.2" y="19" width="11.6" height="2.2" rx=".8" opacity=".5"/>'
    ),
}

# All-League 1/2/3: laurel + numeral, ring weight fading with team number.
for _n, _op in ((1, "1"), (2, ".72"), (3, ".5")):
    _CREST_BODIES["all_league_{n}".format(n=_n)] = (
        '<g opacity="{op}">{laurel}</g>'
        '<circle cx="12" cy="12.2" r="6.1" opacity=".18"/>'
        '<circle cx="12" cy="12.2" r="6.1" fill="none" stroke="currentColor" '
        'stroke-width="1.5" opacity="{op}"/>{num}'.format(
            op=_op, laurel=_LAUREL, num=_numeral(_n)
        )
    )
del _n, _op


def crest_svg(kind: str, css_class: Optional[str] = None) -> str:
    """Inline SVG crest for an award. Tint via CSS `color` (uses currentColor).

    Unknown kinds raise KeyError listing the valid kinds.
    """
    if kind not in _CREST_BODIES:
        raise KeyError(
            "unknown crest kind {k!r}; valid kinds: {v}".format(
                k=kind, v=", ".join(CREST_KINDS)
            )
        )
    cls = "crest crest-{k}".format(k=kind) if css_class is None else css_class
    return (
        '<svg class="{cls}" viewBox="0 0 24 24" role="img" '
        'aria-label="{label}" fill="currentColor" '
        'xmlns="http://www.w3.org/2000/svg"><title>{label}</title>{body}</svg>'
    ).format(
        cls=html.escape(cls, quote=True),
        label=html.escape(_CREST_LABELS[kind], quote=True),
        body=_CREST_BODIES[kind],
    )


# ---------------------------------------------------------------------------
# Build-time validation
# ---------------------------------------------------------------------------


def validate_identity() -> bool:
    """Assert AA contrast and chart distinctness. Raises AssertionError on fail.

    Checks the curated table itself, so it holds no matter how the export
    numbers its tids.
    """
    abbrevs = sorted(_BASE)
    idents = {abbrev: _make_identity(abbrev) for abbrev in abbrevs}
    for abbrev in abbrevs:
        ident = idents[abbrev]
        ratio = contrast_ratio(ident["on_primary"], ident["primary"])
        assert ratio >= 4.5, (
            "{a}: on_primary {o} on primary {p} contrast {r:.2f} < 4.5".format(
                a=abbrev, o=ident["on_primary"], p=ident["primary"], r=ratio,
            )
        )
    fb_ratio = contrast_ratio(FALLBACK_IDENTITY["on_primary"], FALLBACK_IDENTITY["primary"])
    assert fb_ratio >= 4.5, "fallback identity fails AA contrast: {r:.2f}".format(r=fb_ratio)

    charts = {abbrev: idents[abbrev]["chart"] for abbrev in abbrevs}
    assert len(set(charts.values())) == len(charts), "duplicate chart colors"
    for i, a in enumerate(abbrevs):
        for b in abbrevs[i + 1 :]:
            d = _chart_distance(charts[a], charts[b])
            assert d >= CHART_DISTINCT_MIN, (
                "chart colors too close: {a} {ca} vs {b} {cb} "
                "(distance {d:.1f} < {m})".format(
                    a=a, ca=charts[a], b=b, cb=charts[b], d=d, m=CHART_DISTINCT_MIN
                )
            )
    return True
