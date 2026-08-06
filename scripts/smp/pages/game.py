from __future__ import annotations

import argparse
import functools
import html
import json
import os
import random
import math
import re
import shutil
import unicodedata
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable

from ..core import (
    ALL_PLAYERS_BY_PID,
    FREE_AGENT_TID,
    RETIRED_TID,
    age,
    esc,
    event_player_link,
    fmt_minutes,
    fmt_number,
    fmt_pct,
    fmt_ratio,
    fmt_record,
    fmt_signed,
    game_ot_label,
    game_score_value,
    game_url,
    game_winner_tid,
    is_completed_game_item,
    last_ten_text,
    latest_rating,
    latest_team_season,
    latest_team_stat,
    made_attempted,
    made_pct,
    page_html,
    player_link,
    player_name,
    player_url,
    plus_minus_class,
    safe_float,
    safe_int,
    streak_text,
    td,
    team_abbrev,
    team_abbrev_for_tid,
    team_full_for_tid,
    team_label,
    team_mov,
    team_stat_per_game,
    team_url,
    th,
)

from ..derived import drama_index, fantasy_pts

from ..identity import team_identity

# Read-only consumption of the sim model: the exact constants and player-impact
# function behind simulate_league / sim_client_inputs, so the preview projection
# below shows the same numbers the Monte Carlo uses (parity is tested).
from ..simmodel import SIM_HCA, SIM_LOGISTIC_K, SIM_MOV_BLEND_K, rotation_impacts, rotation_strength


SHOT_ZONES = [("AtRim", "Rim"), ("LowPost", "Post"), ("MidRange", "Mid"), ("", "3P")]

# Drama-index floor for the "Instant Classic" hero chip. Calibrated on the real
# distribution (479 retained games across seasons 2029-2030): max observed 68,
# only 9 games (~1.9%, about 4-5 per 45-game season) reach 50. Data-driven, not
# per-season: the same bar applies to every future export.
DRAMA_CLASSIC_MIN = 50.0

# FPTS is a local header title because core.GLOSSARY is owned elsewhere.
FPTS_TITLE = "Fantasy points"

# Same reason: the preview's one non-obvious number. It is a simmodel term, so the
# wording has to promise exactly what the sim computes and no more.
IMPACT_TITLE = (
    "Projected points this player adds to the scoring margin at his rotation slot — "
    "the terms the spread above is summed from"
)

# Monte Carlo projections, written beside the export by the projection harness
# (league-data/projected_box_scores.json). Local-only and entirely optional:
# nothing in the build requires it, and a checkout that has never run the
# harness renders the rotation tables it renders today. SMP_PROJECTED_BOX_SCORES
# overrides the location for builds run against a copied league-data tree.
PROJECTION_PATH = Path(__file__).resolve().parents[3] / "league-data" / "projected_box_scores.json"
PROJECTION_PATH_ENV = "SMP_PROJECTED_BOX_SCORES"

# Below this many projected minutes a man gets a footer line, not a row. A mean
# of 0.3 minutes prints as a row of 0.0s, which is indistinguishable from a DNP
# line in a real box score — exactly the confusion this page must not create.
PROJECTED_MIN_FLOOR = 1.0

# Fewer surviving rows than this on either side and the projection is not
# trustworthy enough to publish (stale pids, a half-written file): fall back to
# the rotation tables for the whole game rather than print a five-man team.
PROJECTED_MIN_ROWS = 5

PROJECTED_MIN_TITLE = (
    "Projected minutes — the mean across every simulation of this game, not a played total"
)
PROJECTED_OUT_TITLE = (
    "The league dresses ten; the 11th and 12th men are reserve and do not play. "
    "Also covers anyone the projection run does not carry."
)


def fmt_fpts(fpts: float | None) -> str:
    """Fantasy points display everywhere on game pages: whole numbers."""
    return fmt_number(int(round(fpts)), 0) if fpts is not None else "—"


def fpts_th() -> str:
    return f'<th scope="col" title="{esc(FPTS_TITLE)}">FPTS</th>'


def shot_zone_cells(box: dict[str, Any]) -> list[str]:
    cells = []
    for suffix, label in SHOT_ZONES:
        if label == "3P":
            made, att = safe_float(box.get("tp")), safe_float(box.get("tpa"))
        else:
            made, att = safe_float(box.get("fg" + suffix)), safe_float(box.get("fga" + suffix))
        pct = made_pct(made, att)
        cells.append(td(f"{fmt_number(made, 0)}-{fmt_number(att, 0)} <span class=\"muted\">({fmt_pct(pct, 1)}%)</span>" if att else "—", sort=pct))
    return cells


def game_shot_profile(item: dict[str, Any], teams_by_tid: dict[int, dict[str, Any]], root: str) -> str:
    if not is_completed_game_item(item):
        return ""
    rows = []
    for box_key in ("away_box", "home_box"):
        box = item.get(box_key) or {}
        cells = [td(team_label(box.get("tid"), teams_by_tid, root), cls="name-cell")] + shot_zone_cells(box)
        rows.append("<tr>" + "".join(cells) + "</tr>")
    header = "".join(th(label) for label in ["Team", "Rim", "Post", "Mid", "3P"])
    return f"""
    <section class="card compact-card">
      <div class="section-title-row"><h2>Shot Zones</h2><span class="muted small-copy">made-attempted (FG%) by area</span></div>
      <div class="table-wrap fit-table">
        <table><thead><tr>{header}</tr></thead><tbody>{''.join(rows)}</tbody></table>
      </div>
    </section>
    """


def box_player_link(player_box: dict[str, Any], players_by_pid: dict[int, dict[str, Any]], root: str) -> str:
    pid = player_box.get("pid")
    full = players_by_pid.get(int(pid)) if pid is not None and str(pid).lstrip("-").isdigit() else None
    number = player_box.get("jerseyNumber")
    number_html = f'<span class="muted number">{esc(number)}</span> ' if number not in (None, "") else ""
    skills = player_box.get("skills") or (latest_rating(full).get("skills") if full else []) or []
    skill_html = "".join(f'<span class="mini-skill">{esc(skill)}</span>' for skill in skills)
    name = player_box.get("name") or (player_name(full) if full else "Unknown")
    if full:
        return f'{number_html}<a class="player-link" href="{player_url(full, root)}">{esc(name)}</a> {skill_html}'
    return f'{number_html}<span class="player-link">{esc(name)}</span> {skill_html}'


def played_box_players(team_box: dict[str, Any]) -> tuple[list[dict[str, Any]], int, list[dict[str, Any]]]:
    """Completed games: everyone with minutes (starters first), plus the DNP list."""
    players = team_box.get("players") or []
    played = [p for p in players if safe_float(p.get("min")) > 0]
    starters = [p for p in played if safe_int(p.get("gs")) > 0][:5]
    bench = [p for p in played if p not in starters]
    dnp = [p for p in players if safe_float(p.get("min")) <= 0]
    return starters + bench, len(starters), dnp


def dnp_footer_html(dnp_players: list[dict[str, Any]], players_by_pid: dict[int, dict[str, Any]], root: str) -> str:
    if not dnp_players:
        return ""
    links = []
    for player_box in dnp_players:
        pid = safe_int(player_box.get("pid"), -10)
        full = players_by_pid.get(pid)
        name = player_box.get("name") or (player_name(full) if full else "Unknown")
        if full:
            links.append(f'<a href="{player_url(full, root)}">{esc(name)}</a>')
        else:
            links.append(esc(name))
    return f'<p class="gx-dnp small-copy muted"><strong>Did not play:</strong> {", ".join(links)}</p>'


