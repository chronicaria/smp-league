from __future__ import annotations

"""Rivalries + Greatest Games pages.

    render_extras_pages(data, teams) -> {output_filename: html}
        rivalries.html                     10x10 all-time head-to-head grid
        rivalries/{slugA}-vs-{slugB}.html  one page per team pair (45 pages)
        classics.html                      drama-ranked greatest games

Head-to-head records come from the export's ``headToHeads`` rows (every season
since the league began, regular season + playoffs). Game-level detail (streaks,
blowouts, meeting logs, classics) comes from ``games``, which the export only
retains for recent seasons — every page says so honestly.
"""

from collections import defaultdict
from typing import Any

from ..core import (
    compose_event_html,
    completed_game_items,
    current_season,
    esc,
    fmt_number,
    fmt_signed,
    game_url,
    game_winner_tid,
    heat_style,
    latest_game_season,
    page_html,
    safe_float,
    safe_int,
    score_items_for_page,
    table_html,
    td,
    team_abbrev,
    team_abbrev_for_tid,
    team_full_for_tid,
    team_full_name,
    team_slug,
    team_sort_key,
    team_url,
    th,
)
from ..derived import comeback_size, drama_index, feats_index
from ..identity import team_css_vars

ROUND_NAMES = {
    1: ["Finals"],
    2: ["Semifinals", "Finals"],
    3: ["Quarterfinals", "Semifinals", "Finals"],
}

CLASSICS_FEATURED = 10


# ---------------------------------------------------------------------------
# Head-to-head index (from data["headToHeads"])
# ---------------------------------------------------------------------------

def _blank_record() -> dict[str, float]:
    return {"won": 0.0, "lost": 0.0, "pts": 0.0, "oppPts": 0.0}


def _add_record(total: dict[str, float], rec: dict[str, Any], flip: bool) -> None:
    """Fold a headToHeads record into a running total, optionally mirrored."""
    won, lost = safe_float(rec.get("won")), safe_float(rec.get("lost"))
    pts, opp = safe_float(rec.get("pts")), safe_float(rec.get("oppPts"))
    if flip:
        won, lost, pts, opp = lost, won, opp, pts
    total["won"] += won
    total["lost"] += lost
    total["pts"] += pts
    total["oppPts"] += opp


def head_to_head_index(data: dict[str, Any]) -> dict[int, dict[str, dict[tuple[int, int], dict[str, float]]]]:
    """{season: {"regularSeason"|"playoffs": {(tid_a, tid_b): record}}}.

    Records are mirrored to both (a, b) orders, always from the first tid's
    perspective. The export stores each pair once (lower tid as the outer key);
    otl/otw/tied are folded into won/lost by BBGM already, so won+lost = games.
    """
    out: dict[int, dict[str, dict[tuple[int, int], dict[str, float]]]] = {}
    for row in data.get("headToHeads", []) or []:
        if not isinstance(row, dict):
            continue
        season = safe_int(row.get("season"), -1)
        if season < 0:
            continue
        by_part = out.setdefault(season, {"regularSeason": {}, "playoffs": {}})
        for part in ("regularSeason", "playoffs"):
            for a_key, opponents in (row.get(part) or {}).items():
                a = safe_int(a_key, -1)
                if a < 0 or not isinstance(opponents, dict):
                    continue
                for b_key, rec in opponents.items():
                    b = safe_int(b_key, -1)
                    if b < 0 or not isinstance(rec, dict):
                        continue
                    fwd = by_part[part].setdefault((a, b), _blank_record())
                    _add_record(fwd, rec, flip=False)
                    rev = by_part[part].setdefault((b, a), _blank_record())
                    _add_record(rev, rec, flip=True)
    return out


def all_time_record(h2h: dict[int, dict[str, dict[tuple[int, int], dict[str, float]]]],
                    tid_a: int, tid_b: int) -> dict[str, float]:
    """Aggregate regular-season + playoff record for a from A's perspective."""
    total = _blank_record()
    for by_part in h2h.values():
        for part in ("regularSeason", "playoffs"):
            rec = by_part[part].get((tid_a, tid_b))
            if rec:
                _add_record(total, rec, flip=False)
    return total


# ---------------------------------------------------------------------------
# Shared game-level helpers
# ---------------------------------------------------------------------------

