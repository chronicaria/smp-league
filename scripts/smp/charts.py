from __future__ import annotations

import json
import math
from typing import Any

from .core import safe_float, safe_int

from .simmodel import PROJ_N_SIMS, PROJ_SEASONS_AHEAD, _player_projection


def ratings_progress_svg(player: dict[str, Any]) -> str:
    ratings = sorted(
        [r for r in player.get("ratings", []) if isinstance(r.get("season"), int)],
        key=lambda r: r["season"],
    )
    if len(ratings) < 1:
        return ""
    seasons = [r["season"] for r in ratings]
    ovr = [safe_float(r.get("ovr")) for r in ratings]
    pot = [safe_float(r.get("pot")) for r in ratings]
    lo = max(0.0, min(min(ovr), min(pot)) - 4)
    hi = min(100.0, max(max(ovr), max(pot)) + 4)
    width, height = 640, 170
    ml, mr, mt, mb = 34, 12, 10, 24
    plot_w, plot_h = width - ml - mr, height - mt - mb

    def x(i: int) -> float:
        return ml + (i / max(1, len(seasons) - 1)) * plot_w

    def y(v: float) -> float:
        return mt + plot_h - ((v - lo) / max(1e-9, hi - lo)) * plot_h

    grid = []
    step = 10 if hi - lo > 25 else 5
    tick = math.ceil(lo / step) * step
    while tick <= hi:
        gy = y(tick)
        grid.append(f'<line x1="{ml}" y1="{gy:.1f}" x2="{ml + plot_w}" y2="{gy:.1f}" class="chart-grid"/>')
        grid.append(f'<text x="{ml - 6}" y="{gy + 3.5:.1f}" class="chart-tick" text-anchor="end">{int(tick)}</text>')
        tick += step
    for i, season in enumerate(seasons):
        grid.append(f'<text x="{x(i):.1f}" y="{height - 8}" class="chart-tick" text-anchor="middle">{season}</text>')

    def line(values: list[float], cls: str) -> str:
        points = " ".join(f"{x(i):.1f},{y(v):.1f}" for i, v in enumerate(values))
        dots = "".join(
            f'<circle cx="{x(i):.1f}" cy="{y(v):.1f}" r="3" class="{cls}-dot"><title>{seasons[i]}: {int(v)}</title></circle>'
            for i, v in enumerate(values)
        )
        return f'<polyline points="{points}" class="{cls}"/>{dots}'

    return f"""
    <section class="card">
      <div class="section-title-row">
        <h2>Development</h2>
        <span class="muted small-copy"><span class="chart-key chart-key-ovr"></span> Overall · <span class="chart-key chart-key-pot"></span> Potential</span>
      </div>
      <svg viewBox="0 0 {width} {height}" class="dev-chart" role="img" aria-label="Overall and potential by season">
        {''.join(grid)}
        {line(pot, "line-pot")}
        {line(ovr, "line-ovr")}
      </svg>
    </section>
    """