def box_score_player_row(player_box: dict[str, Any], players_by_pid: dict[int, dict[str, Any]], root: str, cls: str = "") -> str:
    trb = safe_float(player_box.get("orb")) + safe_float(player_box.get("drb"))
    fpts = fantasy_pts(player_box)
    row = "".join([
        td(box_player_link(player_box, players_by_pid, root), sort=player_box.get("name"), cls="name-cell"),
        td(esc(player_box.get("pos", "—")), sort=player_box.get("pos", "")),
        td(fmt_minutes(player_box.get("min")), sort=player_box.get("min")),
        td(made_attempted(player_box.get("fg"), player_box.get("fga")), sort=player_box.get("fg")),
        td(made_attempted(player_box.get("tp"), player_box.get("tpa")), sort=player_box.get("tp")),
        td(made_attempted(player_box.get("ft"), player_box.get("fta")), sort=player_box.get("ft")),
        td(fmt_number(player_box.get("orb") or 0, 0), sort=player_box.get("orb")),
        td(fmt_number(trb, 0), sort=trb),
        td(fmt_number(player_box.get("ast") or 0, 0), sort=player_box.get("ast")),
        td(fmt_number(player_box.get("tov") or 0, 0), sort=player_box.get("tov")),
        td(fmt_number(player_box.get("stl") or 0, 0), sort=player_box.get("stl")),
        td(fmt_number(player_box.get("blk") or 0, 0), sort=player_box.get("blk")),
        td(fmt_number(player_box.get("ba") or 0, 0), sort=player_box.get("ba")),
        td(fmt_number(player_box.get("pf") or 0, 0), sort=player_box.get("pf")),
        td(fmt_number(player_box.get("pts") or 0, 0), sort=player_box.get("pts")),
        td(fmt_signed(player_box.get("pm") or 0, 0), sort=player_box.get("pm"), cls=plus_minus_class(player_box.get("pm"))),
        td(fmt_fpts(fpts), sort=fpts),
    ])
    cls_attr = f' class="{cls}"' if cls else ""
    return f"<tr{cls_attr}>{row}</tr>"


def box_team_totals_row(team_box: dict[str, Any]) -> str:
    trb = safe_float(team_box.get("orb")) + safe_float(team_box.get("drb"))
    fpts = fantasy_pts(team_box)
    cells = [
        td("Total", sort="zzzz", cls="name-cell total-label"),
        td(""),
        td(fmt_number(team_box.get("min") or 240, 0), sort=team_box.get("min") or 240),
        td(made_attempted(team_box.get("fg"), team_box.get("fga")), sort=team_box.get("fg")),
        td(made_attempted(team_box.get("tp"), team_box.get("tpa")), sort=team_box.get("tp")),
        td(made_attempted(team_box.get("ft"), team_box.get("fta")), sort=team_box.get("ft")),
        td(fmt_number(team_box.get("orb") or 0, 0), sort=team_box.get("orb")),
        td(fmt_number(trb, 0), sort=trb),
        td(fmt_number(team_box.get("ast") or 0, 0), sort=team_box.get("ast")),
        td(fmt_number(team_box.get("tov") or 0, 0), sort=team_box.get("tov")),
        td(fmt_number(team_box.get("stl") or 0, 0), sort=team_box.get("stl")),
        td(fmt_number(team_box.get("blk") or 0, 0), sort=team_box.get("blk")),
        td(fmt_number(team_box.get("ba") or 0, 0), sort=team_box.get("ba")),
        td(fmt_number(team_box.get("pf") or 0, 0), sort=team_box.get("pf")),
        td(fmt_number(team_box.get("pts") or 0, 0), sort=team_box.get("pts")),
        td(""),
        td(fmt_fpts(fpts) if fpts is not None else "", sort=fpts),
    ]
    return f"<tr class=\"total-row\">{''.join(cells)}</tr>"


def box_team_percentages_row(team_box: dict[str, Any]) -> str:
    cells = [td("Percentages", cls="name-cell total-label"), td(""), td("")]
    cells.append(td(fmt_pct(made_pct(team_box.get("fg"), team_box.get("fga")), 1), sort=made_pct(team_box.get("fg"), team_box.get("fga"))))
    cells.append(td(fmt_pct(made_pct(team_box.get("tp"), team_box.get("tpa")), 1), sort=made_pct(team_box.get("tp"), team_box.get("tpa"))))
    cells.append(td(fmt_pct(made_pct(team_box.get("ft"), team_box.get("fta")), 1), sort=made_pct(team_box.get("ft"), team_box.get("fta"))))
    cells.extend(td("") for _ in range(11))
    return f"<tr class=\"pct-row\">{''.join(cells)}</tr>"


def box_score_team_table(team_box: dict[str, Any], teams_by_tid: dict[int, dict[str, Any]], players_by_pid: dict[int, dict[str, Any]], root: str) -> str:
    """A played game's box score. Unplayed games get preview_rotations_html instead.

    This used to double as the preview state by filling every stat cell with an
    em-dash: two 16-column tables, 160 empty cells, on a page whose only job is
    to sell a game nobody has played yet. A projection is not a blank box score.
    """
    tid = safe_int(team_box.get("tid"))
    team_name = team_full_for_tid(tid, teams_by_tid)
    selected, bench_index, dnp = played_box_players(team_box)
    rows: list[str] = []
    for i, player_box in enumerate(selected):
        cls = "bench-start" if i == bench_index and i > 0 else ""
        rows.append(box_score_player_row(player_box, players_by_pid, root, cls=cls))
    rows.append(box_team_totals_row(team_box))
    rows.append(box_team_percentages_row(team_box))
    header_html = "".join(th(label) for label in ["Name", "Pos", "MP", "FG", "3P", "FT", "ORB", "TRB", "AST", "TOV", "STL", "BLK", "BA", "PF", "PTS", "+/-"]) + fpts_th()
    return f"""
    <section class="box-team-section">
      <h2>{team_label(tid, teams_by_tid, root=root)}</h2>
      <div class="table-wrap box-table-wrap">
        <table data-sortable class="box-score-table">
          <caption class="sr-only">{esc(team_name)} box score</caption>
          <thead><tr>{header_html}</tr></thead>
          <tbody>{''.join(rows)}</tbody>
        </table>
      </div>
      {dnp_footer_html(dnp, players_by_pid, root)}
    </section>
    """


def qtr_cells(points: list[Any], max_len: int) -> str:
    cells = []
    for i in range(max_len):
        value = points[i] if i < len(points) else ""
        cells.append(td(fmt_number(value, 0) if value != "" else "", sort=value if value != "" else None))
    return "".join(cells)


def team_factor_values(team_box: dict[str, Any], opp_box: dict[str, Any]) -> dict[str, float | None]:
    fga = safe_float(team_box.get("fga"))
    fta = safe_float(team_box.get("fta"))
    tov = safe_float(team_box.get("tov"))
    efg = (safe_float(team_box.get("fg")) + 0.5 * safe_float(team_box.get("tp"))) / fga if fga else None
    tov_pct = tov / (fga + 0.44 * fta + tov) if (fga + 0.44 * fta + tov) else None
    orb_pct = safe_float(team_box.get("orb")) / (safe_float(team_box.get("orb")) + safe_float(opp_box.get("drb"))) if (safe_float(team_box.get("orb")) + safe_float(opp_box.get("drb"))) else None
    ftr = fta / fga if fga else None
    return {"eFG%": efg, "TOV%": tov_pct, "ORB%": orb_pct, "FT/FGA": ftr}


def game_series_note(item: dict[str, Any], teams_by_tid: dict[int, dict[str, Any]]) -> str:
    game = item.get("game") or {}
    if not game.get("playoffs"):
        return ""
    target = safe_int(game.get("numGamesToWinSeries"), 0)
    notes = []
    for box in game.get("teams") or []:
        playoffs = box.get("playoffs") or {}
        won = safe_int(playoffs.get("won"), 0)
        lost = safe_int(playoffs.get("lost"), 0)
        if target and won >= target:
            notes.append(f"{team_abbrev_for_tid(box.get('tid'), teams_by_tid)} won series {won}-{lost}")
    if notes:
        return f'<p class="series-note">{esc(" · ".join(notes))}</p>'
    return ""


# ---------------------------------------------------------------------------
# Dual-identity split hero
# ---------------------------------------------------------------------------