def _linked_game_gids(data: dict[str, Any], teams: list[dict[str, Any]], season: int) -> set[str]:
    """gids that get a games/{gid}.html page, mirroring build.py's page list."""
    gids: set[str] = set()
    items, _ = score_items_for_page(data, teams)
    for item in items:
        if item.get("gid") is not None:
            gids.add(str(item.get("gid")))
    for item in completed_game_items(data, season, playoffs=None):
        if item.get("gid") is not None:
            gids.add(str(item.get("gid")))
    last_game_season = latest_game_season(data)
    if last_game_season is not None and last_game_season != season:
        for item in completed_game_items(data, last_game_season, playoffs=None):
            if item.get("gid") is not None:
                gids.add(str(item.get("gid")))
    return gids


def _retained_items(data: dict[str, Any]) -> list[dict[str, Any]]:
    """Every retained completed game, chronological across seasons."""
    items = completed_game_items(data)
    items.sort(key=lambda it: (safe_int(it.get("season")), 1 if it.get("playoffs") else 0,
                               safe_int(it.get("day")), str(it.get("gid"))))
    return items


def _retained_seasons_label(items: list[dict[str, Any]]) -> str:
    seasons = sorted({safe_int(it.get("season")) for it in items})
    if not seasons:
        return ""
    if len(seasons) == 1:
        return str(seasons[0])
    return f"{seasons[0]}–{seasons[-1]}"


def _team_chip(team: dict[str, Any], root: str, cls: str = "rv-chip") -> str:
    tid = safe_int(team.get("tid"))
    return (
        f'<a class="{esc(cls)}" style="{team_css_vars(tid)}" href="{team_url(team, root)}">'
        f'<span class="rv-chip-dot" aria-hidden="true"></span>{esc(team_abbrev(team))}</a>'
    )


def _pair_slug(team_a: dict[str, Any], team_b: dict[str, Any]) -> str:
    return f"{team_slug(team_a)}-vs-{team_slug(team_b)}"


def _pair_url(team_a: dict[str, Any], team_b: dict[str, Any], root: str = "") -> str:
    first, second = sorted((team_a, team_b), key=lambda t: safe_int(t.get("tid")))
    return f"{root}rivalries/{_pair_slug(first, second)}.html"


def _game_score_html(item: dict[str, Any], teams_by_tid: dict[int, dict[str, Any]],
                     linked_gids: set[str], root: str) -> str:
    """Away @ Home score line with the winner bold, linked when a page exists."""
    away = team_abbrev_for_tid(item.get("away_tid"), teams_by_tid)
    home = team_abbrev_for_tid(item.get("home_tid"), teams_by_tid)
    winner = game_winner_tid(item)
    away_html = f"{esc(away)} {fmt_number(item.get('away_pts'), 0)}"
    home_html = f"{esc(home)} {fmt_number(item.get('home_pts'), 0)}"
    if winner == item.get("away_tid"):
        away_html = f"<strong>{away_html}</strong>"
    elif winner == item.get("home_tid"):
        home_html = f"<strong>{home_html}</strong>"
    label = f'{away_html} <span class="muted">@</span> {home_html}'
    if str(item.get("gid")) in linked_gids:
        return f'<a class="rv-score-link" href="{esc(game_url(item, root))}">{label}</a>'
    return label


def _ot_label(item: dict[str, Any]) -> str:
    overtimes = safe_int((item.get("game") or {}).get("overtimes"))
    if overtimes <= 0:
        return ""
    return "OT" if overtimes == 1 else f"{overtimes}OT"


# ---------------------------------------------------------------------------
# rivalries.html — 10x10 grid
# ---------------------------------------------------------------------------

def _grid_cell_data(h2h: dict[int, dict[str, dict[tuple[int, int], dict[str, float]]]],
                    tid_a: int, tid_b: int) -> dict[str, float | None]:
    rec = all_time_record(h2h, tid_a, tid_b)
    games = rec["won"] + rec["lost"]
    return {
        "won": rec["won"],
        "lost": rec["lost"],
        "diff": (rec["pts"] - rec["oppPts"]) / games if games > 0 else None,
    }