def development_chart_html(player: dict[str, Any], season: int, proj: dict[str, Any] | None = None) -> str:
    """Historical overall/potential plus a Monte Carlo overall projection.

    Renders a static SVG fan chart (always visible -- progressive enhancement);
    site.js layers an interactive hover readout on top from the embedded JSON.
    Falls back to the static :func:`ratings_progress_svg` when no projection is
    available. ``proj`` may be passed in (computed once per player by the caller)
    to avoid recomputing the simulation for each projection-backed section.
    """
    if proj is None:
        proj = _player_projection(player, season)
    if proj is None:
        return ratings_progress_svg(player)

    sim = proj["sim"]
    cur_season = proj["cur_season"]

    hist = sorted(
        [r for r in player.get("ratings", [])
         if isinstance(r.get("season"), int) and r["season"] <= cur_season
         and r.get("ovr") is not None],
        key=lambda r: r["season"],
    )
    if not hist:
        return ratings_progress_svg(player)

    hist_seasons = [int(r["season"]) for r in hist]
    hist_ovr = [safe_float(r.get("ovr")) for r in hist]
    # Missing potential falls back to the overall, so a malformed upstream row
    # never renders as a spurious crash-to-zero on the line (pot is >= ovr).
    hist_pot = [safe_float(r.get("pot")) if r.get("pot") is not None
                else safe_float(r.get("ovr")) for r in hist]

    proj_seasons = [int(s) for s in sim["seasons"]]
    p10 = [round(float(v), 1) for v in sim["ovr"]["p10"]]
    p25 = [round(float(v), 1) for v in sim["ovr"]["p25"]]
    p50 = [round(float(v), 1) for v in sim["ovr"]["p50"]]
    p75 = [round(float(v), 1) for v in sim["ovr"]["p75"]]
    p90 = [round(float(v), 1) for v in sim["ovr"]["p90"]]
    pot_peak = int(sim["pot_p75_peak"])

    s_min = min(hist_seasons + proj_seasons)
    s_max = max(hist_seasons + proj_seasons)
    vals = hist_ovr + hist_pot + p10 + p90 + [float(pot_peak)]
    lo = max(0.0, math.floor(min(vals)) - 4)
    hi = min(100.0, math.ceil(max(vals)) + 4)
    if hi <= lo:
        hi = lo + 1

    width, height = 660, 210
    ml, mr, mt, mb = 34, 14, 12, 28
    plot_w, plot_h = width - ml - mr, height - mt - mb
    span = max(1, s_max - s_min)

    def xs(s: float) -> float:
        return ml + (s - s_min) / span * plot_w

    def yv(v: float) -> float:
        return mt + plot_h - (v - lo) / (hi - lo) * plot_h

    grid: list[str] = []
    ystep = 10 if (hi - lo) > 30 else 5
    ytick = math.ceil(lo / ystep) * ystep
    while ytick <= hi:
        gy = yv(ytick)
        grid.append(f'<line x1="{ml}" y1="{gy:.1f}" x2="{ml + plot_w}" y2="{gy:.1f}" class="chart-grid"/>')
        grid.append(f'<text x="{ml - 6}" y="{gy + 3.5:.1f}" class="chart-tick" text-anchor="end">{int(ytick)}</text>')
        ytick += ystep
    xstep = max(1, round((s_max - s_min + 1) / 9))
    labeled: set[int] = set()
    s = s_min
    while s <= s_max:
        labeled.add(s)
        s += xstep
    labeled.update({cur_season, s_max})
    for s in sorted(labeled):
        grid.append(f'<text x="{xs(s):.1f}" y="{height - 8}" class="chart-tick" text-anchor="middle">{s}</text>')

    def poly(seasons: list[int], values: list[float], cls: str, titles: list[str] | None = None) -> str:
        pts = " ".join(f"{xs(s):.1f},{yv(v):.1f}" for s, v in zip(seasons, values))
        dots = "".join(
            f'<circle cx="{xs(s):.1f}" cy="{yv(v):.1f}" r="3" class="{cls}-dot">'
            f'<title>{titles[i] if titles else f"{s}: {int(round(v))}"}</title></circle>'
            for i, (s, v) in enumerate(zip(seasons, values))
        )
        return f'<polyline points="{pts}" class="{cls}"/>{dots}'

    def poly_hist(seasons: list[int], values: list[float], cls: str) -> str:
        # Like poly(), but breaks the line at gap years (consecutive seasons that
        # differ by more than 1) so missing seasons are not drawn as continuous
        # data. Dots are still placed on every real season.
        segments: list[list[int]] = []
        run: list[int] = []
        for i, s in enumerate(seasons):
            if run and s - seasons[i - 1] != 1:
                segments.append(run)
                run = []
            run.append(i)
        if run:
            segments.append(run)
        lines = "".join(
            f'<polyline points="{" ".join(f"{xs(seasons[i]):.1f},{yv(values[i]):.1f}" for i in seg)}" class="{cls}"/>'
            for seg in segments
        )
        dots = "".join(
            f'<circle cx="{xs(s):.1f}" cy="{yv(v):.1f}" r="3" class="{cls}-dot">'
            f'<title>{s}: {int(round(v))}</title></circle>'
            for s, v in zip(seasons, values)
        )
        return lines + dots

    # Confidence-band polygons (forward along the upper edge, back along the lower).
    def band(upper: list[float], lower: list[float], cls: str) -> str:
        fwd = " ".join(f"{xs(s):.1f},{yv(v):.1f}" for s, v in zip(proj_seasons, upper))
        back = " ".join(f"{xs(s):.1f},{yv(v):.1f}" for s, v in zip(reversed(proj_seasons), reversed(lower)))
        return f'<polygon points="{fwd} {back}" class="{cls}"/>'

    band80 = band(p90, p10, "proj-band-80")
    band50 = band(p75, p25, "proj-band-50")
    median = poly(
        proj_seasons, p50, "proj-median",
        titles=[f"{s}: {int(round(v))} proj" for s, v in zip(proj_seasons, p50)],
    )
    hist_pot_line = poly_hist(hist_seasons, hist_pot, "line-pot")
    hist_ovr_line = poly_hist(hist_seasons, hist_ovr, "line-ovr")
    divider = (
        f'<line x1="{xs(cur_season):.1f}" y1="{mt}" x2="{xs(cur_season):.1f}" '
        f'y2="{mt + plot_h}" class="proj-divider"/>'
    )

    pid = safe_int(player.get("pid"), 0)
    payload = {
        "cur": cur_season,
        "potPeak": pot_peak,
        "hist": {"s": hist_seasons,
                 "ovr": [round(v, 1) for v in hist_ovr],
                 "pot": [round(v, 1) for v in hist_pot]},
        "proj": {"s": proj_seasons, "p10": p10, "p25": p25, "p50": p50, "p75": p75, "p90": p90},
        "g": {"ml": ml, "mt": mt, "pw": plot_w, "ph": plot_h,
              "lo": lo, "hi": hi, "smin": s_min, "smax": s_max, "w": width, "h": height},
    }
    payload_json = json.dumps(payload, separators=(",", ":")).replace("</", "<\\/")

    return f"""
    <section class="card">
      <div class="section-title-row">
        <h2>Development &amp; Projection</h2>
        <span class="muted small-copy"><span class="chart-key chart-key-ovr"></span> Overall · <span class="chart-key chart-key-pot"></span> Potential · <span class="chart-key proj-key-band"></span> Projection</span>
      </div>
      <div class="chart-wrap proj-wrap" data-proj-chart>
        <svg viewBox="0 0 {width} {height}" class="proj-chart" role="img" aria-label="Overall rating history and {PROJ_SEASONS_AHEAD}-season projection">
          {''.join(grid)}
          {band80}
          {band50}
          {median}
          {hist_pot_line}
          {hist_ovr_line}
          {divider}
          <line class="proj-hover-line" data-proj-hover-line y1="{mt}" y2="{mt + plot_h}" style="display:none"/>
          <circle class="proj-hover-dot" data-proj-hover-dot r="3.5" style="display:none"/>
        </svg>
        <div class="chart-tooltip" data-proj-tooltip hidden></div>
      </div>
      <p class="muted small-copy" title="Median of {PROJ_N_SIMS:,} Monte Carlo simulations of the game's aging model; bands are the 80% (P10–P90) and 50% (P25–P75) ranges">{PROJ_SEASONS_AHEAD}-season projection · potential ceiling ≈ {pot_peak}</p>
      <script type="application/json" id="proj-data-{pid}">{payload_json}</script>
    </section>
    """