def hero_style_vars(home_tid: Any, away_tid: Any) -> str:
    """Both teams' identity colors as --gx-* custom properties for one element."""
    home = team_identity(safe_int(home_tid))
    away = team_identity(safe_int(away_tid))
    return (
        f"--gx-home-primary:{home['primary']};--gx-home-secondary:{home['secondary']};"
        f"--gx-home-chart:{home['chart']};"
        f"--gx-away-primary:{away['primary']};--gx-away-secondary:{away['secondary']};"
        f"--gx-away-chart:{away['chart']}"
    )


def hero_bg_html(home_tid: Any, away_tid: Any, winner_tid: int | None) -> str:
    def cls(tid: Any, base: str) -> str:
        if winner_tid is None:
            return base
        return base + (" gx-won" if safe_int(tid) == winner_tid else " gx-lost")

    return (
        f'<div class="{cls(away_tid, "gx-bg gx-bg-away")}" aria-hidden="true"></div>'
        f'<div class="{cls(home_tid, "gx-bg gx-bg-home")}" aria-hidden="true"></div>'
    )


def team_record_text(tid: Any, teams_by_tid: dict[int, dict[str, Any]], season: int) -> str:
    team = teams_by_tid.get(safe_int(tid))
    if not team:
        return ""
    row = latest_team_season(team, season)
    if row.get("season") != season:
        return ""
    return fmt_record(row.get("won"), row.get("lost"))


def hero_side_html(tid: Any, side: str, teams_by_tid: dict[int, dict[str, Any]], season: int,
                   pts: Any = None, winner_tid: int | None = None, root: str = "../") -> str:
    team = teams_by_tid.get(safe_int(tid))
    name = team_full_for_tid(tid, teams_by_tid)
    record = team_record_text(tid, teams_by_tid, season)
    cls = f"gx-side gx-side-{side}"
    if winner_tid is not None:
        cls += " gx-won" if safe_int(tid) == winner_tid else " gx-lost"
    if team:
        name_html = f'<a class="gx-team-name" href="{team_url(team, root)}">{esc(name)}</a>'
    else:
        name_html = f'<span class="gx-team-name">{esc(name)}</span>'
    record_html = f'<span class="gx-team-record">{esc(record)}</span>' if record else ""
    score_html = f'<span class="gx-score">{fmt_number(pts, 0)}</span>' if pts is not None else ""
    return f'<span class="{cls}">{name_html}{record_html}{score_html}</span>'


def instant_classic_chip(item: dict[str, Any], feats_by_gid: dict[str, list[dict[str, Any]]] | None) -> str:
    if not is_completed_game_item(item):
        return ""
    score = drama_index(item.get("game") or {}, feats_by_gid)
    if score < DRAMA_CLASSIC_MIN:
        return ""
    return (
        f'<a class="gx-classic" href="../classics.html" '
        f'title="Drama index {fmt_number(score, 0)}/100 — see Greatest Games">'
        f'<span aria-hidden="true">★</span> Instant Classic '
        f'<span class="gx-classic-score">{fmt_number(score, 0)}</span></a>'
    )


# ---------------------------------------------------------------------------
# Quarter momentum bars
# ---------------------------------------------------------------------------


def momentum_bars_svg(item: dict[str, Any], teams_by_tid: dict[int, dict[str, Any]]) -> str:
    """Mirrored per-period margin bars: up = home won the period, down = away."""
    if not is_completed_game_item(item):
        return ""
    home_q = (item.get("home_box") or {}).get("ptsQtrs") or []
    away_q = (item.get("away_box") or {}).get("ptsQtrs") or []
    n = max(len(home_q), len(away_q))
    if n < 2:
        return ""
    home_ab = team_abbrev_for_tid(item.get("home_tid"), teams_by_tid)
    away_ab = team_abbrev_for_tid(item.get("away_tid"), teams_by_tid)
    diffs: list[float] = []
    labels: list[str] = []
    for i in range(n):
        h = safe_float(home_q[i]) if i < len(home_q) else 0.0
        a = safe_float(away_q[i]) if i < len(away_q) else 0.0
        diffs.append(h - a)
        if i < 4:
            labels.append(f"Q{i + 1}")
        else:
            labels.append("OT" if i == 4 else f"{i - 3}OT")

    col_w, bar_w = 56.0, 20.0
    ml = mr = 6.0
    bar_max, val_h, period_h, top_pad = 30.0, 11.0, 14.0, 4.0
    mid_y = top_pad + val_h + bar_max
    width = ml + mr + col_w * n
    height = mid_y + bar_max + val_h + period_h
    max_abs = max([abs(d) for d in diffs] + [1.0])

    parts = [f'<line x1="{ml:.1f}" y1="{mid_y:.1f}" x2="{width - mr:.1f}" y2="{mid_y:.1f}" class="gx-mom-axis"/>']
    summary_bits: list[str] = []
    for i, diff in enumerate(diffs):
        cx = ml + col_w * i + col_w / 2
        x0 = cx - bar_w / 2
        if diff > 0:
            desc = f"{labels[i]}: {home_ab} by {fmt_number(diff, 0)}"
        elif diff < 0:
            desc = f"{labels[i]}: {away_ab} by {fmt_number(-diff, 0)}"
        else:
            desc = f"{labels[i]}: even"
        summary_bits.append(desc)
        if diff == 0:
            parts.append(
                f'<rect x="{x0:.1f}" y="{mid_y - 1.5:.1f}" width="{bar_w:.1f}" height="3" rx="1.5" '
                f'class="gx-mom-even"><title>{esc(desc)}</title></rect>'
            )
        else:
            h_px = max(3.0, abs(diff) / max_abs * bar_max)
            if diff > 0:
                y0 = mid_y - h_px
                parts.append(
                    f'<rect x="{x0:.1f}" y="{y0:.1f}" width="{bar_w:.1f}" height="{h_px:.1f}" rx="2" '
                    f'class="gx-mom-bar gx-mom-bar-home"><title>{esc(desc)}</title></rect>'
                )
                parts.append(f'<text x="{cx:.1f}" y="{y0 - 3:.1f}" text-anchor="middle" class="gx-mom-val">{fmt_number(diff, 0)}</text>')
            else:
                parts.append(
                    f'<rect x="{x0:.1f}" y="{mid_y:.1f}" width="{bar_w:.1f}" height="{h_px:.1f}" rx="2" '
                    f'class="gx-mom-bar gx-mom-bar-away"><title>{esc(desc)}</title></rect>'
                )
                parts.append(f'<text x="{cx:.1f}" y="{mid_y + h_px + 9:.1f}" text-anchor="middle" class="gx-mom-val">{fmt_number(-diff, 0)}</text>')
        parts.append(f'<text x="{cx:.1f}" y="{height - 3:.1f}" text-anchor="middle" class="gx-mom-label">{esc(labels[i])}</text>')

    aria = "Period scoring margins — " + "; ".join(summary_bits)
    # Cap at the intrinsic pixel size so viewBox text renders at ~10px (it only
    # shrinks on narrow screens, never blows up on wide ones).
    return f"""
      <div class="gx-momentum-wrap" style="max-width:{width:.0f}px">
        <svg viewBox="0 0 {width:.0f} {height:.0f}" class="gx-momentum" role="img" aria-label="{esc(aria)}">{''.join(parts)}</svg>
        <p class="gx-mom-caption muted small-copy">Quarter margins · ▲ {esc(home_ab)} won the period · ▼ {esc(away_ab)}</p>
      </div>
    """


# ---------------------------------------------------------------------------
# Pagers, stars, hero assembly
# ---------------------------------------------------------------------------