def render_rivalry_grid_page(data: dict[str, Any], teams: list[dict[str, Any]]) -> str:
    h2h = head_to_head_index(data)
    ordered = sorted((t for t in teams if t.get("tid") is not None and not t.get("disabled")), key=team_sort_key)
    seasons = sorted(h2h)
    span = f"{seasons[0]}–{seasons[-1]}" if len(seasons) > 1 else (str(seasons[0]) if seasons else "")

    cells: dict[tuple[int, int], dict[str, float | None]] = {}
    for row_team in ordered:
        for col_team in ordered:
            a, b = safe_int(row_team.get("tid")), safe_int(col_team.get("tid"))
            if a != b:
                cells[(a, b)] = _grid_cell_data(h2h, a, b)
    diffs = [c["diff"] for c in cells.values() if c["diff"] is not None]
    max_abs = max((abs(d) for d in diffs), default=0.0)

    header_cells = [th("", "rv-corner")]
    for col_team in ordered:
        header_cells.append(
            f'<th scope="col" class="rv-col-head">{_team_chip(col_team, "")}</th>'
        )
    rows = []
    for row_team in ordered:
        a = safe_int(row_team.get("tid"))
        row_cells = [f'<th scope="row" class="rv-row-head">{_team_chip(row_team, "")}</th>']
        for col_team in ordered:
            b = safe_int(col_team.get("tid"))
            if a == b:
                row_cells.append('<td class="rv-diag" aria-hidden="true"></td>')
                continue
            cell = cells[(a, b)]
            record = f"{fmt_number(cell['won'], 0)}-{fmt_number(cell['lost'], 0)}"
            diff = cell["diff"]
            tint = heat_style(diff, -max_abs, max_abs, 1) if diff is not None else ""
            title = (
                f"{team_abbrev(row_team)} {record} vs {team_abbrev(col_team)} all-time"
                + (f" · {fmt_signed(diff, 1)} pts/game" if diff is not None else "")
            )
            row_cells.append(td(
                f'<a class="rv-cell-link" href="{_pair_url(row_team, col_team)}" title="{esc(title)}">{record}</a>',
                sort=cell["won"], cls="rv-cell", style=tint,
            ))
        rows.append(f"<tr>{''.join(row_cells)}</tr>")

    body = f"""
    <section class="page-hero">
      <div>
        <h1>Rivalries</h1>
        <p class="muted">All-time head-to-head, playoffs included · {esc(span)}</p>
      </div>
    </section>
    <section class="card">
      <div class="section-title-row"><h2>Head-to-Head Grid</h2><span class="muted small-copy">row record vs column · tint = point margin · click a cell</span></div>
      <div class="table-wrap rv-grid-wrap">
        <table class="rv-grid">
          <caption class="sr-only">All-time head-to-head records between every pair of teams</caption>
          <thead><tr>{''.join(header_cells)}</tr></thead>
          <tbody>{''.join(rows)}</tbody>
        </table>
      </div>
    </section>
    """
    return page_html("Rivalries", body, teams, root="", active="rivalries")


# ---------------------------------------------------------------------------
# rivalries/{a}-vs-{b}.html — per-pair pages
# ---------------------------------------------------------------------------

def _season_strip_html(h2h: dict[int, dict[str, dict[tuple[int, int], dict[str, float]]]],
                       tid_a: int, tid_b: int, ab_a: str, ab_b: str) -> str:
    chips = []
    for season in sorted(h2h):
        by_part = h2h[season]
        reg = by_part["regularSeason"].get((tid_a, tid_b))
        po = by_part["playoffs"].get((tid_a, tid_b))
        if not reg and not po:
            chips.append(
                f'<div class="rv-season-chip rv-season-none"><span class="rv-season-year">{esc(season)}</span>'
                '<span class="muted">—</span></div>'
            )
            continue
        won = safe_float((reg or {}).get("won")) + safe_float((po or {}).get("won"))
        lost = safe_float((reg or {}).get("lost")) + safe_float((po or {}).get("lost"))
        cls = "rv-season-won" if won > lost else ("rv-season-lost" if lost > won else "rv-season-even")
        po_note = ""
        if po:
            po_w, po_l = safe_float(po.get("won")), safe_float(po.get("lost"))
            po_result = "won" if po_w > po_l else "lost"
            po_note = (f'<span class="rv-season-po" title="{esc(ab_a)} {esc(po_result)} the playoff series '
                       f'{fmt_number(max(po_w, po_l), 0)}-{fmt_number(min(po_w, po_l), 0)}">PO</span>')
        title = f"{season}: {ab_a} {fmt_number(won, 0)}-{fmt_number(lost, 0)} vs {ab_b} (incl. playoffs)"
        chips.append(
            f'<div class="rv-season-chip {cls}" title="{esc(title)}">'
            f'<span class="rv-season-year">{esc(season)}</span>'
            f"<span>{fmt_number(won, 0)}-{fmt_number(lost, 0)}</span>{po_note}</div>"
        )
    return f'<div class="rv-season-strip">{"".join(chips)}</div>'


def _streak_text(meetings: list[dict[str, Any]], teams_by_tid: dict[int, dict[str, Any]]) -> str:
    streak_tid = None
    streak = 0
    for item in meetings:
        winner = game_winner_tid(item)
        if winner is None:
            continue
        if winner == streak_tid:
            streak += 1
        else:
            streak_tid = winner
            streak = 1
    if streak_tid is None:
        return "No completed meetings in the retained game log."
    name = team_full_for_tid(streak_tid, teams_by_tid)
    if streak == 1:
        return f"{name} won the most recent meeting."
    return f"{name} has won {streak} straight in the series."


