from __future__ import annotations

import argparse
import html
import json
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
from ..simmodel import SIM_HCA, SIM_LOGISTIC_K, SIM_MOV_BLEND_K, rotation_strength


SHOT_ZONES = [("AtRim", "Rim"), ("LowPost", "Post"), ("MidRange", "Mid"), ("", "3P")]

# Drama-index floor for the "Instant Classic" hero chip. Calibrated on the real
# distribution (479 retained games across seasons 2029-2030): max observed 68,
# only 9 games (~1.9%, about 4-5 per 45-game season) reach 50. Data-driven, not
# per-season: the same bar applies to every future export.
DRAMA_CLASSIC_MIN = 50.0

# FPTS is a local header title because core.GLOSSARY is owned elsewhere.
FPTS_TITLE = "Fantasy points"


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


def selected_box_players(team_box: dict[str, Any]) -> tuple[list[dict[str, Any]], int]:
    """Projected (preview) rotations only: top of the roster, starters first."""
    players = team_box.get("players") or []
    starters = [p for p in players if safe_int(p.get("gs")) > 0]
    active_bench = [p for p in players if p not in starters and (safe_float(p.get("min")) > 0 or safe_int(p.get("gp")) > 0)]
    selected = starters[:5] + active_bench[:5]
    if len(selected) < 10:
        for p in players:
            if p not in selected:
                selected.append(p)
            if len(selected) >= 10:
                break
    bench_start_index = min(5, len(starters[:5]))
    return selected[:10], bench_start_index


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
    if player_box.get("_projected"):
        row = "".join([
            td(box_player_link(player_box, players_by_pid, root), sort=player_box.get("name"), cls="name-cell"),
            td(esc(player_box.get("pos", "—")), sort=player_box.get("pos", "")),
            *[td("—") for _ in range(15)],
        ])
        cls_attr = f' class="{cls}"' if cls else ""
        return f"<tr{cls_attr}>{row}</tr>"

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


def projected_team_box(tid: Any, players: list[dict[str, Any]], season: int) -> dict[str, Any]:
    tid_int = safe_int(tid)
    roster = [p for p in players if p.get("tid") == tid_int and p.get("retiredYear") is None]
    roster.sort(key=lambda p: (-safe_int(latest_rating(p, season).get("ovr")), player_name(p)))
    selected = roster[:10]
    projected_players: list[dict[str, Any]] = []
    for i, player in enumerate(selected):
        rating = latest_rating(player, season)
        projected_players.append({
            "pid": player.get("pid"),
            "name": player_name(player),
            "pos": rating.get("pos", "—"),
            "jerseyNumber": player.get("jerseyNumber"),
            "skills": rating.get("skills") or [],
            "gs": 1 if i < 5 else 0,
            "_projected": True,
        })
    return {"tid": tid_int, "players": projected_players, "_projected": True}