def pager_html(target: dict[str, Any] | None, direction: str, teams_by_tid: dict[int, dict[str, Any]]) -> str:
    label = "Prev" if direction == "prev" else "Next"
    dir_text = f"← {label}" if direction == "prev" else f"{label} →"
    if target is None:
        # A one-line dead pager opposite a two-line live one pushed the whole
        # scoreboard off-centre on the season's first and last game. Say why it
        # is dead and the two sides match.
        why = "First game of the season" if direction == "prev" else "Last game of the season"
        return (
            f'<span class="button-link gx-pager disabled">'
            f'<span class="gx-pager-dir">{esc(dir_text)}</span>'
            f'<span class="gx-pager-ctx">{esc(why)}</span></span>'
        )
    away_ab = team_abbrev_for_tid(target.get("away_tid"), teams_by_tid)
    home_ab = team_abbrev_for_tid(target.get("home_tid"), teams_by_tid)
    ctx = f"Day {safe_int(target.get('day'))} · {away_ab} @ {home_ab}"
    return (
        f'<a class="button-link gx-pager" href="{esc(game_url(target, root="../"))}">'
        f'<span class="gx-pager-dir">{esc(dir_text)}</span>'
        f'<span class="gx-pager-ctx">{esc(ctx)}</span></a>'
    )


def _star_name_html(player_box: dict[str, Any], root: str) -> str:
    full = ALL_PLAYERS_BY_PID.get(safe_int(player_box.get("pid"), -10))
    name = player_box.get("name") or (player_name(full) if full else "—")
    if full is not None and full.get("retiredYear") is None and safe_int(full.get("tid"), RETIRED_TID) >= FREE_AGENT_TID:
        return f'<a href="{player_url(full, root)}">{esc(name)}</a>'
    return esc(name)


def _star_stat_line(player_box: dict[str, Any]) -> str:
    trb = safe_float(player_box.get("orb")) + safe_float(player_box.get("drb"))
    return f"{fmt_number(player_box.get('pts'), 0)} PTS · {fmt_number(trb, 0)} TRB · {fmt_number(player_box.get('ast'), 0)} AST"


def game_stars_html(item: dict[str, Any], teams_by_tid: dict[int, dict[str, Any]], root: str) -> str:
    """Player of the Game (top Game Score) + Fantasy MVP badge when they differ."""
    best: tuple[float, dict[str, Any], Any] | None = None
    best_fantasy: tuple[float, dict[str, Any], Any] | None = None
    for box_key in ("home_box", "away_box"):
        box = item.get(box_key) or {}
        for player_box in box.get("players") or []:
            if safe_float(player_box.get("min")) <= 0:
                continue
            gmsc = game_score_value(player_box)
            if best is None or gmsc > best[0]:
                best = (gmsc, player_box, box.get("tid"))
            fpts = fantasy_pts(player_box)
            if fpts is not None and (best_fantasy is None or fpts > best_fantasy[0]):
                best_fantasy = (fpts, player_box, box.get("tid"))
    if best is None:
        return ""
    _, player_box, tid = best
    same_star = best_fantasy is not None and safe_int(player_box.get("pid"), -10) == safe_int(best_fantasy[1].get("pid"), -11)
    potg_fpts = fantasy_pts(player_box)
    fpts_note = f" · {fmt_fpts(potg_fpts)} FPTS" if potg_fpts is not None else ""
    out = [
        f'<p class="potg"><span class="badge badge-accent">POTG</span>{_star_name_html(player_box, root)} '
        f'<span class="muted">({esc(team_abbrev_for_tid(tid, teams_by_tid))}) · {_star_stat_line(player_box)}'
        f'{fpts_note}</span></p>'
    ]
    if best_fantasy is not None and not same_star:
        fpts, fantasy_box, fantasy_tid = best_fantasy
        out.append(
            f'<p class="potg"><span class="badge badge-good">Fantasy MVP</span>{_star_name_html(fantasy_box, root)} '
            f'<span class="muted">({esc(team_abbrev_for_tid(fantasy_tid, teams_by_tid))}) · {_star_stat_line(fantasy_box)} · '
            f'{fmt_fpts(fpts)} FPTS</span></p>'
        )
    return "".join(out)


def line_score_html(item: dict[str, Any], teams_by_tid: dict[int, dict[str, Any]]) -> str:
    home_box = item.get("home_box") or {}
    away_box = item.get("away_box") or {}
    home_abbrev = team_abbrev_for_tid(item.get("home_tid"), teams_by_tid)
    away_abbrev = team_abbrev_for_tid(item.get("away_tid"), teams_by_tid)
    winner = game_winner_tid(item)
    max_len = max(len(home_box.get("ptsQtrs") or []), len(away_box.get("ptsQtrs") or []), 4)
    period_labels = [str(i + 1) for i in range(min(4, max_len))]
    if max_len > 4:
        period_labels.extend("OT" if i == 4 else f"{i - 3}OT" for i in range(4, max_len))
    period_labels = period_labels[:max_len]
    score_headers = "".join(th(label) for label in ["", *period_labels, "F"])

    def score_row(abbrev: str, box: dict[str, Any], pts: Any, tid: Any) -> str:
        won = winner is not None and safe_int(tid) == winner
        tick = ' <span class="gx-win-tick" aria-hidden="true">✓</span><span class="sr-only"> winner</span>' if won else ""
        row_cls = ' class="gx-win-row"' if won else ""
        return (
            f"<tr{row_cls}>{td(esc(abbrev) + tick, cls='score-team')}"
            f"{qtr_cells(box.get('ptsQtrs') or [], max_len)}"
            f"{td(fmt_number(pts, 0), sort=pts, cls='final-score')}</tr>"
        )

    away_row = score_row(away_abbrev, away_box, item.get("away_pts"), item.get("away_tid"))
    home_row = score_row(home_abbrev, home_box, item.get("home_pts"), item.get("home_tid"))

    home_factors = team_factor_values(home_box, away_box)
    away_factors = team_factor_values(away_box, home_box)
    factor_headers = "".join(th(label) for label in ["", "eFG%", "TOV%", "ORB%", "FT/FGA"])
    away_factor_row = f"<tr>{td(esc(away_abbrev), cls='score-team')}{td(fmt_pct((away_factors['eFG%'] or 0) * 100 if away_factors['eFG%'] is not None else None, 1))}{td(fmt_pct((away_factors['TOV%'] or 0) * 100 if away_factors['TOV%'] is not None else None, 1))}{td(fmt_pct((away_factors['ORB%'] or 0) * 100 if away_factors['ORB%'] is not None else None, 1))}{td(fmt_ratio(away_factors['FT/FGA'], 3))}</tr>"
    home_factor_row = f"<tr>{td(esc(home_abbrev), cls='score-team')}{td(fmt_pct((home_factors['eFG%'] or 0) * 100 if home_factors['eFG%'] is not None else None, 1))}{td(fmt_pct((home_factors['TOV%'] or 0) * 100 if home_factors['TOV%'] is not None else None, 1))}{td(fmt_pct((home_factors['ORB%'] or 0) * 100 if home_factors['ORB%'] is not None else None, 1))}{td(fmt_ratio(home_factors['FT/FGA'], 3))}</tr>"
    return f"""
        <div class="scoreboard-grid">
          <div class="mini-score-table table-wrap"><table><thead><tr>{score_headers}</tr></thead><tbody>{away_row}{home_row}</tbody></table></div>
          <div class="mini-score-table table-wrap"><table><thead><tr>{factor_headers}</tr></thead><tbody>{away_factor_row}{home_factor_row}</tbody></table></div>
        </div>
    """