def _playoff_meetings_html(data: dict[str, Any], tid_a: int, tid_b: int,
                           teams_by_tid: dict[int, dict[str, Any]],
                           linked_gids: set[str], root: str) -> str:
    pair = {tid_a, tid_b}
    rows = []
    for ps in data.get("playoffSeries", []) or []:
        if not isinstance(ps, dict):
            continue
        season = safe_int(ps.get("season"), -1)
        rounds = ps.get("series") or []
        names = ROUND_NAMES.get(len(rounds), [f"Round {i + 1}" for i in range(len(rounds))])
        for round_index, matchups in enumerate(rounds):
            for series in matchups or []:
                home, away = series.get("home") or {}, series.get("away") or {}
                if {safe_int(home.get("tid"), -1), safe_int(away.get("tid"), -1)} != pair:
                    continue
                home_won = safe_int(home.get("won")) > safe_int(away.get("won"))
                winner, loser = (home, away) if home_won else (away, home)
                game_links = []
                for gid in series.get("gids") or []:
                    if str(gid) in linked_gids:
                        game_links.append(
                            f'<a class="rv-series-gm" href="{root}games/{esc(gid)}.html">G{len(game_links) + 1}</a>'
                        )
                games_html = f' <span class="rv-series-games">{"".join(game_links)}</span>' if game_links else ""
                rows.append(
                    f'<li><span class="rv-po-season">{esc(season)} {esc(names[round_index])}</span>'
                    f'<span><strong>{esc(team_abbrev_for_tid(winner.get("tid"), teams_by_tid))}</strong> '
                    f'won {safe_int(winner.get("won"))}-{safe_int(loser.get("won"))} '
                    f'<span class="muted">(seeds {safe_int(home.get("seed"))} vs {safe_int(away.get("seed"))}'
                    f", {fmt_number(winner.get('pts'), 0)}-{fmt_number(loser.get('pts'), 0)} aggregate)</span>"
                    f"{games_html}</span></li>"
                )
    if not rows:
        return '<p class="empty-state">These two teams have never met in the playoffs.</p>'
    return f'<ul class="rv-po-list">{"".join(rows)}</ul>'


def _extreme_game_line(item: dict[str, Any], label: str, teams_by_tid: dict[int, dict[str, Any]],
                       linked_gids: set[str], root: str) -> str:
    margin = abs(safe_float(item.get("home_pts")) - safe_float(item.get("away_pts")))
    ot = _ot_label(item)
    meta = f"Season {safe_int(item.get('season'))} · Day {safe_int(item.get('day'))}"
    if item.get("playoffs"):
        meta += " · Playoffs"
    if ot:
        meta += f" · {ot}"
    return (
        f'<div class="rv-extreme"><span class="rv-extreme-label">{esc(label)}</span>'
        f'<span class="rv-extreme-score">{_game_score_html(item, teams_by_tid, linked_gids, root)}</span>'
        f'<span class="muted small-copy">{esc(meta)} · margin {fmt_number(margin, 0)}</span></div>'
    )


def _trade_history_html(data: dict[str, Any], tid_a: int, tid_b: int,
                        teams_by_tid: dict[int, dict[str, Any]],
                        all_players_by_pid: dict[int, dict[str, Any]], root: str) -> str:
    pair = {tid_a, tid_b}
    rows = []
    trades = [
        event for event in data.get("events", []) or []
        if event.get("type") == "trade" and {safe_int(t, -1) for t in (event.get("tids") or [])[:2]} == pair
    ]
    trades.sort(key=lambda e: (safe_int(e.get("season")), safe_int(e.get("eid"))))
    for event in trades:
        text = compose_event_html(event, all_players_by_pid, teams_by_tid, safe_int(event.get("season")), set(), root)
        if not text:
            continue
        rows.append(
            f'<li><span class="badge badge-accent">TRADE</span>'
            f'<span><span class="muted">{esc(event.get("season"))}:</span> {text}</span></li>'
        )
    if not rows:
        return '<p class="empty-state">No trades on record between these two teams.</p>'
    return f'<ul class="news-list">{"".join(rows)}</ul>'


