from __future__ import annotations

import argparse
import colorsys
import html
import itertools
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
    RATING_GROUP_STARTS,
    TEAM_RATING_RANK_KEYS,
    acquisition_html,
    active_team_ids,
    active_teams_for_season,
    age,
    regular_season_length,
    build_game_logs,
    canonical_pos,
    completed_game_items,
    current_season,
    draft_slot,
    draft_transaction,
    esc,
    fmt_contract,
    fmt_draft_slot,
    fmt_money,
    fmt_number,
    fmt_pct,
    fmt_record,
    fmt_signed,
    fmt_win_pct,
    game_ot_label,
    game_recap_text,
    game_sort_key,
    game_url,
    game_winner_tid,
    get_attr_value,
    heat_style,
    initials,
    injury_html,
    is_completed_game_item,
    item_team_points,
    latest_rating,
    latest_regular_stat,
    latest_team_season,
    latest_team_stat,
    made_pct,
    page_html,
    per_game,
    player_link,
    player_name,
    player_url,
    rating_delta_html,
    safe_float,
    safe_int,
    season_regular_stat,
    standings_order,
    stat_gp,
    streak_text,
    table_html,
    td,
    team_abbrev,
    team_abbrev_for_tid,
    team_full_name,
    team_label,
    team_schedule_result,
    team_slug,
    win_pct,
)

from ..derived import four_factors

from ..identity import monogram_svg, team_css_vars, team_identity

from ..portraits import portrait_html

from ..finance import (
    FIN_CHAMP,
    FIN_FINALS,
    FIN_BASE,
    FIN_PER_WIN,
    FIN_PLAYOFF_WIN,
    FIN_PLAYOFF,
    fmt_money_pm,
    team_finances_table,
)


def _fin_mil(amount: float) -> str:
    """Exact short money label for a FIN_* constant ($5.3M, $7M) — fmt_money
    renders 5300 as "$5.30M", which reads wrong in rules copy."""
    return f"${amount / 1000:g}M"


def _money(amount: Any) -> str:
    """fmt_money with a sane zero.

    Salaries are stored in thousands and fmt_money switches to a $NNNK label
    below a million, so exactly zero comes out as "$0K" — which showed up in the
    hero as "Cap space $0K" for a team sitting exactly on the line, and as the
    "Now" total of a ledger that has not earned anything yet. Zero is $0."""
    return "$0" if abs(safe_float(amount)) < 1e-9 else fmt_money(amount)


def _cap_rules(data: dict[str, Any] | None, season: int) -> dict[str, Any]:
    """The league's cap rules for ``season``, read straight off gameAttributes so
    the team pages can never drift from the export: {"cap", "type", "hard",
    "enforced", "minimum"} (money in thousands). ``cap`` is 0.0 when the export
    carries none, which is the signal for the cap cards to render nothing at all.

    ``type`` is Basketball GM's salaryCapType verbatim — "hard", "soft" or
    "none". SMP II runs "none", so salaryCap is only a reference line (the
    league-average payroll target the salary curve is built around) and nothing
    on the page may describe it as a limit; ``enforced`` is the single flag the
    copy branches on.
    """
    ga = (data or {}).get("gameAttributes") or {}
    cap_type = str(get_attr_value(ga.get("salaryCapType"), season) or "")
    return {
        "cap": safe_float(get_attr_value(ga.get("salaryCap"), season), 0.0),
        "type": cap_type,
        "hard": cap_type == "hard",
        "enforced": cap_type in ("hard", "soft"),
        "minimum": safe_float(get_attr_value(ga.get("minContract"), season), 0.0),
    }


# ---------------------------------------------------------------------------
# Team-immersion helpers: identity scope wrapper, color ramps, small tiles
# ---------------------------------------------------------------------------


def team_scope_html(team: dict[str, Any], body: str) -> str:
    """Wrap a team page body in a div carrying the team's --team-* css vars,
    with the two-color jersey stripe pinned along the top."""
    tid = safe_int(team.get("tid"), -1)
    return (
        f'<div class="team-scope" style="{team_css_vars(tid)}">'
        '<div class="tm-stripe" aria-hidden="true"></div>'
        f"{body}</div>"
    )


def _hex_rgb(color: str) -> tuple:
    c = str(color).lstrip("#")
    if len(c) == 3:
        c = "".join(ch * 2 for ch in c)
    try:
        return tuple(int(c[i:i + 2], 16) for i in (0, 2, 4))
    except ValueError:
        return (90, 100, 110)


def _mix_hex(a: str, b: str, t: float) -> str:
    """Linear RGB mix of two hex colors; t=0 -> a, t=1 -> b."""
    t = max(0.0, min(1.0, t))
    ra, rb = _hex_rgb(a), _hex_rgb(b)
    return "#%02x%02x%02x" % tuple(int(round(ca + (cb - ca) * t)) for ca, cb in zip(ra, rb))


def _lighten_hex(color: str, amount: float) -> str:
    """Shift lightness in HLS space; positive lightens, negative darkens."""
    r, g, b = (v / 255.0 for v in _hex_rgb(color))
    h, l, s = colorsys.rgb_to_hls(r, g, b)
    l = max(0.0, min(1.0, l + amount))
    rr, gg, bb = colorsys.hls_to_rgb(h, l, s)
    return "#%02x%02x%02x" % (int(round(rr * 255)), int(round(gg * 255)), int(round(bb * 255)))


def team_color_ramp(tid: Any, n: int) -> list[str]:
    """n distinct band colors derived from the team's identity (secondary -> primary),
    with alternating lightness so adjacent stacked-bar segments stay separable. Fixed
    hexes on purpose: the fills sit on a neutral panel in both themes."""
    ident = team_identity(tid)
    a, b = ident["secondary"], ident["primary"]
    out = []
    for i in range(max(1, n)):
        t = i / (n - 1) if n > 1 else 0.0
        base = _mix_hex(a, b, t)
        if i % 2 == 1:
            base = _lighten_hex(base, 0.12)
        out.append(base)
    return out


def _on_hex(color: str) -> str:
    """Legible text color (white / near-black) for a fixed hex background."""
    r, g, b = _hex_rgb(color)
    luminance = (0.2126 * r + 0.7152 * g + 0.0722 * b) / 255.0
    return "#10131a" if luminance > 0.55 else "#ffffff"


def _tile(label: str, value: str, cls: str = "", tip: str | None = None) -> str:
    """One .vital-tile stat chip, optionally with an explainer tooltip."""
    tip_attr = f' title="{esc(tip)}"' if tip else ""
    tip_cls = " has-tip" if tip else ""
    cls_attr = f' class="{esc(cls)}"' if cls else ""
    return (
        f'<div class="vital-tile{tip_cls}"{tip_attr}><span>{esc(label)}</span>'
        f"<strong{cls_attr}>{value}</strong></div>"
    )


def _team_completed_window(team: dict[str, Any], game_items: list[dict[str, Any]], season: int) -> tuple[list[dict[str, Any]], int]:
    """Completed regular-season games involving the team for ``season``; when that
    season has none yet (preseason), fall back to the latest season present in
    ``game_items`` so team pages stay honest instead of empty. Returns
    (window, display_season)."""
    tid = safe_int(team.get("tid"))
    involved = [
        item for item in game_items
        if is_completed_game_item(item)
        and not item.get("playoffs")
        and tid in (safe_int(item.get("home_tid")), safe_int(item.get("away_tid")))
    ]
    involved.sort(key=game_sort_key)
    window = [item for item in involved if safe_int(item.get("season")) == season]
    if window:
        return window, season
    seasons = [safe_int(item.get("season")) for item in involved]
    if not seasons:
        return [], season
    display = max(seasons)
    return [item for item in involved if safe_int(item.get("season")) == display], display


def _portrait(player: dict[str, Any], cls: str, root: str) -> str:
    """portraits.portrait_html with a monogram guard: a player with neither photo
    nor rendered face must never break the build (portrait_html's final fallback
    currently passes an unsupported kwarg to monogram_svg)."""
    try:
        return portrait_html(player, cls, root)
    except TypeError:
        mono = monogram_svg(initials(player), player.get("tid"),
                            jersey_number=player.get("jerseyNumber"))
        return (f'<span class="{esc(cls)} portrait-monogram" role="img" '
                f'aria-label="{esc(player_name(player))}">{mono}</span>')


def _roundel(player: dict[str, Any], cls: str, root: str) -> str:
    """Portrait with a monogram layered underneath: when a hotlinked photo 404s
    for a player with no rendered face, the portrait chain hides the bitmap —
    the monogram beneath keeps the roundel from ever rendering empty."""
    mono = monogram_svg(initials(player), player.get("tid"), css_class="monogram tm-under")
    return f"{mono}{_portrait(player, cls, root)}"


def team_games_strip(team: dict[str, Any], game_items: list[dict[str, Any]], teams_by_tid: dict[int, dict[str, Any]], season: int | None = None) -> str:
    tid = safe_int(team.get("tid"))
    involved = [
        item for item in game_items
        if safe_int(item.get("home_tid")) == tid or safe_int(item.get("away_tid")) == tid
    ]
    involved.sort(key=game_sort_key)
    played = [item for item in involved if is_completed_game_item(item)]
    upcoming = [item for item in involved if not is_completed_game_item(item)]
    chips = []
    for item in played[-5:]:
        result = team_schedule_result(item, tid)
        ot = game_ot_label(item)
        if ot:
            result += f" {ot}"
        opp_tid = item.get("away_tid") if safe_int(item.get("home_tid")) == tid else item.get("home_tid")
        loc = "vs." if safe_int(item.get("home_tid")) == tid else "@"
        cls = "chip-win" if result.startswith("W") else "chip-loss"
        chips.append(
            f'<a class="game-chip {cls}" href="{esc(game_url(item, "../"))}">'
            f'<span>Day {safe_int(item.get("day"))} {loc} {esc(team_abbrev_for_tid(opp_tid, teams_by_tid))}</span>'
            f'<strong>{esc(result)}</strong></a>'
        )
    for item in upcoming[:5]:
        opp_tid = item.get("away_tid") if safe_int(item.get("home_tid")) == tid else item.get("home_tid")
        loc = "vs." if safe_int(item.get("home_tid")) == tid else "@"
        chips.append(
            f'<a class="game-chip chip-next" href="{esc(game_url(item, "../"))}">'
            f'<span>Day {safe_int(item.get("day"))}</span>'
            f'<strong>{loc} {esc(team_abbrev_for_tid(opp_tid, teams_by_tid))}</strong></a>'
        )
    if not chips:
        return ""
    # The caption has to describe the chips that actually rendered. "last 5 ·
    # next 5" was printed unconditionally, so a preseason team with nothing but
    # a schedule advertised five results it did not have.
    n_back, n_fwd = len(played[-5:]), len(upcoming[:5])
    bits = []
    if n_back:
        bits.append(f"last {n_back}")
    if n_fwd:
        bits.append(f"next {n_fwd}")
    note = " · ".join(bits)
    if season is not None and played and not upcoming:
        played_seasons = {safe_int(item.get("season")) for item in played}
        if season not in played_seasons:
            latest = max(played_seasons)
            note = f"final {n_back} games of {latest} · no {season} games yet"
    elif season is not None and not played:
        note = f"first {n_fwd} games of {season} · none played yet"
    return f"""
    <section class="card">
      <div class="section-title-row"><h2>Form &amp; Upcoming</h2><span class="muted small-copy">{esc(note)}</span></div>
      <div class="game-strip">{''.join(chips)}</div>
    </section>
    """