def box_score_header(item: dict[str, Any], teams_by_tid: dict[int, dict[str, Any]],
                     prev_item: dict[str, Any] | None, next_item: dict[str, Any] | None,
                     feats_by_gid: dict[str, list[dict[str, Any]]] | None = None,
                     projection_html: str = "") -> str:
    season = safe_int(item.get("season"))
    home_tid = item.get("home_tid")
    away_tid = item.get("away_tid")
    completed = is_completed_game_item(item)
    winner = game_winner_tid(item) if completed else None

    prev_link = pager_html(prev_item, "prev", teams_by_tid)
    next_link = pager_html(next_item, "next", teams_by_tid)
    eyebrow = f"Day {fmt_number(item.get('day'), 0)} · Season {fmt_number(season, 0)}"
    if item.get("playoffs"):
        eyebrow += " · Playoffs"

    away_side = hero_side_html(away_tid, "away", teams_by_tid, season,
                               pts=item.get("away_pts") if completed else None, winner_tid=winner)
    home_side = hero_side_html(home_tid, "home", teams_by_tid, season,
                               pts=item.get("home_pts") if completed else None, winner_tid=winner)
    if completed:
        ot = game_ot_label(item)
        center = "Final" + (f" · {ot}" if ot else "")
    else:
        center = "@"
    chip = instant_classic_chip(item, feats_by_gid)
    chip_html = f'<p class="gx-classic-row">{chip}</p>' if chip else ""

    if completed:
        extras = f"""
        {momentum_bars_svg(item, teams_by_tid)}
        {line_score_html(item, teams_by_tid)}
        {game_stars_html(item, teams_by_tid, '../')}
        {game_series_note(item, teams_by_tid)}
        """
    else:
        extras = f"""
        {projection_html}
        <p class="scheduled-note">Scheduled game · box score to come.</p>
        """

    return f"""
    <section class="box-score-hero card gx-hero" style="{hero_style_vars(home_tid, away_tid)}">
      {hero_bg_html(home_tid, away_tid, winner)}
      <div class="game-pager">{prev_link}</div>
      <div class="scoreboard-core gx-core">
        <p class="eyebrow">{esc(eyebrow)}</p>
        <h1 class="gx-matchup">{away_side}<span class="gx-at">{esc(center)}</span>{home_side}</h1>
        {chip_html}
        {extras}
      </div>
      <div class="game-pager">{next_link}</div>
    </section>
    """


def season_series_html(item: dict[str, Any], all_items: list[dict[str, Any]], teams_by_tid: dict[int, dict[str, Any]], root: str) -> str:
    pair = {safe_int(item.get("home_tid")), safe_int(item.get("away_tid"))}
    meetings = [
        other for other in all_items
        if {safe_int(other.get("home_tid")), safe_int(other.get("away_tid"))} == pair
    ]
    meetings.sort(key=lambda other: (safe_int(other.get("day")), str(other.get("gid"))))
    completed = [m for m in meetings if is_completed_game_item(m)]
    if len(meetings) < 2:
        return ""
    tid_a, tid_b = sorted(pair)
    wins = {tid_a: 0, tid_b: 0}
    for m in completed:
        winner = game_winner_tid(m)
        if winner in wins:
            wins[winner] += 1
    if not completed:
        # "First meeting of the season" was printed on all four meeting pages
        # while none had been played, which is false on three of them. Say where
        # in the series this game actually falls.
        position = next((i for i, m in enumerate(meetings) if str(m.get("gid")) == str(item.get("gid"))), 0) + 1
        series_text = f"Meeting {position} of {len(meetings)} · none played yet"
    elif wins[tid_a] == wins[tid_b]:
        series_text = f"Series tied {wins[tid_a]}-{wins[tid_b]}"
    else:
        lead_tid = tid_a if wins[tid_a] > wins[tid_b] else tid_b
        trail = min(wins.values())
        series_text = f"{team_abbrev_for_tid(lead_tid, teams_by_tid)} leads the series {max(wins.values())}-{trail}"
    chips = []
    for m in meetings:
        current = str(m.get("gid")) == str(item.get("gid"))
        if is_completed_game_item(m):
            winner = game_winner_tid(m)
            away = team_abbrev_for_tid(m.get("away_tid"), teams_by_tid)
            home = team_abbrev_for_tid(m.get("home_tid"), teams_by_tid)
            away_html = f"{esc(away)} {fmt_number(m.get('away_pts'), 0)}"
            home_html = f"{esc(home)} {fmt_number(m.get('home_pts'), 0)}"
            if winner == m.get("away_tid"):
                away_html = f"<strong>{away_html}</strong>"
            elif winner == m.get("home_tid"):
                home_html = f"<strong>{home_html}</strong>"
            label = f"Day {safe_int(m.get('day'))}: {away_html} @ {home_html}"
        else:
            label = (
                f"Day {safe_int(m.get('day'))}: "
                f"{esc(team_abbrev_for_tid(m.get('away_tid'), teams_by_tid))} @ "
                f"{esc(team_abbrev_for_tid(m.get('home_tid'), teams_by_tid))}"
            )
        cls = "series-chip current" if current else "series-chip"
        # The current chip links to the page you are already on; the accent border
        # says so visually, aria-current says so to a screen reader.
        marker = ' aria-current="page"' if current else ""
        chips.append(f'<a class="{cls}"{marker} href="{esc(game_url(m, root))}">{label}</a>')
    return f"""
    <section class="card">
      <div class="section-title-row"><h2>Season Series</h2><span class="muted small-copy">{esc(series_text)}</span></div>
      <div class="series-row">{''.join(chips)}</div>
    </section>
    """


# ---------------------------------------------------------------------------
# Preview projection (win probability + spread, sim-consistent)
# ---------------------------------------------------------------------------

# Strengths are identical for every preview page in a build; memoize on the
# exact list objects build.py passes to every render_game_page call.
_STRENGTH_CACHE: dict[tuple[int, int, int, int, int], dict[int, float]] = {}


def preview_strengths(teams: list[dict[str, Any]], players: list[dict[str, Any]], season: int) -> dict[int, float]:
    """Healthy-baseline sim strengths per tid, mirroring simmodel.sim_client_inputs.

    Same math as the Monte Carlo's base strength: current-roster top-10
    per-game impact centered on the league mean, blended with CURRENT-season
    scoring margin at weight gp/(gp+SIM_MOV_BLEND_K). Tests assert parity with
    sim_client_inputs so displayed odds always agree with the sim.
    """
    key = (id(teams), len(teams), id(players), len(players), season)
    cached = _STRENGTH_CACHE.get(key)
    if cached is not None:
        return cached
    tids = [safe_int(t.get("tid")) for t in teams if t.get("tid") is not None]
    roster_by_tid: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for player in players:
        tid = safe_int(player.get("tid"), -9)
        if tid >= 0:
            roster_by_tid[tid].append(player)
    roster_strength: dict[int, float] = {}
    for tid in tids:
        # simmodel.rotation_strength, not a local copy of it: the rotation sum is
        # rank-decayed, and a flat re-implementation here silently published odds
        # the simulator disagreed with.
        roster_strength[tid] = rotation_strength(roster_by_tid.get(tid, []), season)
    mean_roster = sum(roster_strength.values()) / len(roster_strength) if roster_strength else 0.0
    strengths: dict[int, float] = {}
    for team in teams:
        tid = safe_int(team.get("tid"))
        stat = latest_team_stat(team, season)
        # latest_team_stat falls back to an earlier season's row when this
        # season has no stats yet — never blend last season's margin.
        if safe_int(stat.get("season")) == season:
            gp = safe_float(stat.get("gp"))
            mov = team_mov(stat) or 0.0
        else:
            gp, mov = 0.0, 0.0
        mov_weight = gp / (gp + SIM_MOV_BLEND_K)
        strengths[tid] = (1.0 - mov_weight) * (roster_strength.get(tid, 0.0) - mean_roster) + mov_weight * mov
    _STRENGTH_CACHE[key] = strengths
    return strengths


def preview_home_win_prob(strengths: dict[int, float], home_tid: int, away_tid: int) -> float:
    """p(home) = 1 / (1 + exp(-(sH - sA + SIM_HCA) * SIM_LOGISTIC_K)) — the sim's win_prob."""
    diff = strengths.get(home_tid, 0.0) - strengths.get(away_tid, 0.0) + SIM_HCA
    return 1.0 / (1.0 + math.exp(-diff * SIM_LOGISTIC_K))