def _meeting_log_html(meetings: list[dict[str, Any]], teams_by_tid: dict[int, dict[str, Any]],
                      linked_gids: set[str], root: str) -> str:
    rows = []
    for item in reversed(meetings):  # most recent first
        margin = abs(safe_float(item.get("home_pts")) - safe_float(item.get("away_pts")))
        ot = _ot_label(item)
        rows.append("".join([
            td(esc(item.get("season")), sort=item.get("season")),
            td(fmt_number(item.get("day"), 0), sort=item.get("day")),
            td("Playoffs" if item.get("playoffs") else "Regular", sort=1 if item.get("playoffs") else 0),
            td(_game_score_html(item, teams_by_tid, linked_gids, root), cls="name-cell",
               sort=safe_float(item.get("home_pts")) + safe_float(item.get("away_pts"))),
            td(fmt_number(margin, 0), sort=margin),
            td(esc(ot) if ot else "—", sort=safe_int((item.get("game") or {}).get("overtimes"))),
        ]))
    return table_html(
        ["Season", "Day", "Type", "Score", "Margin", "OT"], rows,
        table_id="meeting-log", empty_message="No retained meetings between these teams.",
        caption="Retained meetings between the two teams",
    )


def render_rivalry_pair_page(data: dict[str, Any], teams: list[dict[str, Any]],
                             team_a: dict[str, Any], team_b: dict[str, Any],
                             h2h: dict[int, dict[str, dict[tuple[int, int], dict[str, float]]]],
                             retained: list[dict[str, Any]], linked_gids: set[str],
                             all_players_by_pid: dict[int, dict[str, Any]]) -> str:
    root = "../"
    teams_by_tid = {int(t.get("tid")): t for t in teams if t.get("tid") is not None}
    tid_a, tid_b = safe_int(team_a.get("tid")), safe_int(team_b.get("tid"))
    ab_a, ab_b = team_abbrev(team_a), team_abbrev(team_b)

    total = all_time_record(h2h, tid_a, tid_b)
    games = total["won"] + total["lost"]
    if games <= 0:
        headline = "These teams have never met."
    elif total["won"] == total["lost"]:
        headline = f"All-time series tied {fmt_number(total['won'], 0)}-{fmt_number(total['lost'], 0)}"
    else:
        lead_team = team_a if total["won"] > total["lost"] else team_b
        w, l = max(total["won"], total["lost"]), min(total["won"], total["lost"])
        headline = f"{team_full_name(lead_team)} lead the all-time series {fmt_number(w, 0)}-{fmt_number(l, 0)}"
    diff = (total["pts"] - total["oppPts"]) / games if games > 0 else None
    diff_note = f" · {esc(ab_a)} {fmt_signed(diff, 1)} pts/game" if diff is not None else ""

    pair = {tid_a, tid_b}
    meetings = [it for it in retained
                if {safe_int(it.get("home_tid")), safe_int(it.get("away_tid"))} == pair]
    retained_span = _retained_seasons_label(retained)
    retained_note = (
        f"Game details cover retained box scores ({retained_span}); all-time records cover every season."
    ) if retained_span else "No box scores retained in this export."

    blowout_html = closest_html = ""
    if meetings:
        def margin_key(item: dict[str, Any]) -> tuple:
            margin = abs(safe_float(item.get("home_pts")) - safe_float(item.get("away_pts")))
            return (margin, safe_int(item.get("season")), safe_int(item.get("day")), str(item.get("gid")))
        blowout = max(meetings, key=margin_key)
        closest = min(meetings, key=margin_key)
        blowout_html = _extreme_game_line(blowout, "Biggest blowout", teams_by_tid, linked_gids, root)
        closest_html = _extreme_game_line(closest, "Closest game", teams_by_tid, linked_gids, root)
    extremes = (
        f'<div class="rv-extremes">{blowout_html}{closest_html}</div>'
        if meetings else '<p class="empty-state">No retained meetings between these teams.</p>'
    )

    body = f"""
    <section class="page-hero rv-hero">
      <div>
        <p class="eyebrow">Rivalry</p>
        <h1 class="rv-hero-title">{_team_chip(team_a, root)} <span class="rv-vs">vs</span> {_team_chip(team_b, root)}</h1>
        <p class="rv-headline">{esc(headline)}{diff_note}</p>
        <p class="muted small-copy">{esc(_streak_text(meetings, teams_by_tid))}</p>
      </div>
      <a class="button-link" href="{root}rivalries.html">All rivalries</a>
    </section>
    <section class="card">
      <div class="section-title-row"><h2>Season by Season</h2><span class="muted small-copy">{esc(ab_a)}'s record vs {esc(ab_b)}, playoffs included</span></div>
      {_season_strip_html(h2h, tid_a, tid_b, ab_a, ab_b)}
    </section>
    <section class="card">
      <div class="section-title-row"><h2>Playoff Meetings</h2></div>
      {_playoff_meetings_html(data, tid_a, tid_b, teams_by_tid, linked_gids, root)}
    </section>
    <section class="card">
      <div class="section-title-row"><h2>Extremes</h2><span class="muted small-copy">from retained box scores</span></div>
      {extremes}
      <p class="muted small-copy">{esc(retained_note)}</p>
    </section>
    <section class="card">
      <div class="section-title-row"><h2>Trade History</h2><span class="muted small-copy">deals between the two clubs</span></div>
      {_trade_history_html(data, tid_a, tid_b, teams_by_tid, all_players_by_pid, root)}
    </section>
    <section class="card">
      <div class="section-title-row"><h2>Meeting Log</h2><span class="count-pill">{len(meetings)} retained games</span></div>
      {_meeting_log_html(meetings, teams_by_tid, linked_gids, root)}
    </section>
    """
    title = f"{ab_a} vs {ab_b} Rivalry"
    return page_html(title, body, teams, root=root, active="rivalries")