def box_score_team_table(team_box: dict[str, Any], teams_by_tid: dict[int, dict[str, Any]], players_by_pid: dict[int, dict[str, Any]], root: str) -> str:
    tid = safe_int(team_box.get("tid"))
    team_name = team_full_for_tid(tid, teams_by_tid)
    if team_box.get("_projected"):
        selected, bench_index = selected_box_players(team_box)
        dnp: list[dict[str, Any]] = []
    else:
        selected, bench_index, dnp = played_box_players(team_box)
    rows: list[str] = []
    for i, player_box in enumerate(selected):
        cls = "bench-start" if i == bench_index and i > 0 else ""
        rows.append(box_score_player_row(player_box, players_by_pid, root, cls=cls))
    if not team_box.get("_projected"):
        rows.append(box_team_totals_row(team_box))
        rows.append(box_team_percentages_row(team_box))
    note = '<p class="muted small-copy">Projected active rotation · stats arrive after tip-off.</p>' if team_box.get("_projected") else ""
    header_html = "".join(th(label) for label in ["Name", "Pos", "MP", "FG", "3P", "FT", "ORB", "TRB", "AST", "TOV", "STL", "BLK", "BA", "PF", "PTS", "+/-"]) + fpts_th()
    return f"""
    <section class="box-team-section">
      <h2>{team_label(tid, teams_by_tid, root=root)}</h2>
      {note}
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
        return f'<span class="button-link gx-pager disabled">{esc(dir_text)}</span>'
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
    if wins[tid_a] == wins[tid_b]:
        series_text = f"Series tied {wins[tid_a]}-{wins[tid_b]}" if completed else "First meeting of the season"
    else:
        lead_tid = tid_a if wins[tid_a] > wins[tid_b] else tid_b
        trail = min(wins.values())
        series_text = f"{team_abbrev_for_tid(lead_tid, teams_by_tid)} lead{'s' if True else ''} the series {max(wins.values())}-{trail}"
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
        chips.append(f'<a class="{cls}" href="{esc(game_url(m, root))}">{label}</a>')
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
    """Hero centerpiece for unplayed games: both win probabilities + the spread."""
    home_tid = safe_int(item.get("home_tid"))
    away_tid = safe_int(item.get("away_tid"))
    if home_tid not in teams_by_tid or away_tid not in teams_by_tid:
        return ""
    strengths = preview_strengths(teams, players, season)
    p_home = preview_home_win_prob(strengths, home_tid, away_tid)
    diff = strengths.get(home_tid, 0.0) - strengths.get(away_tid, 0.0) + SIM_HCA
    # One-decimal percentages that always sum to 100.0.
    home_pct = round(p_home * 100, 1)
    away_pct = round(100.0 - home_pct, 1)
    home_ab = team_abbrev_for_tid(home_tid, teams_by_tid)
    away_ab = team_abbrev_for_tid(away_tid, teams_by_tid)
    # Spread from the favorite's side: home lays -(sH-sA+HCA) points.
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
          <span class="gx-proj-spread" title="Projected spread — sim strengths plus a {fmt_number(SIM_HCA, 1)}-point home edge">{esc(spread_text)}</span>
          <span class="gx-proj-side gx-proj-home{' gx-proj-fav' if fav_side == 'home' else ''}">
            <span class="gx-proj-pct">{fmt_pct(home_pct, 1)}%</span>
            <span class="gx-proj-team">{esc(home_ab)}</span>
          </span>
        </div>
        <div class="gx-proj-bar" aria-hidden="true"><span class="gx-proj-fill gx-proj-fill-away" style="width:{away_pct}%"></span><span class="gx-proj-fill gx-proj-fill-home" style="width:{home_pct}%"></span></div>
        <p class="gx-proj-caption muted small-copy">Win probability · same model as the season sim</p>
      </div>
    """


def preview_team_metrics(team: dict[str, Any], season: int) -> dict[str, Any]:
    team_season = latest_team_season(team, season)
    stat = latest_team_stat(team, season)
    fga = safe_float(stat.get("fga"))
    fta = safe_float(stat.get("fta"))
    tov = safe_float(stat.get("tov"))
    efg = 100 * (safe_float(stat.get("fg")) + 0.5 * safe_float(stat.get("tp"))) / fga if fga else None
    tovp = 100 * tov / (fga + 0.44 * fta + tov) if (fga + 0.44 * fta + tov) else None
    ftr = safe_float(stat.get("ft")) / fga if fga else None
    return {
        "record": fmt_record(team_season.get("won"), team_season.get("lost")),
        "streak": streak_text(team_season.get("streak")),
        "l10": last_ten_text(team_season.get("lastTen")),
        "ppg": team_stat_per_game(stat, "pts"),
        "papg": team_stat_per_game(stat, "oppPts"),
        "mov": team_mov(stat),
        "efg": efg,
        "tovp": tovp,
        "ftr": ftr,
    }