def preview_projection_html(item: dict[str, Any], teams: list[dict[str, Any]],
                            teams_by_tid: dict[int, dict[str, Any]],
                            players: list[dict[str, Any]], season: int) -> str:
    """Hero centerpiece for unplayed games: both win probabilities + the spread.

    Two different models can fill this block, and the page must never show one
    while arguing the other. When this game has a projected box score below, the
    hero quotes THAT run — its own win frequency, its own mean margin — because
    a spread contradicted by point totals the reader can see two panels down is
    simply wrong, however well-sourced. The two models really do disagree: over
    the 180 previews the game sim's home edge is +3.3 (2003-04's was +3.2) where
    SIM_HCA is +1.5, it rates teams on a wider spread than the rotation-impact
    model, and on 35 games they name opposite favourites.

    Without a projection this is the season sim's logistic, unchanged — which is
    what the home page cards, the schedule and the standings all quote, and the
    caption says which of the two a reader is looking at.
    """
    home_tid = safe_int(item.get("home_tid"))
    away_tid = safe_int(item.get("away_tid"))
    if home_tid not in teams_by_tid or away_tid not in teams_by_tid:
        return ""
    # projected_box_data, not projected_game: the hero may only speak for a
    # projection the page is actually going to print below it.
    data = projected_box_data(item, teams_by_tid, players)
    if data is not None:
        entry = data["entry"]
        sims = load_projected_box_scores()["sims"]
        p_home = safe_float(entry.get("home_win_pct"))
        diff = safe_float(entry.get("home_pts")) - safe_float(entry.get("away_pts"))
        # The page shows this run three ways: the mean score, the share of sims
        # the home team won, and the totals of the rows printed below. On a game
        # near even, rounding and Monte Carlo noise leave them on opposite sides
        # of it — five of the 180 previews at 2,000 sims. Name a favourite only
        # when all three agree; otherwise call the game what it is. A tie counts
        # as disagreement rather than a free pass, because a Total row reading
        # 95.5 against 95.5 has printed a dead heat, and the hero above it may
        # not then name someone a 0.3-point favourite.
        signs = {
            (value > 0) - (value < 0)
            for value in (round(diff, 1), round(projected_printed_margin(data, home_tid), 1),
                          p_home - 0.5)
        }
        if len(signs) > 1:
            diff = 0.0
        runs = f"{fmt_number(sims, 0)} simulations of this game" if sims > 0 else "the simulation below"
        caption = f"Win probability · {runs}"
        spread_title = f"Projected spread — the mean margin across {runs}"
    else:
        strengths = preview_strengths(teams, players, season)
        p_home = preview_home_win_prob(strengths, home_tid, away_tid)
        diff = strengths.get(home_tid, 0.0) - strengths.get(away_tid, 0.0) + SIM_HCA
        caption = "Win probability · same model as the season sim"
        spread_title = (
            f"Projected spread — sim strengths plus a {fmt_number(SIM_HCA, 1)}-point home edge"
        )
    # One-decimal percentages that always sum to 100.0.
    home_pct = round(p_home * 100, 1)
    away_pct = round(100.0 - home_pct, 1)
    home_ab = team_abbrev_for_tid(home_tid, teams_by_tid)
    away_ab = team_abbrev_for_tid(away_tid, teams_by_tid)
    # Spread from the favorite's side: the favorite lays the projected margin.
    if abs(round(diff, 1)) < 0.05:
        spread_text = "Pick 'em"
    else:
        fav_ab = home_ab if diff > 0 else away_ab
        spread_text = f"{fav_ab} {fmt_number(-abs(diff), 1)}"
    fav_side = "home" if diff > 0 else ("away" if diff < 0 else "even")
    aria = (
        f"Projection: {away_ab} {fmt_pct(away_pct, 1)} percent, "
        f"{home_ab} {fmt_pct(home_pct, 1)} percent, spread {spread_text}"
    )
    return f"""
      <div class="gx-proj" role="group" aria-label="{esc(aria)}">
        <div class="gx-proj-nums">
          <span class="gx-proj-side gx-proj-away{' gx-proj-fav' if fav_side == 'away' else ''}">
            <span class="gx-proj-pct">{fmt_pct(away_pct, 1)}%</span>
            <span class="gx-proj-team">{esc(away_ab)}</span>
          </span>
          <span class="gx-proj-spread" title="{esc(spread_title)}">{esc(spread_text)}</span>
          <span class="gx-proj-side gx-proj-home{' gx-proj-fav' if fav_side == 'home' else ''}">
            <span class="gx-proj-pct">{fmt_pct(home_pct, 1)}%</span>
            <span class="gx-proj-team">{esc(home_ab)}</span>
          </span>
        </div>
        <div class="gx-proj-bar" aria-hidden="true"><span class="gx-proj-fill gx-proj-fill-away" style="width:{away_pct}%"></span><span class="gx-proj-fill gx-proj-fill-home" style="width:{home_pct}%"></span></div>
        <p class="gx-proj-caption muted small-copy">{esc(caption)}</p>
      </div>
    """


def team_roster(tid: int, players: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [p for p in players if safe_int(p.get("tid"), -9) == tid and p.get("retiredYear") is None]


# ---------------------------------------------------------------------------
# Projected box scores (Monte Carlo over Basketball GM's own game simulation)
# ---------------------------------------------------------------------------


@functools.lru_cache(maxsize=None)
def load_projected_box_scores() -> dict[str, Any]:
    """Load league-data/projected_box_scores.json once per build (cached).

    Returns ``{"season": int, "sims": int, "games": {gid: entry}}``. Missing,
    empty, unparseable, or the wrong shape → an empty ``games`` map, and every
    preview keeps the rotation table it has today. Same posture portraits.py
    takes toward its cutout manifest: a locally generated, optional input can
    never be the reason a site build fails.
    """
    path = Path(os.environ.get(PROJECTION_PATH_ENV) or PROJECTION_PATH)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"season": -1, "sims": 0, "games": {}}
    if not isinstance(raw, dict):
        return {"season": -1, "sims": 0, "games": {}}
    games = raw.get("games")
    entries = {}
    if isinstance(games, dict):
        for gid, entry in games.items():
            if isinstance(entry, dict) and isinstance(entry.get("players"), list):
                entries[str(gid)] = entry
    return {
        "season": safe_int(raw.get("season"), -1),
        "sims": safe_int(raw.get("sims"), 0),
        "games": entries,
    }


def projected_game(item: dict[str, Any]) -> dict[str, Any] | None:
    """This game's projection, or None when there is no trustworthy one.

    gids are league-local — SMP I and SMP II both number games from zero — so a
    projection is only used when its season AND both tids match the game being
    rendered. That is the same trap ``portraits.has_face`` guards: without the
    match, a file left over from another league paints one game's numbers onto
    whichever game happens to hold that gid now.
    """
    projections = load_projected_box_scores()
    entry = projections["games"].get(str(item.get("gid")))
    if entry is None:
        return None
    if projections["season"] != safe_int(item.get("season"), -2):
        return None
    if safe_int(entry.get("home_tid"), -9) != safe_int(item.get("home_tid"), -8):
        return None
    if safe_int(entry.get("away_tid"), -9) != safe_int(item.get("away_tid"), -8):
        return None
    return entry


def projected_lines(entry: dict[str, Any], tid: int,
                    roster_by_pid: dict[int, dict[str, Any]]) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    """(player, projected line) for one team, ordered by projected minutes desc.

    A row whose pid is not on that roster right now is dropped rather than
    trusted: the file is regenerated by hand, and a trade or a cut between runs
    would otherwise print a player onto the team he just left. The sort is ours,
    not the file's — minutes are the headline, so they set the order.
    """
    out: list[tuple[dict[str, Any], dict[str, Any]]] = []
    seen: set[int] = set()
    for line in entry.get("players") or []:
        if not isinstance(line, dict) or safe_int(line.get("tid"), -9) != tid:
            continue
        pid = safe_int(line.get("pid"), -9)
        player = roster_by_pid.get(pid)
        if player is None or pid in seen:
            continue
        seen.add(pid)
        out.append((player, line))
    out.sort(key=lambda pair: -safe_float(pair[1].get("min")))
    return out


def fmt_projected(value: Any) -> str:
    """Every projected figure prints to one decimal — a mean, never a whole
    number that could be read as something that happened."""
    return fmt_number(safe_float(value), 1)