def render_rivalries_pages(data: dict[str, Any], teams: list[dict[str, Any]]) -> dict[str, str]:
    """rivalries.html plus one page per team pair, keyed by output filename."""
    season = current_season(data)
    h2h = head_to_head_index(data)
    retained = _retained_items(data)
    linked_gids = _linked_game_gids(data, teams, season)
    all_players_by_pid = {safe_int(p.get("pid")): p for p in data.get("players", []) if p.get("pid") is not None}
    ordered = sorted((t for t in teams if t.get("tid") is not None and not t.get("disabled")), key=team_sort_key)

    out = {"rivalries.html": render_rivalry_grid_page(data, teams)}
    for i, team_a in enumerate(ordered):
        for team_b in ordered[i + 1:]:
            first, second = sorted((team_a, team_b), key=lambda t: safe_int(t.get("tid")))
            out[f"rivalries/{_pair_slug(first, second)}.html"] = render_rivalry_pair_page(
                data, teams, first, second, h2h, retained, linked_gids, all_players_by_pid,
            )
    return out


# ---------------------------------------------------------------------------
# classics.html — Greatest Games
# ---------------------------------------------------------------------------

def _max_deficit_boundary_phrase(game: dict[str, Any]) -> str:
    """Where the winner's period-boundary deficit peaked, as an 'entering the …' phrase."""
    boxes = game.get("teams") or []
    if len(boxes) < 2:
        return ""
    home_won = safe_float(boxes[0].get("pts")) > safe_float(boxes[1].get("pts"))
    home_q = boxes[0].get("ptsQtrs") or []
    away_q = boxes[1].get("ptsQtrs") or []
    running = 0.0
    worst = 0.0
    worst_index = -1
    for i, (h, a) in enumerate(zip(home_q, away_q)):
        running += safe_float(h) - safe_float(a)
        trailing_by = -running if home_won else running
        if trailing_by > worst:
            worst = trailing_by
            worst_index = i
    phrases = {0: "entering the 2nd", 1: "entering the 3rd", 2: "entering the 4th"}
    if worst_index < 0:
        return ""
    return phrases.get(worst_index, "entering overtime")


def _best_feat_clause(gid: Any, feats_by_gid: dict[str, list[dict[str, Any]]]) -> str:
    feats = feats_by_gid.get(str(gid)) or []
    best = None
    for feat in feats:
        stats = feat.get("stats") or {}
        pts = safe_float(stats.get("pts"))
        if best is None or pts > best[0]:
            best = (pts, feat)
    if best is None:
        return ""
    pts, feat = best
    stats = feat.get("stats") or {}
    name = str(feat.get("name") or "").strip()
    if not name:
        return ""
    pieces = []
    if pts >= 40:
        pieces.append(f"{fmt_number(pts, 0)} points")
    if safe_int(stats.get("qd")) > 0:
        pieces.append("a quadruple-double")
    elif safe_int(stats.get("td")) > 0:
        pieces.append("a triple-double")
    elif safe_int(stats.get("dd")) > 0 and pts < 40:
        pieces.append(f"a {fmt_number(pts, 0)}-point double-double")
    if not pieces:
        pieces.append(f"{fmt_number(pts, 0)} points")
    return f"; {name} finished with {' and '.join(pieces)}"