def team_games_table(team: dict[str, Any], game_items: list[dict[str, Any]], teams_by_tid: dict[int, dict[str, Any]], season: int) -> str:
    tid = safe_int(team.get("tid"))
    all_involved = [
        item for item in game_items
        if not item.get("playoffs")
        and tid in (safe_int(item.get("home_tid")), safe_int(item.get("away_tid")))
    ]
    involved = [item for item in all_involved if safe_int(item.get("season")) == season]
    display_season = season
    if not involved and all_involved:
        # Honest preseason state: no current-season games exist yet, so show the
        # last completed season's log with clear labeling instead of nothing.
        display_season = max(safe_int(item.get("season")) for item in all_involved)
        involved = [item for item in all_involved if safe_int(item.get("season")) == display_season]
    involved.sort(key=game_sort_key)
    if not involved:
        return ""
    completed_count = sum(1 for item in involved if is_completed_game_item(item))
    # Before the first tip-off every Result cell reads "Upcoming" and every Note
    # cell reads "Scheduled" — two full columns of the same word, 36 rows deep.
    # They carry information the moment one game is final, so the columns come
    # back on their own rather than on a season check.
    show_result = completed_count > 0
    rows = []
    for item in involved:
        home = safe_int(item.get("home_tid")) == tid
        opp_tid = item.get("away_tid") if home else item.get("home_tid")
        completed = is_completed_game_item(item)
        result = team_schedule_result(item, tid)
        ot = game_ot_label(item)
        if ot and completed:
            result += f" {ot}"
        team_pts = item_team_points(item, tid)
        opp_pts = item_team_points(item, safe_int(opp_tid))
        # Opponent + home/away in one cell: "vs. GOO" at home, "@ GOO" on the road.
        opp_prefix = "vs." if home else "@"
        opp_cell = f'{opp_prefix} {team_label(opp_tid, teams_by_tid, "../")}'
        # `result` already includes the score (e.g. "W 112-108"), which is why the old
        # Result and Score columns were redundant — collapse to just this one.
        result_cell = esc(result) if completed else "Upcoming"
        margin = (safe_float(team_pts) - safe_float(opp_pts)) if completed else -999
        note = game_recap_text(item, teams_by_tid) if completed else "Scheduled"
        cls = "game-log-win" if result.startswith("W") else "game-log-loss" if result.startswith("L") else "game-log-next"
        cells = [
            td(fmt_number(item.get("day"), 0), sort=safe_int(item.get("day"))),
            td(opp_cell, sort=team_abbrev_for_tid(opp_tid, teams_by_tid), cls="name-cell"),
        ]
        if show_result:
            cells.append(td(result_cell, sort=margin))
            cells.append(td(esc(note), sort=note, cls="game-note"))
        cells.append(td(f'<a class="button-link table-link" href="{esc(game_url(item, "../"))}">'
                        f'{"View" if completed else "Preview"}</a>', sort=safe_int(item.get("day"))))
        rows.append(
            f'<tr class="click-row {cls}" data-href="{esc(game_url(item, "../"))}">'
            + "".join(cells)
            + "</tr>"
        )
    headers = ["Day", "Opponent", "Result", "Note", "Link"] if show_result else ["Day", "Opponent", "Link"]
    if display_season == season:
        title = "All Games"
        note = f"{completed_count} completed · {len(involved) - completed_count} upcoming"
        caption = f"{team_full_name(team)} current-season game log"
    else:
        title = f"{display_season} Season Log"
        note = f"no {season} games yet · full {display_season} log ({completed_count} games)"
        caption = f"{team_full_name(team)} {display_season} season game log"
    # A three-column fixture list stretched over a full-width card leaves the
    # opponent floating in the middle of nowhere; shrink-wrap it left the way
    # every other narrow table on the site does.
    wrap_cls = "" if show_result else "fit-table"
    return f"""
    <section class="card">
      <div class="section-title-row"><h2>{esc(title)}</h2><span class="muted small-copy">{esc(note)}</span></div>
      {table_html(headers, rows, table_id=f"team-{tid}-games", empty_message="No games found.", caption=caption, wrap_cls=wrap_cls)}
    </section>
    """


def team_playoffs_table(team: dict[str, Any], game_items: list[dict[str, Any]], teams_by_tid: dict[int, dict[str, Any]], season: int) -> str:
    """Playoff games for the season shown on the Games page (the regular-season
    table deliberately excludes them, so surface the postseason run here)."""
    tid = safe_int(team.get("tid"))
    all_involved = [
        item for item in game_items
        if item.get("playoffs") and is_completed_game_item(item)
        and tid in (safe_int(item.get("home_tid")), safe_int(item.get("away_tid")))
    ]
    involved = [item for item in all_involved if safe_int(item.get("season")) == season]
    display_season = season
    if not involved and all_involved:
        display_season = max(safe_int(item.get("season")) for item in all_involved)
        involved = [item for item in all_involved if safe_int(item.get("season")) == display_season]
    if not involved:
        return ""
    involved.sort(key=game_sort_key)
    rows = []
    for item in involved:
        home = safe_int(item.get("home_tid")) == tid
        opp_tid = item.get("away_tid") if home else item.get("home_tid")
        result = team_schedule_result(item, tid)
        ot = game_ot_label(item)
        if ot:
            result += f" {ot}"
        opp_prefix = "vs." if home else "@"
        margin = safe_float(item_team_points(item, tid)) - safe_float(item_team_points(item, safe_int(opp_tid)))
        cls = "game-log-win" if result.startswith("W") else "game-log-loss"
        rows.append(
            f'<tr class="click-row {cls}" data-href="{esc(game_url(item, "../"))}">'
            + "".join([
                td(fmt_number(item.get("day"), 0), sort=safe_int(item.get("day"))),
                td(f'{opp_prefix} {team_label(opp_tid, teams_by_tid, "../")}', sort=team_abbrev_for_tid(opp_tid, teams_by_tid), cls="name-cell"),
                td(esc(result), sort=margin),
                td(esc(game_recap_text(item, teams_by_tid)), sort="", cls="game-note"),
                td(f'<a class="button-link table-link" href="{esc(game_url(item, "../"))}">View</a>', sort=safe_int(item.get("day"))),
            ])
            + "</tr>"
        )
    return f"""
    <section class="card">
      <div class="section-title-row"><h2>{display_season} Playoffs</h2><span class="muted small-copy">{len(involved)} postseason games</span></div>
      {table_html(["Day", "Opponent", "Result", "Note", "Link"], rows, table_id=f"team-{tid}-playoff-games", empty_message="No playoff games.", caption=f"{team_full_name(team)} {display_season} playoff game log")}
    </section>
    """


DEPTH_SLOTS = ["PG", "SG", "SF", "PF", "C"]

# Fixed shape so every team's chart reads the same. The league caps rosters at 12
# (gameAttributes.maxRosterSize), so 5 + 5 + 2 covers the whole player list.
DEPTH_ROWS = [("Starters", 5), ("Bench", 5), ("Reserve", 2)]


def _fitted_slots(group: list[dict[str, Any]], season: int) -> list[tuple[int, dict[str, Any]]]:
    """Give each player in ``group`` a distinct PG..C slot, minimising the total
    displacement along the PG-SG-SF-PF-C spine. Returns (slot index, player)
    pairs already in left-to-right slot order.

    Solved as an assignment problem rather than a greedy left-to-right pass,
    which strands players in silly slots (a leftover center at SG). Five slots
    means at most 120 permutations, so brute force is the lazy correct answer.
    Assignments that tie on the total are broken twice more. First on the gap
    profile, worst gap first: a bench of four point guards and one power forward
    has several fits totalling 7 and only the flattest one avoids printing "C"
    over a point guard. Then on the per-player gaps in ``group`` order, which is
    overall-descending, so the higher-rated of two point guards keeps PG. BBGM's
    combo labels (G/GF/F/FC) reach the spine already collapsed by canonical_pos,
    the same rounding every other surface on the site shows.
    """
    natural = [DEPTH_SLOTS.index(canonical_pos(p, latest_rating(p, season))) for p in group]

    def cost(slots: tuple[int, ...]) -> tuple[int, tuple[int, ...], tuple[int, ...]]:
        gaps = tuple(abs(slot - nat) for slot, nat in zip(slots, natural))
        return sum(gaps), tuple(sorted(gaps, reverse=True)), gaps

    best = min(itertools.permutations(range(len(DEPTH_SLOTS)), len(group)), key=cost)
    return sorted(zip(best, group), key=lambda pair: pair[0])


def _injury_cross(player: dict[str, Any]) -> str:
    injury = player.get("injury") or {}
    if injury.get("type") and injury.get("type") != "Healthy":
        return ' <span class="injured" title="' + esc(injury.get("type", "")) + '">✚</span>'
    return ""


DEPTH_STAT_KEYS = [("pts", "PTS"), ("trb", "REB"), ("ast", "AST"), ("stl", "STL"), ("blk", "BLK")]


def _depth_played_stat(player: dict[str, Any], season: int, start_season: int) -> dict[str, Any]:
    """The player's latest regular-season line that has games in it, or {}.

    Split out of _depth_stat_line so the card and the card's legend read the same
    data: in year one nothing qualifies for anybody, and the legend has to know
    that before it promises per-game numbers the cards cannot show."""
    played = {
        s["season"] for s in player.get("stats") or []
        if isinstance(s, dict) and not s.get("playoffs")
        and isinstance(s.get("season"), int) and start_season <= s["season"] <= season
        and stat_gp(s) > 0
    }
    return season_regular_stat(player, max(played)) if played else {}


def _depth_stat_line(player: dict[str, Any], season: int, start_season: int) -> str:
    """PTS/REB/AST/STL/BLK per-game chips from the player's latest season with
    games played (0-GP rows skipped); an em-dash line when he has none."""
    stat = _depth_played_stat(player, season, start_season)
    gp = stat_gp(stat)
    bits = []
    for key, label in DEPTH_STAT_KEYS:
        if gp > 0:
            raw = (safe_float(stat.get("orb")) + safe_float(stat.get("drb"))) if key == "trb" else safe_float(stat.get(key))
            value = fmt_number(raw / gp, 1)
        else:
            value = "—"
        bits.append(f'<span class="depth-stat"><strong>{value}</strong><small>{label}</small></span>')
    return f'<span class="depth-line">{"".join(bits)}</span>'


def _depth_card(player: dict[str, Any], slot: str, season: int, start_season: int) -> str:
    """One horizontal depth card: portrait on the left, name/jersey/OVR and the
    per-game stat line stacked on the right.

    The label is the slot the player is filling, not necessarily what he is. When
    the two differ the label gets a dotted underline and names his real position
    on hover (title) — chosen over a printed marker because it keeps the row
    scannable while never letting the chart claim a center is a shooting guard.
    A title attribute reaches nobody who is not holding a mouse, so the same
    correction is repeated for screen readers inside the card's link text.
    """
    rating = latest_rating(player, season)
    natural = canonical_pos(player, rating)
    pos_cls = "depth-pos" if natural == slot else "depth-pos depth-pos--fitted"
    pos_tip = "" if natural == slot else f' title="Natural position: {natural}"'
    pos_sr = "" if natural == slot else f'<span class="sr-only"> (natural position {natural})</span>'
    jersey = player.get("jerseyNumber")
    jersey_bit = f'<span class="depth-num">#{esc(jersey)}</span>' if jersey not in (None, "") else ""
    return (
        f'<a class="depth-card" href="{player_url(player, "../")}">'
        f'<span class="depth-portrait-wrap">{_roundel(player, "depth-portrait", "../")}</span>'
        '<span class="depth-main">'
        f'<span class="depth-card-top"><span class="{pos_cls}"{pos_tip}>{slot}{pos_sr}</span>'
        f'<span class="depth-ovr" title="Overall rating">{esc(rating.get("ovr", "—"))}</span></span>'
        f'<span class="depth-id"><span class="depth-name">{esc(player_name(player))}</span>{_injury_cross(player)}{jersey_bit}</span>'
        f"{_depth_stat_line(player, season, start_season)}"
        "</span></a>"
    )


def depth_chart_card(roster: list[dict[str, Any]], season: int, start_season: int = 0) -> str:
    """Depth chart as three fixed rows: Starters (5) / Bench (5) / Reserve (2).

    Driven by the player list, not by position buckets: the roster in the order
    the roster table and players/index.html use it (overall desc, then name) is
    sliced top-down, so every team's chart has the same shape instead of a lumpy
    one that depends on which positions happened to draft two bodies. Inside a
    row the players are fitted to PG/SG/SF/PF/C by nearest position — see
    _fitted_slots — and a card whose slot is not its natural position says so on
    hover. The Reserve row holds its two cards at full width rather than padding
    out to five, and a short roster simply stops when the players run out.
    """
    ordered = _depth_order(roster, season)
    # The caption is a legend, so it may only name markers the cards actually
    # carry. In preseason no player has a played season and nobody is hurt, so
    # the old fixed string promised "per-game from latest season played" over
    # twelve cards of em-dashes and a "✚ injured" key for a cross that appears
    # nowhere — and on a phone it wrapped to three lines to do it. Both clauses
    # are now conditional on the roster, so they return the moment they mean
    # something.
    has_stats = any(_depth_played_stat(p, season, start_season) for p in ordered)
    has_injury = any(_injury_cross(p) for p in ordered)
    by_order = all(isinstance(p.get("rosterOrder"), int) for p in ordered)
    legend = ["starters / bench / reserve" if by_order else "top 5 / next 5 / last 2 by overall",
              "each row fitted to PG–C"]
    legend.append("per-game from latest season played" if has_stats else "no games played yet")
    if has_injury:
        legend.append("✚ injured")
    rows_html = []
    taken = 0
    for label, size in DEPTH_ROWS:
        group = ordered[taken:taken + size]
        taken += size
        if not group:
            break
        cards = "".join(
            _depth_card(player, DEPTH_SLOTS[slot], season, start_season)
            for slot, player in _fitted_slots(group, season)
        )
        rows_html.append(
            f'<div class="depth-row"><h3 class="depth-row-label">{label}</h3>'
            f'<div class="depth-row-cards">{cards}</div></div>'
        )
    return f"""
    <section class="card depth-chart-card">
      <div class="section-title-row"><h2>Depth Chart</h2><span class="muted small-copy">{esc(" · ".join(legend))}</span></div>
      <div class="depth-rows">{''.join(rows_html)}</div>
    </section>
    """