def projected_pair(made: Any, attempted: Any) -> str:
    """Made-attempted on a projected line: 6.8-14.9, not 45.6%.

    A percentage hides how many shots the projection actually hands him, which
    on a per-game mean is the more interesting half of the pair.
    """
    att = safe_float(attempted)
    if att <= 0:
        return "—"
    return f"{fmt_number(safe_float(made), 1)}-{fmt_number(att, 1)}"


def projected_box_row(player: dict[str, Any], line: dict[str, Any], season: int, root: str,
                      minutes_scale: float, cls: str = "") -> str:
    rating = latest_rating(player, season)
    minutes = safe_float(line.get("min"))
    share = min(100.0, 100.0 * minutes / minutes_scale) if minutes_scale > 0 else 0.0
    trb = safe_float(line.get("trb"))
    cells = [
        td(player_link(player, root), sort=player_name(player), cls="name-cell"),
        td(esc(rating.get("pos") or "—"), sort=rating.get("pos") or ""),
        td(esc(age(player, season))),
        td(fmt_number(rating.get("ovr"), 0), sort=rating.get("ovr")),
        td(fmt_projected(minutes), sort=minutes, cls="gx-pbox-min",
           style=f"--gx-min-share:{share:.1f}%"),
        td(fmt_projected(line.get("pts")), sort=line.get("pts")),
        td(fmt_projected(trb), sort=trb),
        td(fmt_projected(line.get("ast")), sort=line.get("ast")),
        td(fmt_projected(line.get("stl")), sort=line.get("stl")),
        td(fmt_projected(line.get("blk")), sort=line.get("blk")),
        td(projected_pair(line.get("fg"), line.get("fga")), sort=line.get("fg")),
        td(projected_pair(line.get("tp"), line.get("tpa")), sort=line.get("tp")),
        td(projected_pair(line.get("ft"), line.get("fta")), sort=line.get("ft")),
        td(fmt_projected(line.get("tov")), sort=line.get("tov")),
        td(fmt_projected(line.get("pf")), sort=line.get("pf")),
    ]
    cls_attr = f' class="{cls}"' if cls else ""
    return f"<tr{cls_attr}>{''.join(cells)}</tr>"


def projected_totals_row(lines: list[dict[str, Any]]) -> str:
    """Sum of the printed rows only.

    The men under the minutes floor sit in the footer and are left out of the
    total, exactly as DNPs are on a played box score — so the columns the reader
    can see are the columns that add up. Their omission moves the projected team
    score by a fraction of a point.
    """
    def total(key: str) -> float:
        return sum(safe_float(line.get(key)) for line in lines)

    cells = [
        td("Total", sort="zzzz", cls="name-cell total-label"),
        td(""),
        td(""),
        td(""),
        td(fmt_projected(total("min")), sort=total("min"), cls="gx-pbox-min"),
        td(fmt_projected(total("pts")), sort=total("pts")),
        td(fmt_projected(total("trb")), sort=total("trb")),
        td(fmt_projected(total("ast")), sort=total("ast")),
        td(fmt_projected(total("stl")), sort=total("stl")),
        td(fmt_projected(total("blk")), sort=total("blk")),
        td(projected_pair(total("fg"), total("fga")), sort=total("fg")),
        td(projected_pair(total("tp"), total("tpa")), sort=total("tp")),
        td(projected_pair(total("ft"), total("fta")), sort=total("ft")),
        td(fmt_projected(total("tov")), sort=total("tov")),
        td(fmt_projected(total("pf")), sort=total("pf")),
    ]
    return f"<tr class=\"total-row\">{''.join(cells)}</tr>"


def projected_out_footer(players: list[dict[str, Any]], root: str) -> str:
    """Everyone on the roster with no row. Normally that is exactly the two the
    league holds out — the sim is only handed the ten who dress — so the line is
    labelled for what it almost always is, with the tooltip covering the rest."""
    if not players:
        return ""
    links = [f'<a href="{player_url(p, root)}">{esc(player_name(p))}</a>' for p in players]
    return (
        f'<p class="gx-pbox-out small-copy muted" title="{esc(PROJECTED_OUT_TITLE)}">'
        f'<strong>Reserve, not dressed:</strong> {", ".join(links)}</p>'
    )


def projected_box_section(tid: int, playing: list[tuple[dict[str, Any], dict[str, Any]]],
                          benched: list[dict[str, Any]], sims: int, season: int,
                          teams_by_tid: dict[int, dict[str, Any]], root: str,
                          minutes_scale: float) -> str:
    """One team's projected box score: means across the Monte Carlo run.

    Every label on it says projected, because the only thing separating this
    table from a real box score is that none of it has happened. Rows run in
    projected-minutes order — the league asked for minutes first — and the rule
    under the last projected starter is the same one the played box score draws
    under its starting five.
    """
    starters = 0
    for _, line in playing:
        if safe_float(line.get("gs")) < 0.5:
            break
        starters += 1
    rows = []
    for i, (player, line) in enumerate(playing):
        cls = "bench-start" if i == starters and 0 < starters < len(playing) else ""
        rows.append(projected_box_row(player, line, season, root, minutes_scale, cls=cls))
    rows.append(projected_totals_row([line for _, line in playing]))
    headers = "".join([
        th("Name"), th("Pos"), th("Age"), th("Ovr"),
        f'<th scope="col" class="gx-pbox-min" title="{esc(PROJECTED_MIN_TITLE)}">MIN</th>',
        th("PTS"), th("REB"), th("AST"), th("STL"), th("BLK"),
        th("FG"), th("3P"), th("FT"), th("TOV"), th("PF"),
    ])
    runs = f"mean of {fmt_number(sims, 0)} simulations" if sims > 0 else "simulated means"
    team_name = team_full_for_tid(tid, teams_by_tid)
    return f"""
    <section class="box-team-section gx-rot">
      <h2>{team_label(tid, teams_by_tid, root=root)}</h2>
      <p class="gx-rot-cap muted small-copy">Projected box score · {esc(runs)} · no game has been played</p>
      <div class="table-wrap">
        <table data-sortable class="gx-rot-table gx-pbox-table">
          <caption class="sr-only">{esc(team_name)} projected box score — {esc(runs)} of a game not yet played, not a result</caption>
          <thead><tr>{headers}</tr></thead>
          <tbody>{''.join(rows)}</tbody>
        </table>
      </div>
      {projected_out_footer(benched, root)}
    </section>
    """


def projected_box_data(item: dict[str, Any], teams_by_tid: dict[int, dict[str, Any]],
                       players: list[dict[str, Any]]) -> dict[str, Any] | None:
    """THE gate: the projection this page will actually publish, or None.

    Three things on a preview speak for the projection — the hero's spread and
    win probability, the Matchup card's tooltip, and the box scores themselves —
    and every one of them must answer this question the same way. When only the
    body asked, a game whose rows were unusable (all pids off-roster, a side
    thinned below the row floor) fell back to rotation tables while the hero went
    on quoting "200 simulations of this game" at a simulation the page had just
    thrown away. So the decision lives here once and the three callers share it.

    All-or-nothing across both teams on purpose: one side as a box score and the
    other as a ratings table would read as two different claims about one game.
    """
    entry = projected_game(item)
    tids = [
        tid for tid in (safe_int(item.get("away_tid")), safe_int(item.get("home_tid")))
        if tid in teams_by_tid
    ]
    if entry is None or len(tids) != 2:
        return None
    per_tid: dict[int, tuple[list[tuple[dict[str, Any], dict[str, Any]]], list[dict[str, Any]]]] = {}
    for tid in tids:
        roster = team_roster(tid, players)
        lines = projected_lines(entry, tid, {safe_int(p.get("pid"), -9): p for p in roster})
        playing = [pair for pair in lines if safe_float(pair[1].get("min")) >= PROJECTED_MIN_FLOOR]
        if len(playing) < PROJECTED_MIN_ROWS:
            return None
        printed = {safe_int(player.get("pid"), -9) for player, _ in playing}
        benched = [p for p in roster if safe_int(p.get("pid"), -9) not in printed]
        per_tid[tid] = (playing, benched)
    # One minutes scale across both tables: a bar that means something different
    # on the left than on the right is worse than no bar.
    minutes_scale = max(
        (safe_float(line.get("min")) for playing, _ in per_tid.values() for _, line in playing),
        default=0.0,
    )
    return {"entry": entry, "tids": tids, "per_tid": per_tid, "minutes_scale": minutes_scale}