def classic_blurb(game: dict[str, Any], teams_by_tid: dict[int, dict[str, Any]],
                  feats_by_gid: dict[str, list[dict[str, Any]]]) -> str:
    """One factual sentence about a completed game — every clause from the box score."""
    boxes = game.get("teams") or []
    if len(boxes) < 2 or boxes[0].get("pts") is None or boxes[1].get("pts") is None:
        return ""
    home, away = boxes[0], boxes[1]
    home_pts, away_pts = safe_float(home.get("pts")), safe_float(away.get("pts"))
    win_box, lose_box = (home, away) if home_pts > away_pts else (away, home)
    win_ab = team_abbrev_for_tid(win_box.get("tid"), teams_by_tid)
    lose_ab = team_abbrev_for_tid(lose_box.get("tid"), teams_by_tid)
    win_pts, lose_pts = max(home_pts, away_pts), min(home_pts, away_pts)
    score = f"{fmt_number(win_pts, 0)}-{fmt_number(lose_pts, 0)}"
    margin = win_pts - lose_pts
    overtimes = safe_int(game.get("overtimes"))
    ot = "" if overtimes <= 0 else ("OT" if overtimes == 1 else f"{overtimes}OT")
    comeback = comeback_size(game)

    if comeback >= 10:
        boundary = _max_deficit_boundary_phrase(game)
        lead = f"Down {fmt_number(comeback, 0)}{f' {boundary}' if boundary else ''}, {win_ab} stormed back"
        lead += f" to win {score}" + (f" in {ot}" if ot else "")
    elif ot:
        lead = f"{win_ab} outlasted {lose_ab} {score} in {ot}"
    elif margin <= 3:
        lead = f"{win_ab} edged {lose_ab} {score}"
    else:
        lead = f"{win_ab} beat {lose_ab} {score}"
    if game.get("playoffs"):
        lead += " in the playoffs"
    return f"{lead}{_best_feat_clause(game.get('gid'), feats_by_gid)}."


def _classic_meta(game: dict[str, Any]) -> str:
    meta = f"Season {safe_int(game.get('season'))} · Day {safe_int(game.get('day'))}"
    meta += " · Playoffs" if game.get("playoffs") else " · Regular season"
    overtimes = safe_int(game.get("overtimes"))
    if overtimes > 0:
        meta += f" · {'OT' if overtimes == 1 else str(overtimes) + 'OT'}"
    return meta


def _ranked_games(data: dict[str, Any]) -> list[tuple[float, dict[str, Any]]]:
    feats_by_gid = feats_index(data)
    scored = []
    for game in data.get("games", []) or []:
        score = drama_index(game, feats_by_gid)
        boxes = game.get("teams") or []
        if len(boxes) < 2 or boxes[0].get("pts") is None or boxes[1].get("pts") is None:
            continue
        scored.append((score, game))
    scored.sort(key=lambda pair: (-pair[0], safe_int(pair[1].get("season")),
                                  safe_int(pair[1].get("day")), str(pair[1].get("gid"))))
    return scored


def _matchup_score_html(game: dict[str, Any], teams_by_tid: dict[int, dict[str, Any]],
                        linked_gids: set[str], root: str) -> str:
    item = {
        "gid": game.get("gid"),
        "home_tid": safe_int((game.get("teams") or [{}])[0].get("tid")),
        "away_tid": safe_int((game.get("teams") or [{}, {}])[1].get("tid")),
        "home_pts": (game.get("teams") or [{}])[0].get("pts"),
        "away_pts": (game.get("teams") or [{}, {}])[1].get("pts"),
        "game": game,
    }
    return _game_score_html(item, teams_by_tid, linked_gids, root)


# Drama-index weights, mirrored from derived.drama_index's docstring. Shown on
# the empty page so a reader learns what the ranking rewards before any game
# exists to rank; keep in sync if the weights ever move.
DRAMA_WEIGHTS = [
    ("Closeness", 30, "final margin — a 1-point game takes all 30, a 16-point game none"),
    ("Comeback", 25, "the largest deficit the winner erased, saturating at 20 points"),
    ("Overtime", 20, "10 for one extra period, the full 20 for two or more"),
    ("Clutch plays", 15, "late-game plays the engine flags, up to three"),
    ("Statistical feats", 10, "40-point nights, triple-doubles, quadruple-doubles"),
]