def game_preview_html(item: dict[str, Any], teams_by_tid: dict[int, dict[str, Any]], players: list[dict[str, Any]], season: int, root: str) -> str:
    away_team = teams_by_tid.get(safe_int(item.get("away_tid")))
    home_team = teams_by_tid.get(safe_int(item.get("home_tid")))
    if not away_team or not home_team:
        return ""
    away = preview_team_metrics(away_team, season)
    home = preview_team_metrics(home_team, season)
    rows_spec = [
        ("Record", "record", None),
        ("Streak", "streak", None),
        ("Last 10", "l10", None),
        ("Points/G", "ppg", 1),
        ("Allowed/G", "papg", 1),
        ("MOV", "mov", "signed"),
        ("eFG%", "efg", 1),
        ("TOV%", "tovp", 1),
        ("FT/FGA", "ftr", "ratio"),
    ]
    rows = []
    for label, key, fmt in rows_spec:
        def render(value):
            if fmt is None:
                return esc(value)
            if fmt == "signed":
                return fmt_signed(value, 1)
            if fmt == "ratio":
                return fmt_ratio(value, 3)
            return fmt_number(value, fmt)
        rows.append(
            f"<tr><td>{render(away.get(key))}</td>"
            f'<td class="cmp-label">{esc(label)}</td>'
            f"<td>{render(home.get(key))}</td></tr>"
        )
    injuries = []
    for team, side in ((away_team, "away"), (home_team, "home")):
        tid = safe_int(team.get("tid"))
        hurt = [
            p for p in players
            if safe_int(p.get("tid"), -9) == tid and (p.get("injury") or {}).get("type") not in (None, "", "Healthy")
        ]
        if hurt:
            bits = []
            for p in sorted(hurt, key=lambda p: -safe_int((p.get("injury") or {}).get("gamesRemaining"))):
                injury = p.get("injury") or {}
                bits.append(
                    f'<a class="player-link" href="{player_url(p, root)}">{esc(player_name(p))}</a> '
                    f'<span class="injured">({esc(injury.get("type"))}, {safe_int(injury.get("gamesRemaining"))} games)</span>'
                )
            injuries.append(f'<p class="small-copy"><strong>{esc(team_abbrev(team))}:</strong> {" · ".join(bits)}</p>')
        else:
            injuries.append(f'<p class="small-copy"><strong>{esc(team_abbrev(team))}:</strong> <span class="healthy">no injuries</span></p>')
    return f"""
    <section class="card">
      <div class="section-title-row"><h2>Matchup</h2><span class="muted small-copy">season-to-date</span></div>
      <div class="table-wrap fit-table">
        <table class="cmp-table">
          <thead><tr><th>{team_label(item.get("away_tid"), teams_by_tid, root)}</th><th></th><th>{team_label(item.get("home_tid"), teams_by_tid, root)}</th></tr></thead>
          <tbody>{''.join(rows)}</tbody>
        </table>
      </div>
      <div class="preview-injuries">
        <h3 class="small-copy muted">INJURY REPORT</h3>
        {''.join(injuries)}
      </div>
    </section>
    """


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
    home_box = item.get("home_box") or projected_team_box(item.get("home_tid"), players, season)
    away_box = item.get("away_box") or projected_team_box(item.get("away_tid"), players, season)
    completed = is_completed_game_item(item)
    preview = "" if completed else game_preview_html(item, teams_by_tid, players, season, "../")
    projection = "" if completed else preview_projection_html(item, teams, teams_by_tid, players, season)
    series = season_series_html(item, all_items, teams_by_tid, "../")
    clutch = clutch_plays_html(item, "../")
    shots = game_shot_profile(item, teams_by_tid, "../")
    body = f"""
    {box_score_header(item, teams_by_tid, prev_item, next_item, feats_by_gid=feats_by_gid, projection_html=projection)}
    {clutch}
    {preview}
    {box_score_team_table(away_box, teams_by_tid, players_by_pid, root='../')}
    {box_score_team_table(home_box, teams_by_tid, players_by_pid, root='../')}
    {shots}
    {series}
    """
    away_abbrev = team_abbrev_for_tid(item.get("away_tid"), teams_by_tid)
    home_abbrev = team_abbrev_for_tid(item.get("home_tid"), teams_by_tid)
    title = f"{away_abbrev} at {home_abbrev} Box Score"
    return page_html(title, body, teams, root="../", active="schedule")