def projected_printed_margin(data: dict[str, Any], home_tid: int) -> float:
    """Home minus away over the rows the box score actually prints.

    Deliberately not ``home_pts - away_pts``: the men under the minutes floor
    sit in the footer and out of the Total row, and every row is rounded to a
    tenth before it is summed. Worth about 0.15 points typically and 0.6 at
    worst — which matters only when the game is close enough for that to change
    who is ahead, and that is exactly when the hero consults it.
    """
    def team_pts(tid: int) -> float:
        return sum(safe_float(line.get("pts")) for _, line in data["per_tid"][tid][0])

    away_tid = next((tid for tid in data["tids"] if tid != home_tid), home_tid)
    return team_pts(home_tid) - team_pts(away_tid)


def projected_box_sections(data: dict[str, Any], season: int,
                           teams_by_tid: dict[int, dict[str, Any]], root: str) -> list[str]:
    """Both projected box scores, rendered from what projected_box_data settled on."""
    sims = load_projected_box_scores()["sims"]
    return [
        projected_box_section(tid, data["per_tid"][tid][0], data["per_tid"][tid][1], sims,
                              season, teams_by_tid, root, data["minutes_scale"])
        for tid in data["tids"]
    ]


def preview_rotation_section(tid: int, players: list[dict[str, Any]], season: int,
                             teams_by_tid: dict[int, dict[str, Any]], root: str) -> str:
    """One team's projected rotation: who plays, and what the sim thinks he is worth.

    Everything here is known before tip-off — the roster, the ratings, and
    simmodel.rotation_impacts, which is literally the per-player term the
    projected spread in the hero is summed from. Rows are in the sim's own
    rotation order, so the reader sees the model's depth chart, not a guess.
    """
    roster = team_roster(tid, players)
    impacts = rotation_impacts(roster, season)
    if not impacts:
        return ""
    rows = []
    for player, impact in impacts:
        rating = latest_rating(player, season)
        rows.append("<tr>" + "".join([
            td(player_link(player, root), sort=player_name(player), cls="name-cell"),
            td(esc(rating.get("pos") or "—"), sort=rating.get("pos") or ""),
            td(esc(age(player, season))),
            td(fmt_number(rating.get("ovr"), 0), sort=rating.get("ovr")),
            td(fmt_number(rating.get("pot"), 0), sort=rating.get("pot")),
            td(fmt_signed(impact, 1), sort=impact, cls="gx-rot-imp"),
        ]) + "</tr>")
    headers = "".join([
        th("Name"), th("Pos"), th("Age"), th("Ovr"), th("Pot"),
        f'<th scope="col" title="{esc(IMPACT_TITLE)}">Imp</th>',
    ])
    reserves = len(roster) - len(impacts)
    reserve_note = (
        f'<p class="gx-rot-reserves muted small-copy">{reserves} more under contract, outside the projected rotation.</p>'
        if reserves > 0 else ""
    )
    return f"""
    <section class="box-team-section gx-rot">
      <h2>{team_label(tid, teams_by_tid, root=root)}</h2>
      <p class="gx-rot-cap muted small-copy">Projected active rotation · in the sim's order</p>
      <div class="table-wrap">
        <table class="gx-rot-table">
          <caption class="sr-only">{esc(team_full_for_tid(tid, teams_by_tid))} projected rotation</caption>
          <thead><tr>{headers}</tr></thead>
          <tbody>{''.join(rows)}</tbody>
        </table>
      </div>
      {reserve_note}
    </section>
    """


def preview_rotations_html(item: dict[str, Any], teams_by_tid: dict[int, dict[str, Any]],
                           players: list[dict[str, Any]], season: int, root: str) -> str:
    """Both projected rotations side by side — the preview's stand-in for a box score.

    When the Monte Carlo has run this game the two panels become projected box
    scores instead; without the file (it is optional and local-only) they stay
    the ratings-and-impact tables.
    """
    data = projected_box_data(item, teams_by_tid, players)
    if data is not None:
        boxes = projected_box_sections(data, season, teams_by_tid, root)
        return f'<div class="gx-rots gx-rots-box">{"".join(boxes)}</div>'
    tids = [
        tid for tid in (safe_int(item.get("away_tid")), safe_int(item.get("home_tid")))
        if tid in teams_by_tid
    ]
    sections = [
        preview_rotation_section(tid, players, season, teams_by_tid, root)
        for tid in tids
    ]
    sections = [s for s in sections if s]
    if not sections:
        return ""
    return f'<div class="gx-rots">{"".join(sections)}</div>'


def clutch_plays_html(item: dict[str, Any], root: str) -> str:
    plays = (item.get("game") or {}).get("clutchPlays") or []
    if not plays:
        return ""
    rendered = []
    for play in plays:
        def repl(match):
            pid = match.group(1)
            label = re.sub(r"<[^>]+>", "", match.group(2))
            return event_player_link(pid, ALL_PLAYERS_BY_PID, root, label=label)
        text = re.sub(r'<a href="[^"]*?/player/(\d+)[^"]*">(.*?)</a>', repl, play)
        text = re.sub(r'<a href="[^"]*">(.*?)</a>', lambda m: esc(re.sub(r"<[^>]+>", "", m.group(1))), text)
        rendered.append(f'<li><span class="badge badge-accent">CLUTCH</span><span>{text}</span></li>')
    return f"""
    <section class="card compact-card">
      <ul class="news-list">{''.join(rendered)}</ul>
    </section>
    """


def render_game_page(item: dict[str, Any], all_items: list[dict[str, Any]], teams: list[dict[str, Any]],
                     players: list[dict[str, Any]], season: int,
                     feats_by_gid: dict[str, list[dict[str, Any]]] | None = None) -> str:
    teams_by_tid = {int(team.get("tid")): team for team in teams if team.get("tid") is not None}
    players_by_pid = {int(player.get("pid")): player for player in players if player.get("pid") is not None}
    ordered_items = sorted(all_items, key=lambda it: (safe_int(it.get("day")), str(it.get("gid"))))
    index = ordered_items.index(item) if item in ordered_items else -1
    prev_item = ordered_items[index - 1] if index > 0 else None
    next_item = ordered_items[index + 1] if 0 <= index < len(ordered_items) - 1 else None
    completed = is_completed_game_item(item)
    if completed:
        projection = ""
        rosters = "".join(
            box_score_team_table(item.get(key) or {}, teams_by_tid, players_by_pid, root="../")
            for key in ("away_box", "home_box")
        )
    else:
        # No Matchup comparison and no injury report: the projected box score below
        # is built from the same rosters and states their difference in the currency
        # that matters — minutes and points — so a table of roster averages beside it
        # was restating the input to a number the page already prints.
        projection = preview_projection_html(item, teams, teams_by_tid, players, season)
        rosters = preview_rotations_html(item, teams_by_tid, players, season, "../")
    series = season_series_html(item, all_items, teams_by_tid, "../")
    clutch = clutch_plays_html(item, "../")
    shots = game_shot_profile(item, teams_by_tid, "../")
    body = f"""
    {box_score_header(item, teams_by_tid, prev_item, next_item, feats_by_gid=feats_by_gid, projection_html=projection)}
    {clutch}
    {rosters}
    {shots}
    {series}
    """
    away_abbrev = team_abbrev_for_tid(item.get("away_tid"), teams_by_tid)
    home_abbrev = team_abbrev_for_tid(item.get("home_tid"), teams_by_tid)
    # A page with no box score on it should not be titled one.
    title = f"{away_abbrev} at {home_abbrev} {'Box Score' if completed else 'Preview'}"
    return page_html(title, body, teams, root="../", active="schedule")