def _classics_empty_html(data: dict[str, Any], season: int) -> str:
    """The preseason state of classics.html.

    Year one has no box scores, so the ranked list is empty. Rather than repeat
    "nothing here" under a hero that already said it, the page spends the space
    explaining the scale every future game gets measured on — the same weights
    the drama badge reports once games exist.
    """
    scheduled = len(data.get("schedule") or [])
    count_html = (
        f'<span class="muted small-copy">0 of {scheduled} games played</span>'
        if scheduled else ""
    )
    rows = "".join(
        f'<li><span class="cl-weight-name">{esc(name)}</span>'
        f'<span class="cl-drama-meter" aria-hidden="true">'
        f'<span class="cl-drama-fill" style="width:{weight}%"></span></span>'
        f'<span class="cl-weight-num">{weight}</span>'
        f'<span class="cl-weight-note muted small-copy">{esc(note)}</span></li>'
        for name, weight, note in DRAMA_WEIGHTS
    )
    return f"""
      <section class="card cl-empty">
        <div class="section-title-row">
          <h2>Nothing to rank yet</h2>
          {count_html}
        </div>
        <p class="empty-state">The {esc(season)} season hasn't tipped off. Every completed game is scored
        0–100 as soon as it reaches the export, and the ten highest take these slots.</p>
        <ul class="cl-weights">{rows}</ul>
        <p class="muted small-copy">Weights out of 100. A one-point double-overtime comeback with three
        clutch plays and two feats is the only way to score all of them.</p>
        <p class="cl-empty-links">
          <a class="button-link" href="schedule.html">The {esc(season)} schedule</a>
          <a class="button-link" href="simulator.html">Win-Out Machine</a>
        </p>
      </section>
    """


def render_classics_page(data: dict[str, Any], teams: list[dict[str, Any]]) -> str:
    season = current_season(data)
    teams_by_tid = {int(t.get("tid")): t for t in teams if t.get("tid") is not None}
    feats_by_gid = feats_index(data)
    linked_gids = _linked_game_gids(data, teams, season)
    ranked = _ranked_games(data)
    retained_span = _retained_seasons_label(_retained_items(data))

    featured = ranked[:CLASSICS_FEATURED]

    articles = []
    for rank, (score, game) in enumerate(featured, 1):
        gid = game.get("gid")
        anchor = f"g{esc(gid)}"
        medal_cls = f"cl-medal-{rank}" if rank <= 3 else "cl-medal-std"
        box_link = (
            f'<a class="button-link cl-box-link" href="games/{esc(gid)}.html">Box score</a>'
            if str(gid) in linked_gids else ""
        )
        meter_pct = max(0.0, min(100.0, score))
        articles.append(f"""
        <article class="cl-game{' cl-top3' if rank <= 3 else ''}" id="{anchor}">
          <div class="cl-medal {medal_cls}" aria-hidden="true"><span class="cl-medal-num">{rank}</span></div>
          <div class="cl-body">
            <div class="cl-scoreline">{_matchup_score_html(game, teams_by_tid, linked_gids, "")}</div>
            <p class="cl-meta muted small-copy">{esc(_classic_meta(game))}</p>
            <p class="cl-blurb">{esc(classic_blurb(game, teams_by_tid, feats_by_gid))}</p>
            <div class="cl-foot">{box_link}<a class="cl-permalink" href="#{anchor}" aria-label="Permalink to game {esc(gid)}">#</a></div>
          </div>
          <div class="cl-drama">
            <span class="cl-badge" title="Drama index 0–100: closeness, overtimes, comeback size, clutch plays, statistical feats">Drama</span>
            <span class="cl-drama-num">{fmt_number(score, 1)}</span>
            <span class="cl-drama-meter" aria-hidden="true"><span class="cl-drama-fill" style="width:{meter_pct:.1f}%"></span></span>
          </div>
        </article>
        """)

    # One statement of "there is nothing here yet", not two. With games, the hero
    # counts them; without, the hero describes the ranking and the panel below
    # carries the single empty-state sentence plus what will fill the page.
    if retained_span:
        span_note = (
            f"Top {min(CLASSICS_FEATURED, len(ranked))} of {len(ranked)} retained games "
            f"({retained_span}) by drama index"
        )
        list_html = "".join(articles)
    else:
        span_note = "Ranked by drama index — closeness, overtimes, comeback size, clutch plays and feats"
        list_html = _classics_empty_html(data, season)
    body = f"""
    <section class="page-hero cl-hero">
      <div>
        <p class="eyebrow">Hall of Fame</p>
        <h1>Greatest Games</h1>
        <p class="muted">{esc(span_note)}</p>
      </div>
    </section>
    <div class="cl-list">
      {list_html}
    </div>
    """
    return page_html("Greatest Games", body, teams, root="", active="classics")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def render_extras_pages(data: dict[str, Any], teams: list[dict[str, Any]]) -> dict[str, str]:
    """All extras outputs, keyed by output filename relative to the site root."""
    out = render_rivalries_pages(data, teams)
    out["classics.html"] = render_classics_page(data, teams)
    return out