def _rotation_rows(tid: int, gids: list[str], game_logs: dict[int, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    """Per-player minutes across a window of games (by gid), attributed to the
    team the player was logged with (mid-season trades stay honest). Sorted by
    total minutes desc, then name; players with zero minutes are dropped."""
    gid_set = set(gids)
    rows_by_pid: dict[int, dict[str, Any]] = {}
    for pid, entries in game_logs.items():
        for entry in entries:
            if safe_int(entry.get("tid"), -999) != tid:
                continue
            gid = str(entry.get("gid"))
            if gid not in gid_set:
                continue
            minutes = safe_float((entry.get("box") or {}).get("min"))
            if minutes <= 0:
                continue
            box = entry.get("box") or {}
            player = ALL_PLAYERS_BY_PID.get(pid)
            name = player_name(player) if player else str(box.get("name") or f"Player {pid}")
            label = player_link(player, "../", show_number=False) if player else f'<span class="player-link">{esc(name)}</span>'
            row = rows_by_pid.setdefault(pid, {"pid": pid, "name": name, "label": label, "minutes_by_gid": defaultdict(float)})
            row["minutes_by_gid"][gid] += minutes
    rows = []
    for row in rows_by_pid.values():
        window_minutes = [row["minutes_by_gid"].get(gid, 0.0) for gid in gids]
        total = sum(window_minutes)
        if total <= 0:
            continue
        rows.append({**row, "minutes": window_minutes, "total": total})
    rows.sort(key=lambda r: (-r["total"], r["name"]))
    return rows


def _window_header_bits(item: dict[str, Any], tid: int, teams_by_tid: dict[int, dict[str, Any]]) -> tuple[str, str, str]:
    """(loc, opp_abbrev, result) chips for one completed game from the team's view."""
    opp_tid = item.get("away_tid") if safe_int(item.get("home_tid")) == tid else item.get("home_tid")
    loc = "vs" if safe_int(item.get("home_tid")) == tid else "@"
    result = team_schedule_result(item, tid)
    return loc, team_abbrev_for_tid(opp_tid, teams_by_tid), result


def rotation_map_card(team: dict[str, Any], roster: list[dict[str, Any]], game_items: list[dict[str, Any]], game_logs: dict[int, list[dict[str, Any]]], season: int, teams_by_tid: dict[int, dict[str, Any]]) -> str:
    tid = safe_int(team.get("tid"))
    window, display_season = _team_completed_window(team, game_items, season)
    if not window:
        return ""
    gids = [str(item.get("gid")) for item in window]
    header_cells = ['<th class="name-cell">Player</th>']
    for item in window:
        won = game_winner_tid(item) == tid
        loc, opp, _result = _window_header_bits(item, tid, teams_by_tid)
        cls = "rot-w" if won else "rot-l"
        header_cells.append(
            f'<th class="{cls}" data-gid="{esc(item.get("gid"))}" title="Day {safe_int(item.get("day"))} {loc} {esc(opp)}">'
            f'{safe_int(item.get("day"))}</th>'
        )

    row_data = _rotation_rows(tid, gids, game_logs)
    if not row_data:
        return ""
    max_minutes = max((m for row in row_data for m in row["minutes"]), default=0.0)
    body_rows = []
    for row in row_data:
        cells = [td(row["label"], sort=row["name"], cls="name-cell")]
        for gid, minutes in zip(gids, row["minutes"]):
            if minutes <= 0:
                cells.append(td('<span class="muted">·</span>', sort=0, cls="rot-cell"))
            else:
                frac = min(1.0, minutes / max_minutes) if max_minutes > 0 else 0.0
                hue = 4 + 126 * frac
                alpha = 0.18 + 0.34 * frac
                style = f"background-color: hsla({hue:.0f}, 58%, 42%, {alpha:.2f})"
                cells.append(td(fmt_number(minutes, 0), sort=minutes, cls="rot-cell", style=style))
        body_rows.append(f'<tr data-pid="{row["pid"]}">{"".join(cells)}</tr>')
    body_html = "".join(body_rows)
    season_note = "this season" if display_season == season else f"in {display_season} (no {season} games yet)"
    return f"""
    <section class="card">
      <div class="section-title-row"><h2>Rotation Map</h2><span class="muted small-copy">{len(window)} games {esc(season_note)} · red to green = minutes · · = DNP</span></div>
      <div class="table-wrap fit-table">
        <table class="rotation-map" data-rotation-table="{tid}">
          <thead><tr>{''.join(header_cells)}</tr></thead>
          <tbody>{body_html}</tbody>
        </table>
      </div>
    </section>
    """


# ---------------------------------------------------------------------------
# Scoring share (100%-stacked bar with PTS / FGA / AST toggle)
# ---------------------------------------------------------------------------

SHARE_METRICS = [
    ("pts", "PTS", "points"),
    ("fga", "FGA", "field-goal attempts"),
    ("ast", "AST", "assists"),
]


def _share_display_season(roster: list[dict[str, Any]], season: int) -> int | None:
    """Latest season <= season in which anyone on the current roster logged
    regular-season games."""
    seasons = set()
    for p in roster:
        for s in p.get("stats") or []:
            if (isinstance(s, dict) and not s.get("playoffs")
                    and isinstance(s.get("season"), int) and s["season"] <= season
                    and stat_gp(s) > 0):
                seasons.add(s["season"])
    return max(seasons) if seasons else None


def scoring_share_card(team: dict[str, Any], roster: list[dict[str, Any]], season: int) -> str:
    """B21: who the offense runs through — a sorted 100%-stacked horizontal bar
    of each player's share of team PTS, toggleable to FGA and AST share."""
    display = _share_display_season(roster, season)
    if display is None:
        return ""
    per_player: list[dict[str, Any]] = []
    for p in roster:
        stat = season_regular_stat(p, display)
        if not stat or stat_gp(stat) <= 0:
            continue
        per_player.append({
            "pid": safe_int(p.get("pid"), -1),
            "player": p,
            "name": player_name(p),
            "pts": safe_float(stat.get("pts")),
            "fga": safe_float(stat.get("fga")),
            "ast": safe_float(stat.get("ast")),
        })
    if not per_player:
        return ""
    # Stable color per player from the team ramp, keyed by PTS rank so colors
    # do not reshuffle when toggling metrics.
    per_player.sort(key=lambda r: (-r["pts"], r["name"]))
    colors = team_color_ramp(safe_int(team.get("tid")), len(per_player))
    for i, row in enumerate(per_player):
        row["color"] = colors[i]

    tid = safe_int(team.get("tid"))
    buttons = []
    panels = []
    for mi, (key, label, noun) in enumerate(SHARE_METRICS):
        total = sum(r[key] for r in per_player)
        if total <= 0:
            continue
        ordered = sorted(per_player, key=lambda r: (-r[key], r["name"]))
        segs = []
        for row in ordered:
            share = 100.0 * row[key] / total
            if share <= 0:
                continue
            label_html = f"<span>{esc(row['name'].split(' ')[-1])}</span>" if share >= 8.0 else ""
            segs.append(
                f'<div class="share-seg" style="width:{share:.2f}%;background:{row["color"]};color:{_on_hex(row["color"])}" '
                f'title="{esc(row["name"])} — {share:.1f}% of team {label} ({fmt_number(row[key], 0)})">{label_html}</div>'
            )
        top3 = " · ".join(f'{r["name"]} {100.0 * r[key] / total:.1f}%' for r in ordered[:3])
        first = not buttons
        buttons.append(
            f'<button type="button" data-share-metric="{key}" class="{"active" if first else ""}" '
            f'aria-pressed="{"true" if first else "false"}">{label}</button>'
        )
        panels.append(
            f'<div class="share-bar" data-share-panel="{key}" role="img" '
            f'aria-label="Share of team {noun}: {esc(top3)}"{"" if first else " hidden"}>{"".join(segs)}</div>'
        )
    if not panels:
        return ""
    legend = "".join(
        f'<a class="share-chip" href="{player_url(row["player"], "../")}" style="--share-color:{row["color"]}">'
        f'<span class="share-chip-dot"></span>{esc(row["name"])}</a>'
        for row in per_player
    )
    note = f"{display} totals · current roster" if display != season else "this season · current roster"
    return f"""
    <section class="card share-card" data-share-card>
      <div class="section-title-row"><h2>Scoring Share</h2>
        <div class="share-toggle" role="group" aria-label="Share metric">{''.join(buttons)}</div>
      </div>
      {''.join(panels)}
      <div class="share-legend">{legend}</div>
      <p class="muted small-copy">{esc(note)}</p>
    </section>"""


# ---------------------------------------------------------------------------
# Four factors vs league average (diverging strip)
# ---------------------------------------------------------------------------

# (key, label, higher_is_better, format digits, is_ratio)
FF_ROWS = [
    ("efg", "eFG%", True, 1, False),
    ("tov_pct", "TOV%", False, 1, False),
    ("orb_pct", "ORB%", True, 1, False),
    ("ft_rate", "FT/FGA", True, 3, True),
    ("opp_efg", "Opp eFG%", False, 1, False),
    ("opp_tov_pct", "Opp TOV%", True, 1, False),
    ("opp_orb_pct", "Opp ORB%", False, 1, False),
    ("opp_ft_rate", "Opp FT/FGA", False, 3, True),
]


def four_factors_card(data: dict[str, Any], team: dict[str, Any], teams: list[dict[str, Any]], season: int) -> str:
    """B16(b): Dean Oliver four factors (offense + defense) as a diverging strip
    against the league average for the same season."""
    tid = safe_int(team.get("tid"))
    # Latest season <= season with real team stats (preseason rows are all zero).
    display = None
    for cand in range(season, season - 8, -1):
        row = latest_team_stat(team, cand)
        if safe_int(row.get("season"), -1) == cand and safe_float(row.get("gp")) > 0:
            display = cand
            break
    if display is None:
        return ""
    league_rows = []
    own = None
    for t in active_teams_for_season(teams, display):
        stat = latest_team_stat(t, display)
        if safe_int(stat.get("season"), -1) != display or safe_float(stat.get("gp")) <= 0:
            continue
        ff = four_factors(stat)
        league_rows.append(ff)
        if safe_int(t.get("tid"), -99) == tid:
            own = ff
    if own is None or len(league_rows) < 2:
        return ""

    width = 660.0
    ml, mr = 92.0, 96.0
    row_h, top = 27.0, 8.0
    plot_w = width - ml - mr
    half = plot_w / 2.0
    center_x = ml + half
    height = top + row_h * len(FF_ROWS) + 20.0

    parts = [
        f'<line x1="{center_x:.1f}" y1="{top:.1f}" x2="{center_x:.1f}" y2="{top + row_h * len(FF_ROWS):.1f}" class="ff-center"/>',
        f'<text x="{center_x:.1f}" y="{height - 6:.1f}" class="chart-tick" text-anchor="middle">league average</text>',
    ]
    for ri, (key, label, higher_better, digits, is_ratio) in enumerate(FF_ROWS):
        y = top + ri * row_h
        bar_y = y + 6.0
        bar_h = row_h - 12.0
        values = [safe_float(r.get(key), float("nan")) for r in league_rows]
        values = [v for v in values if math.isfinite(v)]
        value = own.get(key)
        if value is None or not values:
            continue
        value = safe_float(value)
        avg = sum(values) / len(values)
        max_dev = max((abs(v - avg) for v in values), default=0.0)
        dev = value - avg
        good = (dev > 0) == higher_better if abs(dev) > 1e-9 else None
        frac = 0.0 if max_dev <= 1e-9 else max(-1.0, min(1.0, dev / max_dev))
        # Bars diverge by GOODNESS, not raw sign: better than league always
        # extends right (e.g. a low Opp eFG% is a right-side green bar).
        plot_frac = frac if higher_better else -frac
        bar_w = abs(plot_frac) * (half - 6.0)
        bar_x = center_x if plot_frac >= 0 else center_x - bar_w
        cls = "ff-bar-good" if good else ("ff-bar-bad" if good is not None else "ff-bar-flat")
        fmt_v = fmt_number(value, digits)
        fmt_avg = fmt_number(avg, digits)
        delta_txt = f"{'+' if dev > 0 else ''}{fmt_number(dev, digits)}"
        parts.append(f'<g class="ff-row"><title>{esc(label)}: {fmt_v} vs league {fmt_avg} ({delta_txt})</title>')
        parts.append(f'<text x="{ml - 8:.1f}" y="{y + row_h / 2 + 3.5:.1f}" class="ff-label" text-anchor="end">{esc(label)}</text>')
        parts.append(f'<rect x="{ml:.1f}" y="{bar_y:.1f}" width="{plot_w:.1f}" height="{bar_h:.1f}" class="ff-track"/>')
        if bar_w > 0.5:
            parts.append(f'<rect x="{bar_x:.1f}" y="{bar_y:.1f}" width="{bar_w:.1f}" height="{bar_h:.1f}" class="{cls}"/>')
        val_cls = "ff-val-good" if good else ("ff-val-bad" if good is not None else "ff-val")
        parts.append(
            f'<text x="{ml + plot_w + 8:.1f}" y="{y + row_h / 2 + 3.5:.1f}" class="{val_cls}" text-anchor="start">'
            f"{fmt_v} <tspan class=\"ff-delta\">({delta_txt})</tspan></text>"
        )
        parts.append("</g>")

    season_note = f"{display} season" + ("" if display == season else f" · no {season} team stats yet")
    return f"""
    <section class="card ff-card">
      <div class="section-title-row"><h2>Four Factors</h2><span class="muted small-copy">{esc(season_note)} · right of center = better than league average</span></div>
      <div class="chart-wrap ff-wrap">
        <svg viewBox="0 0 {width:.0f} {height:.0f}" class="ff-chart" role="img" aria-label="Four factors vs league average, {esc(display)} season">
          {''.join(parts)}
        </svg>
      </div>
    </section>"""


def team_quarter_profile(team: dict[str, Any], data: dict[str, Any], season: int, teams_by_tid: dict[int, dict[str, Any]]) -> str:
    tid = safe_int(team.get("tid"))
    # Honest preseason state: profile the latest season that actually has games.
    if not completed_game_items(data, season, playoffs=False):
        candidates = [
            safe_int(g.get("season")) for g in data.get("games", [])
            if isinstance(g.get("season"), int) and safe_int(g.get("season")) <= season
        ]
        if not candidates:
            return ""
        season = max(candidates)
    own_q = [0.0, 0.0, 0.0, 0.0]
    opp_q = [0.0, 0.0, 0.0, 0.0]
    games = 0
    close_w = close_l = ot_w = ot_l = 0
    biggest_win = None
    biggest_loss = None
    for item in completed_game_items(data, season, playoffs=False):
        if safe_int(item.get("home_tid")) == tid:
            own, opp = item.get("home_box") or {}, item.get("away_box") or {}
        elif safe_int(item.get("away_tid")) == tid:
            own, opp = item.get("away_box") or {}, item.get("home_box") or {}
        else:
            continue
        games += 1
        own_qtrs = own.get("ptsQtrs") or []
        opp_qtrs = opp.get("ptsQtrs") or []
        for i in range(4):
            own_q[i] += safe_float(own_qtrs[i]) if i < len(own_qtrs) else 0.0
            opp_q[i] += safe_float(opp_qtrs[i]) if i < len(opp_qtrs) else 0.0
        margin = safe_float(own.get("pts")) - safe_float(opp.get("pts"))
        won = margin > 0
        overtimes = safe_int((item.get("game") or {}).get("overtimes"))
        if overtimes:
            ot_w += 1 if won else 0
            ot_l += 0 if won else 1
        if abs(margin) <= 5:
            close_w += 1 if won else 0
            close_l += 0 if won else 1
        if won and (biggest_win is None or margin > biggest_win[0]):
            biggest_win = (margin, item)
        if not won and (biggest_loss is None or margin < biggest_loss[0]):
            biggest_loss = (margin, item)
    if not games:
        return ""

    def qtr_row(label, values, other):
        cells = [td(esc(label), cls="name-cell")]
        for i in range(4):
            diff = values[i] / games - other[i] / games
            cells.append(td(fmt_number(values[i] / games, 1), sort=values[i], style=heat_style(diff, -4, 4, 1)))
        return "<tr>" + "".join(cells) + "</tr>"

    def game_chip(entry, label):
        if not entry:
            return ""
        margin, item = entry
        opp_tid = item.get("away_tid") if safe_int(item.get("home_tid")) == tid else item.get("home_tid")
        own_pts = item_team_points(item, tid)
        opp_pts = item_team_points(item, safe_int(opp_tid))
        return (
            f'<div class="vital-tile"><span>{esc(label)}</span>'
            f'<strong><a href="{esc(game_url(item, "../"))}">{fmt_signed(margin, 0)} vs {esc(team_abbrev_for_tid(opp_tid, teams_by_tid))}'
            f' ({fmt_number(own_pts, 0)}-{fmt_number(opp_pts, 0)})</a></strong></div>'
        )

    # aggregate shot zones for the season
    zone_totals = defaultdict(float)
    for item in completed_game_items(data, season, playoffs=False):
        if safe_int(item.get("home_tid")) == tid:
            own_box = item.get("home_box") or {}
        elif safe_int(item.get("away_tid")) == tid:
            own_box = item.get("away_box") or {}
        else:
            continue
        for key in ("fgAtRim", "fgaAtRim", "fgLowPost", "fgaLowPost", "fgMidRange", "fgaMidRange", "tp", "tpa"):
            zone_totals[key] += safe_float(own_box.get(key))
    total_fga = zone_totals["fgaAtRim"] + zone_totals["fgaLowPost"] + zone_totals["fgaMidRange"] + zone_totals["tpa"]
    shot_rows = ""
    if total_fga > 0:
        mix_cells = []
        pct_cells = []
        for made_key, att_key in (("fgAtRim", "fgaAtRim"), ("fgLowPost", "fgaLowPost"), ("fgMidRange", "fgaMidRange"), ("tp", "tpa")):
            att = zone_totals[att_key]
            mix = 100 * att / total_fga
            pct = made_pct(zone_totals[made_key], att)
            mix_cells.append(td(fmt_number(mix, 1) + "%", sort=mix))
            pct_cells.append(td(fmt_pct(pct, 1), sort=pct))
        shot_rows = (
            '<tr>' + td("Shot mix", cls="name-cell") + "".join(mix_cells) + '</tr>'
            '<tr>' + td("FG%", cls="name-cell") + "".join(pct_cells) + '</tr>'
        )
    shot_table = f"""
    <div class="table-wrap fit-table">
      <table class="qtr-table">
        <thead><tr><th></th><th>Rim</th><th>Post</th><th>Mid</th><th>3P</th></tr></thead>
        <tbody>{shot_rows}</tbody>
      </table>
    </div>
    """ if shot_rows else ""

    table = f"""
    <div class="table-wrap fit-table">
      <table class="qtr-table">
        <thead><tr><th></th><th>Q1</th><th>Q2</th><th>Q3</th><th>Q4</th></tr></thead>
        <tbody>
          {qtr_row("Scored", own_q, opp_q)}
          {qtr_row("Allowed", opp_q, own_q)}
        </tbody>
      </table>
    </div>
    {shot_table}
    """
    team_season = latest_team_season(team, season)
    home_rec = fmt_record(team_season.get("wonHome"), team_season.get("lostHome"))
    road_rec = fmt_record(team_season.get("wonAway"), team_season.get("lostAway"))
    top4 = set(standings_order(active_teams_for_season([t for t in teams_by_tid.values()], season), season)[:4])
    top4_w = top4_l = 0
    for item in completed_game_items(data, season, playoffs=False):
        if safe_int(item.get("home_tid")) == tid:
            opp = safe_int(item.get("away_tid"))
        elif safe_int(item.get("away_tid")) == tid:
            opp = safe_int(item.get("home_tid"))
        else:
            continue
        if opp in top4:
            if game_winner_tid(item) == tid:
                top4_w += 1
            else:
                top4_l += 1
    tiles = "".join([
        f'<div class="vital-tile"><span>Home / Road</span><strong>{esc(home_rec)} / {esc(road_rec)}</strong></div>',
        f'<div class="vital-tile"><span>vs top 4</span><strong>{top4_w}-{top4_l}</strong></div>',
        f'<div class="vital-tile"><span>Close games (≤5)</span><strong>{close_w}-{close_l}</strong></div>',
        f'<div class="vital-tile"><span>Overtime</span><strong>{ot_w}-{ot_l}</strong></div>',
        game_chip(biggest_win, "Biggest win"),
        game_chip(biggest_loss, "Worst loss"),
    ])
    return f"""
    <section class="card">
      <div class="section-title-row"><h2>Game Profile</h2><span class="muted small-copy">{season} · points per quarter · green = outscoring</span></div>
      <div class="profile-row">
        {table}
        <div class="vitals-row">{tiles}</div>
      </div>
    </section>
    """


def draft_picks_card(data: dict[str, Any], team: dict[str, Any], teams_by_tid: dict[int, dict[str, Any]]) -> str:
    tid = safe_int(team.get("tid"))
    picks = [
        dp for dp in data.get("draftPicks", [])
        if isinstance(dp, dict) and safe_int(dp.get("tid"), -10) == tid and isinstance(dp.get("season"), int)
    ]
    if not picks:
        return ""
    picks.sort(key=lambda dp: (dp.get("season"), safe_int(dp.get("round"))))
    chips = []
    for dp in picks:
        rnd = "" if safe_int(dp.get("round")) == 1 else " 2nd"  # single-round league: no "1st"
        own = safe_int(dp.get("originalTid"), -10) == tid
        via = "" if own else f' <span class="muted">via {esc(team_abbrev(teams_by_tid.get(safe_int(dp.get("originalTid"), -10))))}</span>'
        chips.append(f'<span class="pick-chip{" pick-own" if own else " pick-acquired"}">{esc(dp.get("season"))}{rnd}{via}</span>')
    traded_away = [
        dp for dp in data.get("draftPicks", [])
        if isinstance(dp, dict) and safe_int(dp.get("originalTid"), -10) == tid and safe_int(dp.get("tid"), -10) != tid
    ]
    away_note = ""
    if traded_away:
        away_bits = []
        for dp in sorted(traded_away, key=lambda dp: (dp.get("season"), safe_int(dp.get("round")))):
            rnd = "" if safe_int(dp.get("round")) == 1 else " 2nd"
            holder = team_abbrev(teams_by_tid.get(safe_int(dp.get("tid"), -10)))
            away_bits.append(f"{dp.get('season')}{rnd} → {holder}")
        away_note = f'<p class="muted small-copy">Traded away: {esc(" · ".join(away_bits))}</p>'
    return f"""
    <section class="card">
      <div class="section-title-row"><h2>Draft Picks</h2><span class="count-pill">{len(picks)} owned</span></div>
      <div class="pick-row">{''.join(chips)}</div>
      {away_note}
    </section>
    """


# ---------------------------------------------------------------------------
# Franchise Arc (teams/{slug}-history.html)
# ---------------------------------------------------------------------------


def _round_name(round_index_1based: int, total_rounds: int) -> str:
    from_end = total_rounds - round_index_1based
    if from_end <= 0:
        return "Finals"
    if from_end == 1:
        return "Semifinals"
    if from_end == 2:
        return "Quarterfinals"
    return f"Round {round_index_1based}"


def franchise_seasons(team: dict[str, Any], data: dict[str, Any], teams: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One summary row per completed (or in-progress) season the franchise has
    actually played: record, league finish, playoff result. Data-driven off the
    team's seasons rows + playoffSeries; the empty preseason row is skipped."""
    tid = safe_int(team.get("tid"))
    cur = current_season(data)
    champs = champions_by_season(data)
    out = []
    for srow in team.get("seasons") or []:
        if not isinstance(srow, dict):
            continue
        s = srow.get("season")
        won, lost = safe_int(srow.get("won")), safe_int(srow.get("lost"))
        if not isinstance(s, int) or won + lost == 0:
            continue
        order = standings_order(active_teams_for_season(teams, s), s)
        finish = (order.index(tid) + 1) if tid in order else None
        prw = safe_int(srow.get("playoffRoundsWon"), -1)
        info = champs.get(s)
        rounds = info["rounds"] if info else 2
        if info and info["champ"] == tid:
            result, kind = "Champion", "champ"
        elif info and info["runner_up"] == tid:
            result, kind = "Lost Finals", "finals"
        elif s == cur and s not in champs:
            result, kind = "In progress", "live"
        elif prw >= 0:
            result, kind = f"Lost {_round_name(prw + 1, rounds)}", "out"
        else:
            result, kind = "Missed playoffs", "miss"
        stat = latest_team_stat(team, s)
        gp = safe_float(stat.get("gp")) if safe_int(stat.get("season"), -1) == s else 0.0
        out.append({
            "season": s, "won": won, "lost": lost,
            "pct": win_pct(won, lost), "finish": finish,
            "result": result, "kind": kind,
            "ps": (safe_float(stat.get("pts")) / gp) if gp > 0 else None,
            "pa": (safe_float(stat.get("oppPts")) / gp) if gp > 0 else None,
        })
    out.sort(key=lambda r: r["season"])
    return out


def _first_season(team: dict[str, Any], data: dict[str, Any] | None) -> int | None:
    """Earliest season the franchise has a row for — its founding year as far as
    the export is concerned. Falls back to the current season for a team the
    export has not written a seasons row for yet."""
    seasons = [s.get("season") for s in (team.get("seasons") or []) if isinstance(s, dict)]
    seasons = [s for s in seasons if isinstance(s, int)]
    if seasons:
        return min(seasons)
    return current_season(data) if data else None


def _franchise_file_tiles(team: dict[str, Any], roster: list[dict[str, Any]], data: dict[str, Any] | None) -> str:
    """The charter facts a franchise has before it has played anything: the year
    it started, how many of the current roster it drafted, and its colors."""
    tid = safe_int(team.get("tid"), -1)
    ident = team_identity(tid)
    tiles = []
    born = _first_season(team, data)
    if born is not None:
        tiles.append(_tile("First season", esc(born)))
    drafted = [p for p in roster if draft_transaction(p)]
    if drafted:
        tiles.append(_tile("Drafted", f"{len(drafted)} of {len(roster)}",
                           tip="Players on the roster this franchise took at a league draft, "
                               "rather than signing or trading for."))
    # The tile's whole value is two colour chips, so the hex has to be readable
    # by something other than a mouse pointer: title alone leaves the tile empty
    # for a screen reader and unreachable from the keyboard.
    swatches = "".join(
        f'<span class="tm-swatch" role="img" style="background:{esc(ident[key])}" '
        f'title="{esc(label)} {esc(ident[key])}" aria-label="{esc(label)} {esc(ident[key])}"></span>'
        for key, label in (("primary", "Primary"), ("secondary", "Secondary"))
    )
    tiles.append(_tile("Colors", f'<span class="tm-swatches">{swatches}</span>'))
    return f'<div class="vitals-row">{"".join(tiles)}</div>'


def franchise_arc_card(team: dict[str, Any], data: dict[str, Any], teams: list[dict[str, Any]], teams_by_tid: dict[int, dict[str, Any]], roster: list[dict[str, Any]] | None = None) -> str:
    """C26: the W/L ribbon — wins up, losses down, playoff exits and title flags
    along the top.

    Before the franchise has finished a season there is no ribbon to draw, and a
    bare "nothing here" line left the whole History page 200px tall. The empty
    branch instead says what the chart will be and carries the facts that DO
    exist in year one — founding season, colors, how much of the roster the
    franchise drafted itself."""
    rows = franchise_seasons(team, data, teams)
    if not rows:
        cur = current_season(data)
        year = f" the day {cur} is in the books" if isinstance(cur, int) else " once a season is played out"
        return f"""
    <section class="card">
      <div class="section-title-row"><h2>Franchise Arc</h2><span class="muted small-copy">nothing on the board yet</span></div>
      <p class="empty-state">No completed seasons yet — the wins-and-losses ribbon, the playoff exit over
      each column and the title flags all start filling in{esc(year)}.</p>
      {_franchise_file_tiles(team, roster or [], data)}
    </section>"""
    n = len(rows)
    max_wl = max(max(r["won"], r["lost"]) for r in rows) or 1

    ml, mr = 46.0, 16.0
    col_w = max(64.0, min(96.0, 560.0 / n))
    marker_y = 16.0
    win_h_max, loss_h_max = 82.0, 58.0
    axis_y = 34.0 + win_h_max
    height = axis_y + loss_h_max + 44.0
    width = ml + col_w * n + mr
    bar_w = min(36.0, col_w * 0.46)

    parts = [
        f'<line x1="{ml - 6:.1f}" y1="{axis_y:.1f}" x2="{width - mr + 4:.1f}" y2="{axis_y:.1f}" class="arc-axis"/>',
        f'<text x="{ml - 10:.1f}" y="{axis_y - win_h_max / 2:.1f}" class="arc-side" text-anchor="middle" transform="rotate(-90 {ml - 10:.1f} {axis_y - win_h_max / 2:.1f})">W</text>',
        f'<text x="{ml - 10:.1f}" y="{axis_y + loss_h_max / 2 + 4:.1f}" class="arc-side" text-anchor="middle" transform="rotate(-90 {ml - 10:.1f} {axis_y + loss_h_max / 2 + 4:.1f})">L</text>',
    ]
    for i, r in enumerate(rows):
        cx = ml + col_w * i + col_w / 2
        win_h = win_h_max * r["won"] / max_wl
        loss_h = loss_h_max * r["lost"] / max_wl
        title = f'{r["season"]}: {r["won"]}-{r["lost"]} · {r["result"]}'
        parts.append(f'<g class="arc-col"><title>{esc(title)}</title>')
        parts.append(f'<rect x="{cx - bar_w / 2:.1f}" y="{axis_y - win_h:.1f}" width="{bar_w:.1f}" height="{max(1.0, win_h):.1f}" class="arc-win"/>')
        parts.append(f'<rect x="{cx - bar_w / 2:.1f}" y="{axis_y + 1:.1f}" width="{bar_w:.1f}" height="{max(1.0, loss_h):.1f}" class="arc-loss"/>')
        parts.append(f'<text x="{cx:.1f}" y="{axis_y - win_h - 5:.1f}" class="arc-num" text-anchor="middle">{r["won"]}</text>')
        parts.append(f'<text x="{cx:.1f}" y="{axis_y + loss_h + 13:.1f}" class="arc-num arc-num-loss" text-anchor="middle">{r["lost"]}</text>')
        # Playoff exit marker / title flag along the top rail.
        if r["kind"] == "champ":
            parts.append(f'<polygon points="{_star_points(cx - 26, marker_y - 3.4, 5.0, 2.0)}" class="arc-flag"/>')
            parts.append(f'<text x="{cx + 4:.1f}" y="{marker_y:.1f}" class="arc-marker arc-marker-champ" text-anchor="middle">TITLE</text>')
        elif r["kind"] == "finals":
            parts.append(f'<text x="{cx:.1f}" y="{marker_y:.1f}" class="arc-marker arc-marker-finals" text-anchor="middle">Finals</text>')
        elif r["kind"] == "out":
            short = r["result"].replace("Lost ", "")
            parts.append(f'<text x="{cx:.1f}" y="{marker_y:.1f}" class="arc-marker" text-anchor="middle">{esc(short)}</text>')
        elif r["kind"] == "live":
            parts.append(f'<text x="{cx:.1f}" y="{marker_y:.1f}" class="arc-marker" text-anchor="middle">Live</text>')
        parts.append(f'<text x="{cx:.1f}" y="{height - 6:.1f}" class="chart-tick" text-anchor="middle">{r["season"]}</text>')
        parts.append("</g>")

    titles = sum(1 for r in rows if r["kind"] == "champ")
    sub = f"{rows[0]['season']}–{rows[-1]['season']} · {titles} championship{'' if titles == 1 else 's'}"
    return f"""
    <section class="card arc-card">
      <div class="section-title-row"><h2>Franchise Arc</h2><span class="muted small-copy">{esc(sub)} · hover a column for detail</span></div>
      <div class="chart-wrap arc-wrap">
        <svg viewBox="0 0 {width:.0f} {height:.0f}" class="arc-chart" role="img" aria-label="Season-by-season wins and losses for {esc(team_full_name(team))}">
          {''.join(parts)}
        </svg>
      </div>
    </section>"""


def season_results_card(team: dict[str, Any], data: dict[str, Any], teams: list[dict[str, Any]]) -> str:
    rows_data = franchise_seasons(team, data, teams)
    if not rows_data:
        return ""
    body_rows = []
    for r in sorted(rows_data, key=lambda r: -r["season"]):
        result_cls = {"champ": "delta-up", "finals": "", "live": "muted", "miss": "muted"}.get(r["kind"], "")
        result_html = f'<span class="{result_cls}">{esc(r["result"])}</span>' if result_cls else esc(r["result"])
        if r["kind"] == "champ":
            result_html = f'<span class="arc-flag-inline" aria-hidden="true">★</span> {result_html}'
        body_rows.append("".join([
            td(esc(r["season"]), sort=r["season"]),
            td(fmt_record(r["won"], r["lost"]), sort=r["won"]),
            td(fmt_win_pct(r["pct"]), sort=r["pct"]),
            td(fmt_number(r["ps"], 1) if r["ps"] is not None else "—", sort=r["ps"]),
            td(fmt_number(r["pa"], 1) if r["pa"] is not None else "—", sort=r["pa"]),
            td(f'#{r["finish"]}' if r["finish"] else "—", sort=r["finish"]),
            td(result_html, sort=r["result"]),
        ]))
    return f"""
    <section class="card">
      <div class="section-title-row"><h2>Season Results</h2><span class="count-pill">{len(rows_data)} seasons</span></div>
      {table_html(["Season", "Record", "Pct", "PS", "PA", "Finish", "Playoffs"], body_rows, table_id=f"team-{safe_int(team.get('tid'))}-seasons", empty_message="No seasons yet.", caption=f"{team_full_name(team)} season-by-season results")}
    </section>"""


def redraft_board_card(roster: list[dict[str, Any]], season: int, root: str = "../") -> str:
    """The franchise's own draft board: everyone still on the roster that this
    team drafted, in the order it called their names.

    Year one is the reason this exists. A franchise with no seasons behind it
    has exactly one piece of history — the draft that built it — and the roster
    page only shows the slot as a right-hand "Acquired" note sorted by overall
    rating, which is the wrong axis to read a draft on. It keeps earning its
    place afterwards: players who arrive by trade or free agency are simply not
    on the board, so the card shrinks as the original squad is broken up.
    """
    picks = []
    for player in roster:
        tx = draft_transaction(player)
        if not tx:
            continue
        overall = safe_int(tx.get("pickNum"), 0)
        picks.append({
            "player": player,
            "overall": overall if overall > 0 else 10 ** 6,
            "slot": fmt_draft_slot(draft_slot(player)),
            "season": safe_int(tx.get("season"), 0),
        })
    if not picks:
        return ""
    picks.sort(key=lambda p: (p["overall"], player_name(p["player"])))
    seasons = sorted({p["season"] for p in picks if p["season"]})
    title = f"{seasons[0]} Redraft" if len(seasons) == 1 else "Redraft Board"

    tiles = []
    for pick in picks:
        player = pick["player"]
        rating = latest_rating(player, season)
        ovr = rating.get("ovr")
        meta = " · ".join(str(bit) for bit in (
            rating.get("pos") or "", age(player, season), f"{ovr} ovr" if ovr is not None else "",
        ) if bit not in ("", None))
        slot = pick["slot"] or f"#{pick['overall']}"
        tiles.append(
            f'<a class="rd-pick" href="{player_url(player, root)}">'
            f'<span class="rd-slot">{esc(slot)}</span>'
            '<span class="rd-body">'
            f'<span class="rd-name">{esc(player_name(player))}</span>'
            f'<span class="rd-meta">{esc(meta)}</span>'
            "</span></a>"
        )
    others = len(roster) - len(picks)
    if others > 0:
        foot = (f'{others} other player{"" if others == 1 else "s"} on the roster arrived by trade '
                "or free agency.")
    else:
        foot = f"Every player on the roster came from the {seasons[0]} redraft." if seasons else ""
    foot_html = f'<p class="muted small-copy">{esc(foot)}</p>' if foot else ""
    return f"""
    <section class="card">
      <div class="section-title-row"><h2>{esc(title)}</h2><span class="muted small-copy">{len(picks)} pick{"" if len(picks) == 1 else "s"} still on the roster · board order</span></div>
      <div class="redraft-board">{''.join(tiles)}</div>
      {foot_html}
    </section>"""


def hero_cap_chip(tfin: dict[str, Any] | None, cap: float, season: int, enforced: bool = True) -> str:
    """Hero chip: payroll against the league-average target. With no cap the only money number
    that constrains a roster is the room left under the line, so that is what
    every team subpage carries in the hero instead of a revenue projection.

    ``enforced`` is False when gameAttributes reports salaryCapType "none": the
    line is then a benchmark rather than a ceiling and the tooltip has to say
    so. The visible labels stay the ones the league-wide finances table uses for
    the same number, so the two pages read as one league.
    """
    if not tfin or not cap:
        return ""
    payroll = tfin["payroll"]
    room = cap - payroll
    label = "Cap space" if room >= 0 else "Over the cap by"
    # Exactly on the line is not good news, so $0 stays the plain text colour
    # (Queens open 2004 at $100M on the nose and read "Cap space $0" in green).
    cls = "delta-up" if room > 0 else "delta-down" if room < 0 else ""
    cls_attr = f' class="{cls}"' if cls else ""
    room_tip = (
        f"Room under the {fmt_money(cap)} cap. A team at the cap can only add players at the league minimum."
        if enforced else
        f"Payroll against the {fmt_money(cap)} league-average line. There is no salary cap — this is the "
        "benchmark the salary curve is built around, not a limit on what a team may sign."
    )
    return f"""
    <div class="hero-finance">
      <div class="hero-fin-row" title="{season} player salaries plus dead money and retained salary."><span>{season} payroll</span><strong>{_money(payroll)}</strong></div>
      <div class="hero-fin-row" title="{esc(room_tip)}"><span>{label}</span><strong{cls_attr}>{_money(abs(room))}</strong></div>
    </div>"""


# ---------------------------------------------------------------------------
# Championship banners (pennants in the hero rafters)
# ---------------------------------------------------------------------------


def _star_points(cx: float, cy: float, r_outer: float, r_inner: float) -> str:
    """Points attribute for a small upright 5-point star (banner decoration)."""
    coords = []
    for i in range(10):
        r = r_outer if i % 2 == 0 else r_inner
        ang = math.pi / 5.0 * i - math.pi / 2.0
        coords.append("%.2f,%.2f" % (cx + r * math.cos(ang), cy + r * math.sin(ang)))
    return " ".join(coords)


def _playoff_games_to_win(data: dict[str, Any], season: int) -> int:
    """Wins that clinch a season's Finals, from the retained playoff game rows;
    falls back to gameAttributes.numGamesPlayoffSeries when that season's games
    are gone. SMP II's Finals is best-of-5, so the fallback must be derived — a
    hardcoded 4 would refuse to crown a champion who won it 3-x."""
    for game in data.get("games") or []:
        if (safe_int(game.get("season"), -1) == season and game.get("playoffs")
                and safe_int(game.get("numGamesToWinSeries")) > 0):
            return safe_int(game.get("numGamesToWinSeries"))
    series = get_attr_value((data.get("gameAttributes") or {}).get("numGamesPlayoffSeries"), season)
    if isinstance(series, list) and series:
        return max(1, safe_int(series[-1], 7) // 2 + 1)
    return 4


def champions_by_season(data: dict[str, Any]) -> dict[int, dict[str, Any]]:
    """{season: {"champ": tid, "runner_up": tid, "rounds": n}} from playoffSeries.

    Past seasons read straight off the decided final; the current season only
    counts once the Finals series is actually clinched (playoffSeries grows one
    round at a time, so a mid-playoff export must not mint a champion early).
    """
    cur = current_season(data)
    out: dict[int, dict[str, Any]] = {}
    for ps in data.get("playoffSeries") or []:
        if not isinstance(ps, dict):
            continue
        season = safe_int(ps.get("season"), -1)
        rounds = [rnd for rnd in (ps.get("series") or []) if rnd]
        if season < 0 or not rounds:
            continue
        first = [m for m in rounds[0] if isinstance(m, dict)]
        expected = (int(round(math.log2(len(first)))) + 1) if first else len(rounds)
        if len(rounds) < expected:
            continue
        finals = [m for m in rounds[expected - 1] if isinstance(m, dict)]
        if len(finals) != 1:
            continue
        home = finals[0].get("home") or {}
        away = finals[0].get("away") or {}
        hw, aw = safe_int(home.get("won")), safe_int(away.get("won"))
        if hw == aw:
            continue
        if season >= cur and max(hw, aw) < _playoff_games_to_win(data, season):
            continue  # Finals in progress: no champion yet
        champ, runner = (home, away) if hw > aw else (away, home)
        out[season] = {
            "champ": safe_int(champ.get("tid"), -1),
            "runner_up": safe_int(runner.get("tid"), -1),
            "rounds": expected,
        }
    return out


def team_banner_history(data: dict[str, Any], tid: int) -> list[dict[str, Any]]:
    """Chronological banner entries for a team: {"season", "kind"} with kind
    "title" (championship) or "finals" (Finals appearance, lost)."""
    out = []
    for season, info in sorted(champions_by_season(data).items()):
        if info["champ"] == tid:
            out.append({"season": season, "kind": "title"})
        elif info["runner_up"] == tid:
            out.append({"season": season, "kind": "finals"})
    return out


_BANNER_FONT = "font-family=\"'Helvetica Neue',Helvetica,Arial,sans-serif\""


def banner_svg(season: Any, kind: str = "title", tid: Any = None) -> str:
    """One rafter pennant, sized to hang in the hero like a real arena banner.
    kind="title" is the full championship banner (team primary fill, secondary
    trim, star, CHAMPS caption); kind="finals" is slimmer and muted for a
    Finals appearance. Colors resolve from the --team-* css vars — pass ``tid``
    to bake them onto the svg so it renders standalone (reusable: the
    history-page "Rafters" strip can call this directly with a tid).
    """
    year = esc(season)
    vars_attr = f' style="{team_css_vars(tid)}"' if tid is not None else ""
    if kind == "title":
        return (
            f'<svg class="banner banner--title" viewBox="0 0 60 84" role="img" '
            f'aria-label="{year} League Champions"{vars_attr} '
            'xmlns="http://www.w3.org/2000/svg">'
            '<title>' + year + ' League Champions</title>'
            '<polygon points="2,2 58,2 58,62 30,82 2,62" fill="var(--team-primary)" '
            'stroke="var(--team-secondary)" stroke-width="2.4" stroke-linejoin="round"/>'
            '<line x1="7" y1="8.5" x2="53" y2="8.5" stroke="var(--team-secondary)" '
            'stroke-width="2" opacity=".85"/>'
            f'<text x="30" y="27.5" text-anchor="middle" {_BANNER_FONT} '
            'font-weight="700" font-size="15" letter-spacing=".5" '
            'fill="var(--team-on-primary)">' + year + "</text>"
            f'<polygon points="{_star_points(30, 41.5, 7.6, 3.0)}" fill="var(--team-secondary)"/>'
            f'<text x="30" y="60" text-anchor="middle" {_BANNER_FONT} '
            'font-weight="700" font-size="7.2" letter-spacing="1.6" '
            'fill="var(--team-on-primary)" opacity=".85">CHAMPS</text>'
            "</svg>"
        )
    return (
        f'<svg class="banner banner--finals" viewBox="0 0 46 68" role="img" '
        f'aria-label="{year} Finals appearance"{vars_attr} '
        'xmlns="http://www.w3.org/2000/svg">'
        '<title>' + year + " Finals</title>"
        '<polygon points="2,2 44,2 44,48 23,66 2,48" class="banner-finals-body" '
        'stroke-width="1.8" stroke-linejoin="round"/>'
        '<rect x="2" y="2" width="42" height="5" fill="var(--team-secondary)" opacity=".55"/>'
        f'<text x="23" y="24.5" text-anchor="middle" {_BANNER_FONT} '
        'font-weight="700" font-size="12" class="banner-finals-year">' + year + "</text>"
        f'<text x="23" y="38.5" text-anchor="middle" {_BANNER_FONT} '
        'font-weight="700" font-size="6.6" letter-spacing="1.3" class="banner-finals-cap">FINALS</text>'
        "</svg>"
    )


def team_rafters_html(data: dict[str, Any] | None, team: dict[str, Any]) -> str:
    """The hero rafters strip: one pennant per championship / Finals run.
    Teams with no banners get nothing at all."""
    if not data:
        return ""
    tid = safe_int(team.get("tid"), -1)
    entries = team_banner_history(data, tid)
    if not entries:
        return ""
    pennants = "".join(banner_svg(e["season"], e["kind"]) for e in entries)
    n_titles = sum(1 for e in entries if e["kind"] == "title")
    label = f'{n_titles} championship{"" if n_titles == 1 else "s"}' if n_titles else "Finals appearances"
    return f'<div class="tm-rafters" role="group" aria-label="{esc(label)}">{pennants}</div>'


def team_subnav(team: dict[str, Any], active_sub: str) -> str:
    slug = team_slug(team)
    items = [
        ("roster", "Roster", f"{slug}.html"),
        ("games", "Games", f"{slug}-games.html"),
        ("finances", "Finances", f"{slug}-finances.html"),
        ("history", "History", f"{slug}-history.html"),
    ]
    links = []
    for key, label, href in items:
        active = " active" if key == active_sub else ""
        cur = ' aria-current="page"' if key == active_sub else ""
        links.append(f'<a class="subnav-link{active}" href="{href}"{cur}>{esc(label)}</a>')
    return f'<nav class="team-subnav" aria-label="Team sections">{"".join(links)}</nav>'


def team_hero_html(team: dict[str, Any], season: int, sorted_roster: list[dict[str, Any]], teams: list[dict[str, Any]], tfin: dict[str, Any] | None, data: dict[str, Any] | None = None) -> str:
    ts = latest_team_season(team, season)
    record = fmt_record(ts.get("won"), ts.get("lost"))
    streak = streak_text(ts.get("streak"))
    abbrev = str(team.get("abbrev") or team_identity(safe_int(team.get("tid"), -1))["abbrev"])
    bits = [esc(abbrev)]
    if record != "—":
        bits.append(record)
    if streak != "—":
        bits.append(streak)
    bits.append(f"{len(sorted_roster)} players")
    rules = _cap_rules(data, season)
    return f"""
    <section class="page-hero team-hero">
      <span class="tm-watermark" aria-hidden="true">{esc(abbrev)}</span>
      {team_rafters_html(data, team)}
      <div class="tm-hero-copy">
        <p class="eyebrow">Team</p>
        <h1>{esc(team_full_name(team))}</h1>
        <p class="muted">{' · '.join(bits)}</p>
      </div>
      {hero_cap_chip(tfin, rules["cap"], season, enforced=rules["enforced"])}
    </section>"""


def finance_ledger_card(tfin: dict[str, Any] | None, year: int, cap: float | None = None) -> str:
    """Revenue ledger: win payouts + playoff bonuses + adjustments = net revenue.

    This ledger is a scoreboard, not a spending account. A per-win revenue model has a
    ~2x spread between the best and worst team, so what a team banks and what it can
    responsibly commit are different numbers; reporting net revenue as a "budget
    surplus" contradicted the payroll figures on the same page (measured: 10 of 10
    teams disagreed, average gap ~$11M). So the last tile reports what the team can
    ACTUALLY spend -- next season's revenue less the salaries already committed.

    No luxury-tax line: Basketball GM assesses no tax when salaryCapType is anything
    other than "soft", so a tax row and a tax-distribution row could only ever read $0."""
    if not tfin:
        return ""
    f = tfin

    def row(label: str, now: str, proj: str, cls: str = "") -> str:
        cls_attr = f' class="{cls}"' if cls else ""
        return f'<tr{cls_attr}><td class="ledger-label">{label}</td><td class="ledger-num">{now}</td><td class="ledger-num">{proj}</td></tr>'

    budget_now = f'<strong>{_money(f["net_revenue_now"])}</strong>'
    budget_proj = f'<strong>{_money(f["net_revenue_proj"])}</strong>'
    rows = [
        row(f'Win payouts <span class="muted small-copy">({_fin_mil(FIN_PER_WIN)} × W)</span>',
            f'{fmt_money_pm(f["win_rev_now"])} <span class="muted small-copy">({f["won"]} W)</span>',
            f'{fmt_money_pm(f["win_rev_proj"])} <span class="muted small-copy">(proj {fmt_number(f["proj_w"], 1)} W)</span>'),
        row('Postseason <span class="muted small-copy">(berth · per win · finals · title)</span>', fmt_money_pm(f["earned_playoff"]), fmt_money_pm(f["proj_playoff"])),
    ]
    if abs(f.get("adj", 0)) > 1e-9:
        adj_cls = "delta-up" if f["adj"] > 0 else "delta-down"
        adj_label = "Trade cash"
        if f.get("adj_note"):
            adj_label += f' <span class="muted small-copy">({esc(f["adj_note"])})</span>'
        adj_cell = f'<span class="{adj_cls}">{fmt_money_pm(f["adj"])}</span>'
        rows.append(row(adj_label, adj_cell, adj_cell))
    rows.append(row(f"{year} net revenue <span class=\"muted small-copy\">(earned, not spendable)</span>", budget_now, budget_proj, cls="ledger-total"))

    bal = f["season_balance_proj"]
    surplus = f["surplus_next"]
    bc = "delta-up" if bal >= 0 else "delta-down"

    # With no cap, the only limit on what a team can add is what it earned.
    committed = f["committed_next"]
    spendable = surplus
    tip = (f"{year} net revenue minus committed {year} payroll. There is no cap, so "
           f"revenue is the only limit on what you can add.")

    tiles = "".join([
        _tile(f"{year - 1} payroll", _money(f["payroll"]),
              tip="This season's player salaries plus dead money and retained salary."),
        _tile("Season balance", fmt_money_pm(bal), cls=bc,
              tip="Projected net revenue minus this season's payroll. League average is about $0 by design."),
        _tile(f"Committed {year} payroll", _money(committed),
              tip=f"Salaries already on the books for {year}, incl. dead money and retained salary."),
        _tile(f"Spendable in {year}", fmt_money_pm(spendable),
              cls="delta-up" if spendable >= 0 else "delta-down", tip=tip),
    ])
    return f"""
    <section class="card">
      <div class="section-title-row"><h2>Revenue &amp; Budget</h2><span class="muted small-copy">projected = 10k-sim wins + playoff EV</span></div>
      <div class="table-wrap">
        <table class="ledger-table">
          <thead><tr><th>Item</th><th>Now</th><th>Projected</th></tr></thead>
          <tbody>{"".join(rows)}</tbody>
        </table>
      </div>
      <div class="vitals-row">{tiles}</div>
    </section>"""


def cap_sheet_card(tfin: dict[str, Any] | None, data: dict[str, Any] | None, season: int, roster_size: int, league_fin: dict[str, Any]) -> str:
    """Cap sheet: payroll against the cap line, room left, and roster spots filled.

    This is what the old Luxury Tax card became. SMP II has no cap and no tax, so the
    live questions are simply what the team is spending and how that compares with the
    league-average target the salary curve is calibrated against — and the prose has
    to branch on ``_cap_rules(...)["enforced"]`` so it never states a rule the export
    does not carry."""
    if not tfin:
        return ""
    rules = _cap_rules(data, season)
    cap = rules["cap"]
    if not cap:
        return ""
    payroll = tfin["payroll"]
    room = cap - payroll
    enforced = rules["enforced"]
    max_roster = safe_int(get_attr_value((data or {}).get("gameAttributes", {}).get("maxRosterSize"), season))
    tiles = [_tile("Payroll", _money(payroll),
                   tip="Full-season player salaries plus dead money and retained salary.")]
    line = "cap" if enforced else "league-average line"
    if room >= 0:
        # Green means "there is room". A team sitting exactly on the line has
        # none, so $0 is reported in the plain text colour rather than as good news.
        tiles.append(_tile("Cap space", _money(room), cls="delta-up" if room > 0 else "",
                           tip=f"Room below the {fmt_money(cap)} {line}."))
    else:
        over_tip = (f"Payroll above the {fmt_money(cap)} cap — this roster is not legal."
                    if enforced else
                    f"Payroll above the {fmt_money(cap)} league-average line. Legal — there is no cap — "
                    "but the overspend has to be covered by what the team earns.")
        tiles.append(_tile("Over the cap by", _money(-room), cls="delta-down", tip=over_tip))
    if max_roster:
        tiles.append(_tile("Roster", f"{roster_size} / {max_roster}",
                           tip=f"Rosters are locked at {max_roster} players."))
    cap_type = {"hard": "hard cap", "soft": "soft cap"}.get(rules["type"], "league average")
    # The card subtitle used cap_type too, so an uncapped league got "league
    # average $100M" in the header and "the 10 teams are actually paying $96.9M
    # on average" in the body — the same contradiction, one line apart. $100M is
    # the target the salary curve is calibrated to, not the observed average.
    subtitle = f"{cap_type} {fmt_money(cap)}" if enforced else f"league-average target {fmt_money(cap)}"
    # Every claim below is branched on whether the export actually enforces a
    # cap. It used to print hard-cap rules unconditionally ("this roster is not
    # legal", "every signing has to land under $100M") on a league whose
    # salaryCapType is "none" — directly contradicting the How Finances Work
    # card two cards further down the same page.
    if not enforced:
        note = (f"There is no salary cap and no luxury tax: {fmt_money(cap)} is the league-average "
                "payroll target the salary curve is built around, and revenue is the only real limit "
                "on what a team can add.")
    elif room < 0:
        note = f"Payroll is over the {cap_type} — this roster cannot be submitted as-is."
    elif rules["minimum"] and room < rules["minimum"]:
        note = f"Capped out: with less than the {fmt_money(rules['minimum'])} minimum in space, this team cannot add a player at all."
    else:
        note = f"No Bird rights and no exceptions — every signing, re-signing and trade has to land under {fmt_money(cap)}."
    payrolls = [t["payroll"] for t in (league_fin.get("teams") or {}).values()]
    if payrolls:
        # "League average payroll is $96.9M" landing straight after "$100M is the
        # league-average target" read as a contradiction. One is the calibration
        # line, the other is what the ten teams are actually paying — say so.
        actual = fmt_money(sum(payrolls) / len(payrolls))
        note += (f" The {len(payrolls)} teams are actually paying {actual} on average."
                 if not enforced else f" League average payroll is {actual}.")
    return f"""
    <section class="card">
      <div class="section-title-row"><h2>Cap Sheet</h2><span class="muted small-copy">{esc(subtitle)}</span></div>
      <div class="vitals-row">{"".join(tiles)}</div>
      <p class="muted small-copy">{note}</p>
    </section>"""


def finance_rules_card(data: dict[str, Any] | None = None, season: int | None = None) -> str:
    stacked = FIN_PLAYOFF + 6 * FIN_PLAYOFF_WIN + FIN_FINALS + FIN_CHAMP

    # League wins/season = numGames * numTeams / 2 -- derived, not hardcoded, because
    # SMP I ran 45 games (225 wins) and SMP II runs 36 (180). Falls back to SMP II's
    # shape if the export can't be read.
    n_teams = len(active_team_ids(data.get("teams") or [])) if data else 10
    games = regular_season_length(data, season) if (data and season is not None) else 36
    league_wins = (games * n_teams) // 2 if games and n_teams else 180
    # Average budget: the league's wins are shared out, so an average team wins
    # league_wins / n_teams. Postseason money is a fixed pool spread over the field.
    avg_wins = league_wins / (n_teams or 10)
    post_pool = 4 * FIN_PLAYOFF + 12 * FIN_PLAYOFF_WIN + 2 * FIN_FINALS + FIN_CHAMP
    avg_budget = FIN_BASE + FIN_PER_WIN * avg_wins + post_pool / (n_teams or 10)
    # Cap copy comes off gameAttributes, not a FIN_* constant, so the rules card
    # cannot state a cap the league does not actually enforce.
    rules = _cap_rules(data, season if season is not None else 0)
    cap = rules["cap"]
    cap_label = f'{fmt_money(cap)} {"hard" if rules["hard"] else "soft"} cap' if cap else "Hard cap"
    min_line = (f'Minimum contract is <strong>{fmt_money(rules["minimum"])}</strong>'
                if rules["minimum"] else "Every roster spot still costs the league minimum")
    budget_note = (f"League-average budget is {_fin_mil(avg_budget)} — the number the "
                   f"salary curve is calibrated against, so an average team roughly breaks even.")
    return f"""
    <section class="card">
      <div class="section-title-row"><h2>How Finances Work</h2></div>
      <div class="fin-rules">
        <div>
          <h3>Revenue</h3>
          <ul class="fin-list">
            <li>Every win <strong>+{_fin_mil(FIN_PER_WIN)}</strong> — all 36 weigh the same</li>
            <li>Playoff berth <strong>+{_fin_mil(FIN_PLAYOFF)}</strong> · each playoff win <strong>+{_fin_mil(FIN_PLAYOFF_WIN)}</strong></li>
            <li>Finals <strong>+{_fin_mil(FIN_FINALS)}</strong> · Title <strong>+{_fin_mil(FIN_CHAMP)}</strong></li>
          </ul>
          <p class="muted small-copy">A full title run banks +{_fin_mil(stacked)} on top of the win money. There is no appearance money — win nothing and you earn nothing.</p>
        </div>
        <div>
          <h3>Spending</h3>
          <ul class="fin-list">
            <li><strong>No salary cap and no luxury tax.</strong> What you earn is what you can spend</li>
            <li>{min_line}</li>
            <li>Net revenue is the whole next-season budget — no carried cash</li>
          </ul>
          <p class="muted small-copy">{budget_note}</p>
        </div>
      </div>
    </section>"""


def _age_sort(player: dict[str, Any], season: int) -> int | None:
    yr = (player.get("born") or {}).get("year")
    return (season - yr) if isinstance(yr, int) else None


def _rate_cell(value: float | None, gp: float, digits: int = 1) -> str:
    """A per-game cell that dashes out when the player has not played.

    ``per_game`` returns 0.0 at 0 GP, so the naive cell prints "0.0" for an
    average nobody has recorded — in preseason that is the entire Stats table,
    twelve rows of numbers a visitor reads as real. BPM, TS% and ORtg in the
    same row already print an em-dash because their inputs are missing; this
    makes the counting averages agree with them. The sort key is dropped with
    the value so the blanks group together instead of sorting as zero.
    """
    if gp <= 0 or value is None:
        return td("—")
    return td(fmt_number(value, digits), sort=value)


def roster_stats_row(player: dict[str, Any], season: int, start_season: int, root: str, teams_by_tid: dict[int, dict[str, Any]]) -> str:
    """The default roster row: identity, contract, health, per-game line, BPM.

    A local copy of core.roster_row rather than a call to it, because the
    per-game columns have to dash out at 0 GP (see _rate_cell) and every other
    caller of that helper is on this page anyway.
    """
    rating = latest_rating(player, season)
    stat = latest_regular_stat(player, start_season, season)
    gp = stat_gp(stat)
    trb = (safe_float(stat.get("orb")) + safe_float(stat.get("drb"))) / gp if gp > 0 else None
    has_bpm = stat.get("obpm") is not None or stat.get("dbpm") is not None
    bpm = (safe_float(stat.get("obpm")) + safe_float(stat.get("dbpm"))) if has_bpm else None
    last_tx = ((player.get("transactions") or [{}])[-1] or {}).get("season")
    return "".join([
        td(player_link(player, root), sort=player_name(player), cls="name-cell"),
        td(esc(rating.get("pos", "—")), sort=rating.get("pos", "")),
        td(age(player, season), sort=_age_sort(player, season)),
        td(rating_delta_html(player, "ovr", rating), sort=rating.get("ovr")),
        td(rating_delta_html(player, "pot", rating), sort=rating.get("pot")),
        td(fmt_contract(player), sort=(player.get("contract") or {}).get("amount")),
        td(injury_html(player), sort=(player.get("injury") or {}).get("gamesRemaining") or 0),
        td(fmt_number(gp, 0), sort=gp),
        _rate_cell(per_game(stat, "min"), gp),
        _rate_cell(per_game(stat, "pts"), gp),
        _rate_cell(trb, gp),
        _rate_cell(per_game(stat, "ast"), gp),
        _rate_cell(per_game(stat, "stl"), gp),
        _rate_cell(per_game(stat, "blk"), gp),
        td(fmt_signed(bpm, 1) if bpm is not None else "—", sort=bpm),
        td(acquisition_html(player, teams_by_tid or {}), sort=last_tx),
    ])


def roster_advanced_row(player: dict[str, Any], season: int, start_season: int, root: str) -> str:
    rating = latest_rating(player, season)
    stat = latest_regular_stat(player, start_season, season)
    gp = stat_gp(stat)
    fga, fta = safe_float(stat.get("fga")), safe_float(stat.get("fta"))
    fg, tp, pts = safe_float(stat.get("fg")), safe_float(stat.get("tp")), safe_float(stat.get("pts"))
    ts = (pts / (2.0 * (fga + 0.44 * fta))) if (fga + 0.44 * fta) > 0 else None
    efg = ((fg + 0.5 * tp) / fga) if fga > 0 else None
    has_bpm = stat.get("obpm") is not None or stat.get("dbpm") is not None
    bpm = (safe_float(stat.get("obpm")) + safe_float(stat.get("dbpm"))) if has_bpm else None
    return "".join([
        td(player_link(player, root), sort=player_name(player), cls="name-cell"),
        td(esc(rating.get("pos", "—")), sort=rating.get("pos", "")),
        td(age(player, season), sort=_age_sort(player, season)),
        td(fmt_number(gp, 0), sort=gp),
        _rate_cell(per_game(stat, "min"), gp),
        td(fmt_number(ts * 100, 1) if ts is not None else "—", sort=ts),
        td(fmt_number(efg * 100, 1) if efg is not None else "—", sort=efg),
        td(fmt_number(stat.get("ortg"), 1), sort=stat.get("ortg")),
        td(fmt_number(stat.get("drtg"), 1), sort=stat.get("drtg")),
        td(fmt_signed(stat.get("obpm"), 1) if stat.get("obpm") is not None else "—", sort=stat.get("obpm")),
        td(fmt_signed(stat.get("dbpm"), 1) if stat.get("dbpm") is not None else "—", sort=stat.get("dbpm")),
        td(fmt_signed(bpm, 1) if bpm is not None else "—", sort=bpm),
        td(fmt_number(stat.get("vorp"), 1), sort=stat.get("vorp")),
        td(fmt_signed(stat.get("pm"), 0) if stat.get("pm") is not None else "—", sort=stat.get("pm")),
    ])


def roster_ratings_row(player: dict[str, Any], season: int, root: str, rating_ranges: dict[str, tuple[float, float]]) -> str:
    rating = latest_rating(player, season)
    cells = [
        td(player_link(player, root), sort=player_name(player), cls="name-cell"),
        td(esc(rating.get("pos", "—")), sort=rating.get("pos", "")),
        td(age(player, season), sort=_age_sort(player, season)),
        td(rating_delta_html(player, "ovr", rating), sort=rating.get("ovr")),
        td(rating_delta_html(player, "pot", rating), sort=rating.get("pot")),
    ]
    for key, _ in TEAM_RATING_RANK_KEYS:
        value = rating.get(key)
        lo, hi = rating_ranges.get(key, (0.0, 0.0))
        cls = "group-start" if key in RATING_GROUP_STARTS else ""
        cells.append(td(esc(value if value is not None else "—"), sort=value, cls=cls, style=heat_style(value, lo, hi, 1)))
    return "".join(cells)


def roster_tabs(sorted_roster: list[dict[str, Any]], season: int, start_season: int, root: str, teams_by_tid: dict[int, dict[str, Any]], game_logs: dict[int, list[dict[str, Any]]] | None) -> str:
    """One sortable spreadsheet of the whole roster, toggled between three column sets."""
    ranges: dict[str, tuple[float, float]] = {}
    for key, _ in TEAM_RATING_RANK_KEYS:
        vals = [float(latest_rating(p, season)[key]) for p in sorted_roster
                if isinstance(latest_rating(p, season).get(key), (int, float))]
        ranges[key] = (min(vals), max(vals)) if vals else (0.0, 0.0)

    stats_headers = ["Name", "Pos", "Age", "Ovr", "Pot", "Contract", "Health", "G", "MP", "PTS", "TRB", "AST", "STL", "BLK", "BPM", "Acquired"]
    adv_headers = ["Name", "Pos", "Age", "G", "MP", "TS%", "eFG%", "ORtg", "DRtg", "OBPM", "DBPM", "BPM", "VORP", "+/-"]

    # 0-GP players have no real stat line — their all-zero rows are dimmed and
    # can be hidden by unchecking the "show inactive" toggle (shown by default:
    # the full roster is the honest view). The Ratings view always shows the
    # full roster (ratings are real for everyone).
    never_played = {safe_int(p.get("pid"), -1) for p in sorted_roster
                    if stat_gp(latest_regular_stat(p, start_season, season)) <= 0}
    # Nobody on the roster has played: dimming or hiding the whole squad would
    # lie harder than showing it, and Stats/Advanced have nothing in them, so
    # Ratings opens instead. Both decisions read off the roster's own game logs,
    # so the page reverts on its own the day the first box score lands.
    all_idle = len(never_played) == len(sorted_roster) and bool(sorted_roster)
    zero_gp = set() if all_idle else never_played

    def stat_tr(p: dict[str, Any], cells: str) -> str:
        cls = ' class="inactive-row"' if safe_int(p.get("pid"), -1) in zero_gp else ""
        return f"<tr{cls}>{cells}</tr>"

    stats_rows = [stat_tr(p, roster_stats_row(p, season, start_season, root, teams_by_tid)) for p in sorted_roster]
    adv_rows = [stat_tr(p, roster_advanced_row(p, season, start_season, root)) for p in sorted_roster]
    rat_headers: list = ["Name", "Pos", "Age", "Ovr", "Pot"]
    for key, label in TEAM_RATING_RANK_KEYS:
        rat_headers.append((label, "group-start" if key in RATING_GROUP_STARTS else ""))
    rat_rows = [roster_ratings_row(p, season, root, ranges) for p in sorted_roster]

    open_tab = "rrat" if all_idle else "rstats"

    def tab(tid: str, label: str) -> str:
        on = tid == open_tab
        return (f'<button type="button" class="{"active" if on else ""}" role="tab" id="tab-{tid}" '
                f'aria-controls="panel-{tid}" aria-selected="{"true" if on else "false"}" '
                f'tabindex="{"0" if on else "-1"}" data-tab-target="panel-{tid}">{esc(label)}</button>')

    def panel(tid: str, body: str) -> str:
        hide = "" if tid == open_tab else " hidden"
        return (f'<div id="panel-{tid}" role="tabpanel" aria-labelledby="tab-{tid}" '
                f"data-tab-panel{hide}>{body}</div>")

    note = ""
    if all_idle:
        # "Stats and Advanced stay empty" overstated it: those views still carry
        # position, age, ovr/pot, contract, health and how the player was
        # acquired. What is blank is every column fed by a box score.
        note = ('<p class="muted small-copy">No games played yet — every per-game and advanced '
                'column stays blank until the first box score. Ratings, contracts and health '
                'are current.</p>')
    elif zero_gp:
        n = len(zero_gp)
        note = (
            '<label class="inactive-toggle small-copy">'
            '<input type="checkbox" data-toggle-inactive checked> '
            f'Show inactive — {n} player{"" if n == 1 else "s"} with 0 GP</label>'
        )
    return f"""
    <section class="card" data-roster-card>
      <div class="section-title-row"><h2>Players</h2><span class="muted small-copy">{len(sorted_roster)} players · sortable</span></div>
      <div class="tabs" role="tablist" aria-label="Roster stat views" data-tabs>
        {tab("rstats", "Stats")}{tab("radv", "Advanced")}{tab("rrat", "Ratings")}
      </div>
      {note}
      {panel("rstats", table_html(stats_headers, stats_rows, table_id="roster-stats", empty_message="No players found.", wrap_cls="fit-table", pos_filter=True))}
      {panel("radv", table_html(adv_headers, adv_rows, table_id="roster-advanced", empty_message="No players found.", wrap_cls="fit-table", pos_filter=True))}
      {panel("rrat", table_html(rat_headers, rat_rows, table_id="roster-ratings", empty_message="No players found.", wrap_cls="fit-table", pos_filter=True))}
    </section>"""


def _sorted_team_roster(roster: list[dict[str, Any]], season: int) -> list[dict[str, Any]]:
    return sorted(roster, key=lambda p: (-latest_rating(p, season).get("ovr", 0), player_name(p)))


def _depth_order(roster: list[dict[str, Any]], season: int) -> list[dict[str, Any]]:
    """Roster in depth order: the league's own rosterOrder, best available second.

    The roster TABLE is a leaderboard and sorts by overall; the depth chart is a
    statement about who plays, and that is the manager's call. When a man goes
    down the league moves him to the bottom of the roster and activates someone
    in his place, so an injured 72 sits at slot 11 while a healthy 61 dresses.
    Sorting the chart by overall would put the injured star back in the starting
    five and contradict the projected box scores, which dress the same ten the
    manager did. Overall descending is the fallback for an export with no
    rosterOrder — which is every export before the season starts.
    """
    if all(isinstance(p.get("rosterOrder"), int) for p in roster):
        return sorted(roster, key=lambda p: p["rosterOrder"])
    return _sorted_team_roster(roster, season)


def render_team_roster_page(team: dict[str, Any], roster: list[dict[str, Any]], teams: list[dict[str, Any]], season: int, start_season: int, data: dict[str, Any] | None = None, game_items: list[dict[str, Any]] | None = None, game_logs: dict[int, list[dict[str, Any]]] | None = None, tfin: dict[str, Any] | None = None) -> str:
    teams_by_tid = {int(t.get("tid")): t for t in teams if t.get("tid") is not None}
    sorted_roster = _sorted_team_roster(roster, season)
    rotation = ""
    if game_items and game_logs is not None:
        # Before any current-season game is completed the page-level items are
        # all upcoming — fall back to the retained completed games in the export.
        items = game_items
        window, display_season = _team_completed_window(team, items, season)
        if not window and data is not None:
            items = completed_game_items(data, None, playoffs=False)
            window, display_season = _team_completed_window(team, items, season)
        # The fallback window's season needs matching logs — rebuild when it
        # differs from the current season.
        logs = game_logs
        if window and display_season != season and data is not None:
            logs = build_game_logs(data, display_season)
        if window:
            rotation = rotation_map_card(team, sorted_roster, items, logs, season, teams_by_tid)
    picks = draft_picks_card(data, team, teams_by_tid) if data else ""
    body = f"""
    {team_hero_html(team, season, sorted_roster, teams, tfin, data=data)}
    {team_subnav(team, "roster")}
    {roster_tabs(sorted_roster, season, start_season, "../", teams_by_tid, game_logs)}
    {depth_chart_card(sorted_roster, season, start_season)}
    {rotation}
    {scoring_share_card(team, sorted_roster, season)}
    {picks}
    """
    return page_html(team_full_name(team), team_scope_html(team, body), teams, root="../", active=f"team-{team.get('tid')}")


def render_team_games_page(team: dict[str, Any], roster: list[dict[str, Any]], teams: list[dict[str, Any]], season: int, start_season: int, data: dict[str, Any] | None = None, game_items: list[dict[str, Any]] | None = None, game_logs: dict[int, list[dict[str, Any]]] | None = None, tfin: dict[str, Any] | None = None) -> str:
    teams_by_tid = {int(t.get("tid")): t for t in teams if t.get("tid") is not None}
    sorted_roster = _sorted_team_roster(roster, season)
    strip = team_games_strip(team, game_items or [], teams_by_tid, season=season) if game_items else ""
    games_table = team_games_table(team, game_items or [], teams_by_tid, season) if game_items else ""
    playoff_items = completed_game_items(data, None, playoffs=True) if data else []
    playoffs_table = team_playoffs_table(team, playoff_items, teams_by_tid, season) if playoff_items else ""
    profile = team_quarter_profile(team, data, season, teams_by_tid) if data else ""
    factors = four_factors_card(data, team, teams, season) if data else ""
    sections = [strip, games_table, playoffs_table, factors, profile]
    if not any(s.strip() for s in sections):
        # Every section correctly renders "" before the first tip-off, which left
        # the subnav pointing at a literally blank page in year one.
        games = regular_season_length(data, season) if data else 0
        length = f"{games}-game " if games else ""
        sections = [f"""
    <section class="card">
      <div class="section-title-row"><h2>Games</h2></div>
      <p class="muted">No games played yet — the {length}{season} season has not started.</p>
    </section>"""]
    body = f"""
    {team_hero_html(team, season, sorted_roster, teams, tfin, data=data)}
    {team_subnav(team, "games")}
    {''.join(sections)}
    """
    return page_html(f"{team_full_name(team)} — Games", team_scope_html(team, body), teams, root="../", active=f"team-{team.get('tid')}")


def render_team_finances_page(team: dict[str, Any], roster: list[dict[str, Any]], teams: list[dict[str, Any]], season: int, start_season: int, data: dict[str, Any] | None = None, tfin: dict[str, Any] | None = None, league_fin: dict[str, Any] | None = None) -> str:
    sorted_roster = _sorted_team_roster(roster, season)
    body = f"""
    {team_hero_html(team, season, sorted_roster, teams, tfin, data=data)}
    {team_subnav(team, "finances")}
    {cap_sheet_card(tfin, data, season, len(sorted_roster), league_fin or {})}
    {finance_ledger_card(tfin, season + 1, _cap_rules(data, season)['cap'])}
    {team_finances_table(sorted_roster, season, data=data, tid=safe_int(team.get("tid")))}
    {finance_rules_card(data, season)}
    """
    return page_html(f"{team_full_name(team)} — Finances", team_scope_html(team, body), teams, root="../", active=f"team-{team.get('tid')}")


def render_team_history_page(team: dict[str, Any], roster: list[dict[str, Any]], teams: list[dict[str, Any]], season: int, start_season: int, data: dict[str, Any] | None = None, tfin: dict[str, Any] | None = None) -> str:
    """The 4th team subpage: the Franchise Arc — W/L ribbon, playoff exits,
    title flags, event pins, and the season-by-season results table."""
    teams_by_tid = {int(t.get("tid")): t for t in teams if t.get("tid") is not None}
    sorted_roster = _sorted_team_roster(roster, season)
    arc = franchise_arc_card(team, data, teams, teams_by_tid, roster=sorted_roster) if data else ""
    results = season_results_card(team, data, teams) if data else ""
    board = redraft_board_card(sorted_roster, season)
    body = f"""
    {team_hero_html(team, season, sorted_roster, teams, tfin, data=data)}
    {team_subnav(team, "history")}
    {arc}
    {results}
    {board}
    """
    return page_html(f"{team_full_name(team)} — Franchise Arc", team_scope_html(team, body), teams, root="../", active=f"team-{team.get('tid')}")
