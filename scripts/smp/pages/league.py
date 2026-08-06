from __future__ import annotations

import json
import math
from collections import defaultdict
from typing import Any

from ..core import (
    ALL_PLAYERS_BY_PID,
    EVENT_BADGES,
    FREE_AGENT_TID,
    RETIRED_TID,
    RATING_GROUP_STARTS,
    SCATTER_METRICS,
    TEAM_PALETTE,
    TEAM_RATING_RANK_KEYS,
    active_players,
    active_teams_for_season,
    age,
    build_game_logs,
    combine_stat_rows,
    completed_game_items,
    compose_event_html,
    current_season,
    draft_prospects,
    efg_pct,
    esc,
    event_player_link,
    fmt_contract,
    fmt_height,
    fmt_money,
    fmt_number,
    fmt_pct,
    fmt_record,
    game_ot_label,
    game_slug_from_gid,
    game_url,
    game_winner_tid,
    heat_style,
    inferred_upcoming_schedule_season,
    initials,
    is_completed_game_item,
    latest_rating,
    latest_regular_stat,
    latest_team_season,
    made_pct,
    page_html,
    per36,
    per36_trb,
    per_game,
    player_link,
    player_name,
    player_url,
    rating_delta_html,
    regular_season_length,
    safe_float,
    safe_int,
    schedule_matchup_label,
    score_items_for_page,
    season_regular_stat,
    seed_cell_style,
    standings_order,
    stat_gp,
    table_html,
    td,
    team_abbrev,
    team_abbrev_for_tid,
    team_anchor,
    team_dot,
    team_full_name,
    team_label,
    team_palette_by_tid,
    team_schedule_result,
    team_url,
    th,
    total_rebounds,
    ts_pct,
)

from ..simmodel import fa_salary_by_length, league_sim, sim_client_inputs

from ..derived import fantasy_pts, led_league

from ..identity import crest_svg, monogram_svg, team_css_vars

from ..portraits import portrait_html

# Cards in the Top of the Market strip. Kept to one row -- .fa-card-strip lays out
# exactly this many columns, so changing it here means changing it in league.css too.
TOP_MARKET_CARDS = 8


# ---------------------------------------------------------------------------
# Shared league-page helpers: ordinals, led-league gold, honors, pennants
# ---------------------------------------------------------------------------

_ORDINAL_SUFFIX = {1: "st", 2: "nd", 3: "rd"}


def ordinal(n: Any) -> str:
    n = safe_int(n)
    if 10 <= n % 100 <= 20:
        suffix = "th"
    else:
        suffix = _ORDINAL_SUFFIX.get(n % 10, "th")
    return f"{n}{suffix}"


def led_league_mark(value_html: str, note: str) -> str:
    """Wrap already-rendered stat HTML in the shared gold led-the-league treatment."""
    return (
        f'<span class="led-league" title="{esc(note)}">{value_html}'
        f'<span class="led-star" aria-hidden="true">★</span>'
        f'<span class="sr-only"> (led the league)</span></span>'
    )


def _portrait_safe(player: dict[str, Any], cls: str, root: str = "", size: int = 56) -> str:
    """portraits.portrait_html with a monogram fallback.

    portrait_html's final monogram branch currently passes a ``size`` kwarg that
    identity.monogram_svg does not accept; until that lands upstream, catch the
    TypeError and inline the roundel ourselves so no player renders broken.
    """
    try:
        return portrait_html(player, cls=cls, root=root, size=size)
    except TypeError:
        mono = monogram_svg(initials(player), player.get("tid"), jersey_number=player.get("jerseyNumber"))
        return (
            f'<span class="{esc(cls)} portrait-monogram" role="img" '
            f'aria-label="{esc(player_name(player))}">{mono}</span>'
        )


def league_start_season(data: dict[str, Any]) -> int:
    """Year one of the league, from gameAttributes rather than a hardcoded year."""
    start = safe_int((data.get("gameAttributes") or {}).get("startingSeason"))
    return start or current_season(data)


def champions_by_season(data: dict[str, Any]) -> dict[int, int]:
    """season -> championship-winning tid, from the exported playoff brackets."""
    out: dict[int, int] = {}
    for ps in data.get("playoffSeries", []):
        if not isinstance(ps, dict):
            continue
        season = ps.get("season")
        rounds = ps.get("series") or []
        if not isinstance(season, int) or not rounds or not rounds[-1]:
            continue
        final = rounds[-1][0]
        home, away = final.get("home") or {}, final.get("away") or {}
        if not home or not away:
            continue
        champ = home if safe_int(home.get("won")) > safe_int(away.get("won")) else away
        out[season] = safe_int(champ.get("tid"), -1)
    return out


# Crest kinds in trophy-case display order, with tooltip labels.
_HONOR_KINDS = [
    ("champion", "Champion"),
    ("mvp", "MVP"),
    ("finals_mvp", "Finals MVP"),
    ("sfmvp", "Semifinals MVP"),
    ("dpoy", "Defensive POY"),
    ("smoy", "Sixth Man"),
    ("mip", "Most Improved"),
    ("roy", "Rookie of the Year"),
    ("all_league_1", "All-League 1st Team"),
    ("all_league_2", "All-League 2nd Team"),
    ("all_league_3", "All-League 3rd Team"),
    ("all_defensive", "All-Defensive"),
    ("all_rookie", "All-Rookie"),
]

_ALL_LEAGUE_TEAM_KINDS = {"First Team": "all_league_1", "Second Team": "all_league_2", "Third Team": "all_league_3"}


def player_honors_index(data: dict[str, Any]) -> dict[int, list[tuple[str, int]]]:
    """pid -> [(crest kind, season), ...] from the awards log plus playoff titles."""
    out: dict[int, list[tuple[str, int]]] = defaultdict(list)

    def add(winner: Any, kind: str, season: int) -> None:
        if isinstance(winner, dict) and winner.get("pid") is not None:
            out[safe_int(winner.get("pid"))].append((kind, season))

    for award in data.get("awards", []):
        if not isinstance(award, dict):
            continue
        season = safe_int(award.get("season"), -1)
        if season < 0:
            continue
        for key, kind in (("mvp", "mvp"), ("dpoy", "dpoy"), ("smoy", "smoy"), ("mip", "mip"),
                          ("roy", "roy"), ("finalsMvp", "finals_mvp")):
            add(award.get(key), kind, season)
        sfmvp = award.get("sfmvp")
        for winner in (sfmvp if isinstance(sfmvp, list) else [sfmvp]):
            add(winner, "sfmvp", season)
        for group in award.get("allLeague") or []:
            if not isinstance(group, dict):
                continue
            kind = _ALL_LEAGUE_TEAM_KINDS.get(group.get("title") or "First Team", "all_league_1")
            for member in group.get("players") or []:
                add(member, kind, season)
        def_groups = award.get("allDefensive") or []
        if def_groups and isinstance(def_groups[0], dict) and "players" not in def_groups[0]:
            def_groups = [{"players": def_groups}]
        for group in def_groups[:1]:  # 1st team only, matching honors_html
            if isinstance(group, dict):
                for member in group.get("players") or []:
                    add(member, "all_defensive", season)
        for member in award.get("allRookie") or []:
            add(member, "all_rookie", season)

    champs = champions_by_season(data)
    for player in data.get("players", []):
        pid = player.get("pid")
        if pid is None:
            continue
        for row in player.get("stats", []):
            if not (isinstance(row, dict) and row.get("playoffs")):
                continue
            season = safe_int(row.get("season"), -1)
            if champs.get(season) == safe_int(row.get("tid"), -9) and stat_gp(row) > 0:
                add({"pid": pid}, "champion", season)
    return dict(out)


def honor_chips_html(honors: list[tuple[str, int]]) -> str:
    """Compact crest-chip strip for a player's honors, grouped by kind with ×N counts."""
    if not honors:
        return '<span class="muted">—</span>'
    grouped: dict[str, list[int]] = defaultdict(list)
    for kind, season in honors:
        grouped[kind].append(season)
    chips = []
    for kind, label in _HONOR_KINDS:
        seasons = sorted(grouped.get(kind, []))
        if not seasons:
            continue
        count = f'<span class="regrade-crest-count">×{len(seasons)}</span>' if len(seasons) > 1 else ""
        title = f"{label} " + ", ".join(str(s) for s in seasons)
        chips.append(
            f'<span class="regrade-crest" title="{esc(title)}">'
            f'{crest_svg(kind, css_class="crest")}{count}'
            f'<span class="sr-only">{esc(title)}</span></span>'
        )
    return f'<span class="regrade-crests">{"".join(chips)}</span>'


def career_regular_totals(player: dict[str, Any]) -> dict[str, Any]:
    """Raw career regular-season totals for the re-grade value columns."""
    rows = [s for s in player.get("stats", []) if isinstance(s, dict) and not s.get("playoffs")]
    gp = sum(stat_gp(s) for s in rows)
    pts = sum(safe_float(s.get("pts")) for s in rows)
    ws = sum(safe_float(s.get("ows")) + safe_float(s.get("dws")) for s in rows)
    ewa = sum(safe_float(s.get("ewa")) for s in rows)
    return {"gp": gp, "pts": pts, "ws": ws, "ewa": ewa, "ppg": (pts / gp) if gp else None}


_PENNANT_FONT = "'Helvetica Neue',Helvetica,Arial,sans-serif"

# 5-point star centered on (48, 47), outer radius 6.5, inner radius 2.7.
_PENNANT_STAR = ("48,40.5 49.9,45.1 54.9,45.5 51.1,48.7 52.3,53.6 "
                 "48,51 43.7,53.6 44.9,48.7 41.1,45.5 46.1,45.1")


def pennant_svg(team: dict[str, Any], year: int | None = None) -> str:
    """Championship banner SVG in team colors; ``year=None`` renders the empty
    dashed placeholder slot for a franchise with no titles yet."""
    tid = safe_int(team.get("tid"), -1)
    abbrev = team_abbrev(team)
    if year is None:
        return (
            '<svg class="rafters-pennant rafters-pennant-empty" viewBox="0 0 96 132" '
            'aria-hidden="true" focusable="false" xmlns="http://www.w3.org/2000/svg">'
            '<rect x="4" y="3" width="88" height="5" rx="2" fill="none" stroke="var(--line)" stroke-width="1.5"/>'
            '<path d="M10 12h76v72L48 126 10 84z" fill="none" stroke="var(--line)" '
            'stroke-width="2" stroke-dasharray="5 5"/></svg>'
        )
    label = f"{team_full_name(team)} — {year} champions"
    return (
        f'<svg class="rafters-pennant" viewBox="0 0 96 132" style="{team_css_vars(tid)}" '
        f'role="img" aria-label="{esc(label)}" xmlns="http://www.w3.org/2000/svg">'
        f'<title>{esc(label)}</title>'
        '<rect x="4" y="3" width="88" height="5" rx="2" fill="var(--team-secondary)"/>'
        '<rect x="20" y="6" width="4" height="9" fill="var(--team-secondary)" opacity=".85"/>'
        '<rect x="72" y="6" width="4" height="9" fill="var(--team-secondary)" opacity=".85"/>'
        '<path d="M10 12h76v72L48 126 10 84z" fill="var(--team-primary)" '
        'stroke="var(--team-secondary)" stroke-width="2.5"/>'
        '<path d="M16.5 18.5h63v62.5L48 117.5 16.5 81z" fill="none" '
        'stroke="var(--team-on-primary)" stroke-width="1" opacity=".25"/>'
        f'<text x="48" y="33" text-anchor="middle" font-family="{_PENNANT_FONT}" '
        f'font-weight="700" font-size="11" letter-spacing="2.4" fill="var(--team-on-primary)" opacity=".85">{esc(abbrev)}</text>'
        f'<polygon points="{_PENNANT_STAR}" fill="var(--team-secondary)"/>'
        f'<text x="48" y="80" text-anchor="middle" font-family="{_PENNANT_FONT}" '
        f'font-weight="800" font-size="23" letter-spacing=".5" fill="var(--team-on-primary)">{esc(year)}</text>'
        f'<text x="48" y="94" text-anchor="middle" font-family="{_PENNANT_FONT}" '
        'font-weight="600" font-size="6.6" letter-spacing="1.9" fill="var(--team-on-primary)" '
        'opacity=".8">CHAMPIONS</text></svg>'
    )


def rafters_strip_html(data: dict[str, Any], teams: list[dict[str, Any]]) -> str:
    """All ten franchises' championship pennants side by side (empty slots stay honest)."""
    champs = champions_by_season(data)
    by_tid: dict[int, list[int]] = defaultdict(list)
    for season, tid in sorted(champs.items()):
        by_tid[tid].append(season)
    strip_teams = sorted(
        (t for t in teams if t.get("tid") is not None and not t.get("disabled")),
        key=lambda t: team_abbrev(t),
    )
    if not strip_teams or not champs:
        return ""
    slots = []
    for team in strip_teams:
        tid = safe_int(team.get("tid"), -1)
        years = by_tid.get(tid, [])
        if years:
            flags = "".join(
                f'<a class="rafters-flag" href="#season-{y}">{pennant_svg(team, y)}</a>'
                for y in years
            )
        else:
            flags = f'<span class="rafters-flag" title="No championships yet">{pennant_svg(team)}</span>'
        title_count = f'{len(years)} title{"s" if len(years) != 1 else ""}' if years else "no titles yet"
        slot_cls = "rafters-slot rafters-champ" if years else "rafters-slot"
        slots.append(
            f'<div class="{slot_cls}" role="listitem">'
            f'<div class="rafters-flags">{flags}</div>'
            f'<span class="rafters-abbrev">{esc(team_abbrev(team))} '
            f'<span class="rafters-count{"" if years else " rafters-count-none"}">{esc(title_count)}</span></span></div>'
        )
    return f"""
    <section class="card rafters-card">
      <div class="section-title-row"><h2>The Rafters</h2><span class="muted small-copy">click a pennant for that season</span></div>
      <div class="rafters" role="list">{''.join(slots)}</div>
    </section>
    """


def fa_asking_price(player: dict[str, Any], season: int) -> float:
    """What this free agent is asking per year, in BBGM thousands.

    The export's contract IS the ask. scripts/price_contracts.py prices every player in
    the league off one Monte Carlo projection of his own sub-ratings and writes the
    result back as {amount, exp}, so that number is what the game quotes at the table and
    what the draft board already prints. Re-deriving an ask from simmodel's ovr/age curve
    predates that repricing and disagreed with it badly -- Carmelo Anthony asked $6M here
    against the $24M on his card in the game -- so the curve is now only the fallback for
    a pool nobody has priced.
    """
    amount = safe_float((player.get("contract") or {}).get("amount"))
    if amount > 0:
        return amount
    rating = latest_rating(player, season)
    born = (player.get("born") or {}).get("year")
    age_val = (season - born) if isinstance(born, int) else 25
    raw = fa_salary_by_length(safe_int(rating.get("ovr")), safe_int(rating.get("pot")), age_val)[0] * 1000
    return float(max(1, round(raw / 1000)) * 1000)


def fa_asking_term(player: dict[str, Any], season: int) -> str:
    """"thru 2008" for a priced ask, or "" when the export carries no term.

    The ask is an annual figure on a deal of a known length -- quoting the dollars
    without the term is what made the old asking price unreadable. Quoted as an
    expiry rather than a year count, exactly as BBGM quotes it: price_contracts.py
    values a deal over the seasons AFTER the one being played and the site counts
    guaranteed years inclusive of it, so a year count would have to pick a side of
    that disagreement. The expiry is the same number either way.
    """
    contract = player.get("contract") or {}
    exp = contract.get("exp")
    if not isinstance(exp, int) or safe_float(contract.get("amount")) <= 0 or exp < season:
        return ""
    return f"thru {exp}"


def fa_market_is_priced(bids: list[float]) -> bool:
    """Does the salary model actually separate this free-agent pool?

    A column of identical dollar values is worse than no column, so this gates the
    Starting Bid display. The old test was "fewer than half the market shares the
    cheapest ask" -- but in SMP II 496 players compete for 120 jobs, so ~61% of the
    pool sits at the league minimum for a real economic reason, not a calibration
    failure. That test hid a correctly-priced column permanently.

    What actually matters is whether the model distinguishes anyone: if the top of
    the market is separated from the floor, the column carries information even when
    the long tail is bunched at the minimum.
    """
    if not bids:
        return False
    return len({round(bid, 6) for bid in bids}) > 1


def free_agent_row(player: dict[str, Any], season: int, root: str, rating_ranges: dict[str, tuple[float, float]], show_bid: bool = True) -> str:
    rating = latest_rating(player, season)
    born = (player.get("born") or {}).get("year")
    cells = [
        td(player_link(player, root, show_number=False), sort=player_name(player), cls="name-cell"),
        td(esc(rating.get("pos", "—")), sort=rating.get("pos", "")),
        td(age(player, season), sort=(season - born if isinstance(born, int) else None)),
        td(esc(rating.get("ovr") if rating.get("ovr") is not None else "—"), sort=rating.get("ovr")),
        td(esc(rating.get("pot") if rating.get("pot") is not None else "—"), sort=rating.get("pot")),
    ]
    if show_bid:
        bid_k = fa_asking_price(player, season)
        exp = safe_int((player.get("contract") or {}).get("exp"), 0)
        cells.append(td(fmt_money(bid_k), sort=bid_k, cls="group-start"))
        cells.append(td(esc(exp or "—"), sort=exp))
    for key, _ in TEAM_RATING_RANK_KEYS:
        value = rating.get(key)
        lo, hi = rating_ranges.get(key, (0.0, 0.0))
        cls = "group-start" if key in RATING_GROUP_STARTS else ""
        cells.append(td(esc(value if value is not None else "—"), sort=value, cls=cls, style=heat_style(value, lo, hi, 1)))
    return "".join(cells)


def render_free_agency_page(players: list[dict[str, Any]], teams: list[dict[str, Any]], season: int, start_season: int, all_players: list[dict[str, Any]] | None = None, market_year: int | None = None) -> str:
    market_year = market_year if market_year is not None else season

    def market_sort_key(player: dict[str, Any]) -> tuple[int, int, str]:
        rating = latest_rating(player, season)
        return (-safe_int(rating.get("ovr")), -safe_int(rating.get("pot")), player_name(player))

    sorted_players = sorted(players, key=market_sort_key)

    rating_ranges: dict[str, tuple[float, float]] = {}
    for key, _ in TEAM_RATING_RANK_KEYS:
        values = []
        for p in sorted_players:
            value = latest_rating(p, season).get(key)
            if value is not None and math.isfinite(safe_float(value, float("nan"))):
                values.append(float(value))
        rating_ranges[key] = (min(values), max(values)) if values else (0.0, 0.0)

    show_bids = fa_market_is_priced([fa_asking_price(p, season) for p in sorted_players])

    headers: list = ["Name", "Pos", "Age", "Ovr", "Pot"]
    if show_bids:
        headers.append(("Asking", "group-start"))
        headers.append("Thru")
    for key, label in TEAM_RATING_RANK_KEYS:
        headers.append((label, "group-start" if key in RATING_GROUP_STARTS else ""))
    rows = [free_agent_row(p, season, "", rating_ranges, show_bid=show_bids) for p in sorted_players]

    fa_cards = []
    for rank, p in enumerate(sorted_players[:TOP_MARKET_CARDS], 1):
        rating = latest_rating(p, season)
        meta_bits = [rating.get("pos") or "—", f"{age(p, season)} yr",
                     f"{rating.get('ovr', '—')} ovr / {rating.get('pot', '—')} pot"]
        ask_chip = ""
        if show_bids:
            term = fa_asking_term(p, season)
            ask_chip = (f'<span class="fa-card-ask" title="Asking price{" — " + term if term else ""}">'
                        f'{fmt_money(fa_asking_price(p, season))}</span>')
        fa_cards.append(
            f'<a class="fa-card" href="{player_url(p)}">'
            f'<span class="fa-card-rank" aria-hidden="true">{rank}</span>'
            f'{_portrait_safe(p, "fa-card-portrait", root="", size=56)}'
            f'<span class="fa-card-name">{esc(player_name(p))}</span>'
            f'<span class="fa-card-meta">{esc(" · ".join(str(b) for b in meta_bits))}</span>'
            f'{ask_chip}'
            f'</a>'
        )
    fa_card_strip = ""
    if fa_cards:
        strip_note = "best available by overall · chip = asking price" if show_bids else "best available by overall"
        fa_card_strip = f"""
    <section class="card">
      <div class="section-title-row"><h2>Top of the Market</h2><span class="muted small-copy">{strip_note}</span></div>
      <div class="fa-card-strip">{''.join(fa_cards)}</div>
    </section>
    """

    # With every ask clamped to the same minimum, a Starting Bid column is a wall of one
    # number, so the page says why it is missing instead of printing a false precision.
    hero_note = (
        "Asking price is the player's own priced contract — the annual salary the league values "
        "him at, from a Monte Carlo projection of his ratings over the length of the deal."
        if show_bids else
        "Ranked by overall. Asking prices are held back this year — the salary model still puts most of "
        "this market at the league minimum, so a bid column would print one number down the whole board."
    )
    body = f"""
    <section class="page-hero">
      <div>
        <p class="eyebrow">Free Agency</p>
        <h1>{market_year} Free Agents</h1>
        <p class="muted">{hero_note}</p>
      </div>
    </section>
    {fa_card_strip}
    <section class="card">
      <div class="section-title-row"><h2>Available Players</h2><span class="count-pill">{len(sorted_players)}</span></div>
      <div class="toolbar">
        <input class="table-search" data-table-filter="free-agents" placeholder="Filter free agents…" aria-label="Filter free agents">
      </div>
      {table_html(headers, rows, table_id="free-agents", empty_message="No free agents found.", caption=f"{market_year} free agents", pos_filter=True)}
    </section>
    """
    return page_html("Free Agents", body, teams, root="", active="free-agency")


def render_players_index(players: list[dict[str, Any]], teams: list[dict[str, Any]], season: int, start_season: int, data: dict[str, Any] | None = None) -> str:
    teams_by_tid = {t["tid"]: t for t in teams}
    rostered = [p for p in players if isinstance(p.get("tid"), int) and p.get("tid") >= 0]
    sorted_players = sorted(rostered, key=lambda p: (p.get("tid", 999), -safe_int(latest_rating(p, season).get("ovr")), player_name(p)))
    fa_players = sorted(
        [p for p in players if p.get("tid") == FREE_AGENT_TID],
        key=lambda p: (-safe_int(latest_rating(p, season).get("ovr")), -safe_int(latest_rating(p, season).get("pot")), player_name(p)),
    )
    prospects = sorted(
        draft_prospects(data) if data else [],
        key=lambda p: (safe_int((p.get("draft") or {}).get("year"), 9999), -safe_int(latest_rating(p).get("pot")), -safe_int(latest_rating(p).get("ovr")), player_name(p)),
    )
    grouped_players: list[tuple[dict[str, Any], str]] = (
        [(p, "roster") for p in sorted_players] + [(p, "fa") for p in fa_players] + [(p, "draft") for p in prospects]
    )

    def group_rating(p: dict[str, Any], group: str) -> dict[str, Any]:
        # Prospects only carry their draft-class ratings row; everyone else uses this season's.
        return latest_rating(p) if group == "draft" else latest_rating(p, season)

    rating_ranges: dict[str, tuple[float, float]] = {}
    for key, _ in TEAM_RATING_RANK_KEYS:
        values = []
        for p, group in grouped_players:
            value = group_rating(p, group).get(key)
            if value is not None and math.isfinite(safe_float(value, float("nan"))):
                values.append(float(value))
        rating_ranges[key] = (min(values), max(values)) if values else (0.0, 0.0)

    headers = [
        "Name", "Team", "Pos", "Age", "Ovr", "Pot", "G", "MP",
        ("Contract", "col-basic"), ("PTS", "col-basic"), ("TRB", "col-basic"), ("AST", "col-basic"),
        ("TS%", "col-adv"), ("USG%", "col-adv"), ("ORtg", "col-adv"), ("DRtg", "col-adv"),
        ("OBPM", "col-adv"), ("DBPM", "col-adv"), ("BPM", "col-adv"), ("VORP", "col-adv"),
        ("Value", "col-adv"),
        ("PTS/36", "col-p36"), ("TRB/36", "col-p36"), ("AST/36", "col-p36"),
        ("STL/36", "col-p36"), ("BLK/36", "col-p36"), ("TOV/36", "col-p36"),
    ]
    for key, label in TEAM_RATING_RANK_KEYS:
        headers.append((label, "col-rate group-start" if key in RATING_GROUP_STARTS else "col-rate"))
    rows = []
    for p, group in grouped_players:
        rating = group_rating(p, group)
        stat = latest_regular_stat(p, start_season, season)
        gp = stat_gp(stat)
        trb_pg = (float(stat.get("orb") or 0) + float(stat.get("drb") or 0)) / gp if gp else 0
        obpm = safe_float(stat.get("obpm"), 0.0)
        dbpm = safe_float(stat.get("dbpm"), 0.0)
        if group == "fa":
            team_cell = td('<span class="muted">FA</span>', sort="FA")
        elif group == "draft":
            draft_year = (p.get("draft") or {}).get("year")
            label = f"{draft_year} Draft" if isinstance(draft_year, int) else "Draft"
            team_cell = td(f'<span class="muted">{esc(label)}</span>', sort=draft_year if isinstance(draft_year, int) else "Draft")
        else:
            team_cell = td(team_label(p.get("tid"), teams_by_tid, "../"), sort=team_label(p.get("tid"), teams_by_tid, as_link=False))
        cells = [
            td(player_link(p, "../", show_number=False), sort=player_name(p), cls="name-cell"),
            team_cell,
            td(esc(rating.get("pos", "—")), sort=rating.get("pos", "")),
            td(age(p, season), sort=(season - (p.get("born") or {}).get("year", season) if isinstance((p.get("born") or {}).get("year"), int) else None)),
            td(rating_delta_html(p, "ovr", rating), sort=rating.get("ovr")),
            td(rating_delta_html(p, "pot", rating), sort=rating.get("pot")),
            td(fmt_number(gp, 0), sort=gp),
            td(fmt_number(per_game(stat, "min"), 1), sort=per_game(stat, "min")),
            td(fmt_contract(p), sort=(p.get("contract") or {}).get("amount"), cls="col-basic"),
            td(fmt_number(per_game(stat, "pts"), 1), sort=per_game(stat, "pts"), cls="col-basic"),
            td(fmt_number(trb_pg, 1), sort=trb_pg, cls="col-basic"),
            td(fmt_number(per_game(stat, "ast"), 1), sort=per_game(stat, "ast"), cls="col-basic"),
            td(fmt_pct(ts_pct(stat)), sort=ts_pct(stat), cls="col-adv"),
            td(fmt_number(stat.get("usgp"), 1), sort=stat.get("usgp"), cls="col-adv"),
            td(fmt_number(stat.get("ortg"), 1), sort=stat.get("ortg"), cls="col-adv"),
            td(fmt_number(stat.get("drtg"), 1), sort=stat.get("drtg"), cls="col-adv"),
            td(fmt_number(obpm, 1), sort=obpm, cls="col-adv"),
            td(fmt_number(dbpm, 1), sort=dbpm, cls="col-adv"),
            td(fmt_number(obpm + dbpm, 1), sort=obpm + dbpm, cls="col-adv"),
            td(fmt_number(stat.get("vorp"), 1), sort=stat.get("vorp"), cls="col-adv"),
            td(fmt_number(p.get("value"), 1), sort=p.get("value"), cls="col-adv"),
            td(fmt_number(per36(stat, "pts"), 1), sort=per36(stat, "pts"), cls="col-p36"),
            td(fmt_number(per36_trb(stat), 1), sort=per36_trb(stat), cls="col-p36"),
            td(fmt_number(per36(stat, "ast"), 1), sort=per36(stat, "ast"), cls="col-p36"),
            td(fmt_number(per36(stat, "stl"), 1), sort=per36(stat, "stl"), cls="col-p36"),
            td(fmt_number(per36(stat, "blk"), 1), sort=per36(stat, "blk"), cls="col-p36"),
            td(fmt_number(per36(stat, "tov"), 1), sort=per36(stat, "tov"), cls="col-p36"),
        ]
        for key, _ in TEAM_RATING_RANK_KEYS:
            value = rating.get(key)
            lo, hi = rating_ranges.get(key, (0.0, 0.0))
            cls = "col-rate group-start" if key in RATING_GROUP_STARTS else "col-rate"
            cells.append(td(esc(value if value is not None else "—"), sort=value, cls=cls, style=heat_style(value, lo, hi, 1)))
        hidden_cls = "" if group == "roster" else " class=\"group-hidden\""
        rows.append(f'<tr data-group="{group}"{hidden_cls}>{"".join(cells)}</tr>')

    palette_teams = sorted((t for t in teams if t.get("tid") is not None and not t.get("disabled")), key=lambda t: team_abbrev(t))
    team_colors = {team_abbrev(t): TEAM_PALETTE[i % len(TEAM_PALETTE)] for i, t in enumerate(palette_teams)}
    chart_players = []
    # Rostered players plus free agents who logged games this season (the loop drops anyone
    # with 0 GP); FAs are colored by the team they actually played for (from the stat row).
    chart_pool = sorted_players + [p for p in players if p.get("tid") == FREE_AGENT_TID]
    for p in chart_pool:
        stat = latest_regular_stat(p, start_season, season)
        gp = stat_gp(stat)
        if gp <= 0:
            continue
        rating = latest_rating(p, season)
        born_year = (p.get("born") or {}).get("year")
        values = {
            "pts": per_game(stat, "pts"), "trb": (float(stat.get("orb") or 0) + float(stat.get("drb") or 0)) / gp,
            "ast": per_game(stat, "ast"), "stl": per_game(stat, "stl"), "blk": per_game(stat, "blk"),
            "tov": per_game(stat, "tov"), "min": per_game(stat, "min"),
            "fgp": made_pct(stat.get("fg"), stat.get("fga")), "tpp": made_pct(stat.get("tp"), stat.get("tpa")),
            "ftp": made_pct(stat.get("ft"), stat.get("fta")), "ts": ts_pct(stat), "efg": efg_pct(stat),
            "usg": stat.get("usgp"), "per": stat.get("per"), "ortg": stat.get("ortg"), "drtg": stat.get("drtg"),
            "obpm": stat.get("obpm"), "dbpm": stat.get("dbpm"),
            "bpm": safe_float(stat.get("obpm"), 0.0) + safe_float(stat.get("dbpm"), 0.0),
            "vorp": stat.get("vorp"), "ws": safe_float(stat.get("ows"), 0.0) + safe_float(stat.get("dws"), 0.0),
            "age": (season - born_year) if isinstance(born_year, int) else None,
            "ovr": rating.get("ovr"), "pot": rating.get("pot"), "gp": gp,
        }
        clean = {}
        for key, value in values.items():
            number = safe_float(value, float("nan"))
            clean[key] = round(number, 2) if math.isfinite(number) and value is not None else None
        color_tid = safe_int(p.get("tid"), -1)
        if color_tid < 0:
            color_tid = safe_int(stat.get("tid"), -1)
        chart_players.append({
            "name": player_name(p),
            "team": team_abbrev_for_tid(color_tid, teams_by_tid),
            "pos": rating.get("pos", ""),
            "url": player_url(p, "../"),
            "v": clean,
        })
    payload = {
        "metrics": [{"key": key, "label": label} for key, label in SCATTER_METRICS],
        "defaultX": "obpm",
        "defaultY": "dbpm",
        "teams": [{"abbrev": abbrev, "color": color} for abbrev, color in team_colors.items()],
        "players": chart_players,
    }
    payload_json = json.dumps(payload, separators=(",", ":")).replace("</", "<\\/")

    # The scatter's Min GP floor tracks the season: a literal 36 was 80% of a 45-game year
    # but is a perfect-attendance bar in a 36-game one.
    season_games = regular_season_length(data, season) if data else 0
    chart_min_gp = max(5, round(0.55 * season_games)) if season_games else 20

    def metric_options(selected: str) -> str:
        return "".join(
            f'<option value="{esc(key)}"{" selected" if key == selected else ""}>{esc(label)}</option>'
            for key, label in SCATTER_METRICS
        )

    chart_card = f"""
    <section class="card">
      <div class="toolbar">
        <h2>Scatter</h2>
        <div class="chart-controls">
          <label class="select-label">X
            <select data-chart-axis="x">{metric_options("obpm")}</select>
          </label>
          <label class="select-label">Y
            <select data-chart-axis="y">{metric_options("dbpm")}</select>
          </label>
          <label class="select-label">Pos
            <select data-chart-pos>
              <option value="all">All</option>
              <option value="G">Guards</option>
              <option value="F">Forwards</option>
              <option value="C">Centers</option>
            </select>
          </label>
          <label class="select-label">Min MP/G
            <input type="number" data-chart-minmin value="0" min="0" max="48" step="2">
          </label>
          <label class="select-label">Min GP
            <input type="number" data-chart-mingp value="{chart_min_gp}" min="0" step="1">
          </label>
          <label class="select-label check-label">Labels
            <input type="checkbox" data-chart-labels checked>
          </label>
        </div>
      </div>
      <div class="chart-legend" data-chart-legend></div>
      <div class="chart-wrap">
        <canvas id="player-chart" data-player-chart height="460"></canvas>
        <div class="chart-tooltip" data-chart-tooltip hidden></div>
      </div>
      <p class="muted small-copy">Dot size tracks minutes · legend chips toggle teams · click a dot to open the player</p>
    </section>
    <script type="application/json" id="player-chart-data">{payload_json}</script>
    """

    body = f"""
    <section class="page-hero">
      <div>
        <h1>Players</h1>
        <p class="muted">{len(sorted_players)} rostered · {len(fa_players)} free agents · {len(prospects)} prospects · signings live in <a href="../free-agency.html">Free Agency</a></p>
      </div>
      <div>
        <a class="button-link compare-cta" href="../compare.html">⇄ Compare Players</a>
      </div>
    </section>
    {chart_card}
    <section class="card">
      <div class="toolbar">
        <input class="table-search" data-table-filter="players-index" placeholder="Filter players…" aria-label="Filter players">
        <div class="view-toggle group-toggle" data-group-toggle="players-index" role="group" aria-label="Player groups">
          <button type="button" class="active" data-group="roster">On teams</button>
          <button type="button" data-group="fa">Free agents</button>
          <button type="button" data-group="draft">Draft class</button>
        </div>
        <div class="view-toggle" data-view-toggle="players-index">
          <button type="button" class="active" data-view="basic">Per Game</button>
          <button type="button" data-view="p36">Per 36</button>
          <button type="button" data-view="adv">Advanced</button>
          <button type="button" data-view="rate">Ratings</button>
        </div>
      </div>
      {table_html(headers, rows, table_id="players-index", empty_message="No players found.", pos_filter=True)}
    </section>
    """
    return page_html("Players", body, teams, root="../", active="players")


def best_performances_card(data: dict[str, Any], teams: list[dict[str, Any]], season: int, root: str = "") -> str:
    teams_by_tid = {int(t.get("tid")): t for t in teams if t.get("tid") is not None}
    logs = build_game_logs(data, season)
    scored = []
    for pid, entries in logs.items():
        for entry in entries:
            box = entry.get("box") or {}
            if safe_float(box.get("min")) <= 0:
                continue
            fpts = fantasy_pts(box)
            if fpts is None:
                continue
            scored.append((fpts, pid, entry))
    if not scored:
        return ""
    scored.sort(key=lambda x: -x[0])
    rows = []
    for fpts, pid, entry in scored[:10]:
        player = ALL_PLAYERS_BY_PID.get(pid)
        box = entry["box"]
        trb = safe_float(box.get("orb")) + safe_float(box.get("drb"))
        line = f"{fmt_number(box.get('pts'), 0)} PTS · {fmt_number(trb, 0)} TRB · {fmt_number(box.get('ast'), 0)} AST"
        name_html = event_player_link(pid, ALL_PLAYERS_BY_PID, root) if player else esc(box.get("name", "—"))
        rows.append("".join([
            td(name_html, sort=player_name(player) if player else "", cls="name-cell"),
            td(f'<a href="{root}games/{esc(game_slug_from_gid(entry.get("gid")))}.html">Day {safe_int(entry.get("day"))} vs {esc(team_abbrev_for_tid(entry.get("opp_tid"), teams_by_tid))}</a>', sort=entry.get("day")),
            td(line, sort=safe_float(box.get("pts"))),
            td(fmt_number(int(round(fpts)), 0), sort=fpts, cls="lg-fpts-cell"),
        ]))
    return f"""
    <section class="card home-section">
      <div class="section-title-row"><h2>Best Performances · Season {season}</h2><span class="muted small-copy">by fantasy points</span></div>
      {table_html(["Player", "Game", "Line", "FPTS"], rows, table_id="best-perf", empty_message="No games yet.", wrap_cls="fit-table")}
    </section>
    """


def head_to_head_matrix(data: dict[str, Any], teams: list[dict[str, Any]], season: int) -> str:
    palette = team_palette_by_tid(teams)
    grid_teams = sorted(
        [team for team in teams if team.get("tid") is not None and not team.get("disabled")],
        key=lambda team: team_abbrev(team),
    )
    records: dict[tuple[int, int], list[int]] = defaultdict(lambda: [0, 0])
    for item in completed_game_items(data, season, playoffs=False):
        winner = game_winner_tid(item)
        if winner is None:
            continue
        home, away = safe_int(item.get("home_tid")), safe_int(item.get("away_tid"))
        loser = away if winner == home else home
        records[(winner, loser)][0] += 1
        records[(loser, winner)][1] += 1
    if not records:
        return ""

    header = "".join(
        f'<th data-tid="{esc(t.get("tid"))}">{team_dot(t.get("tid"), palette)}{esc(team_abbrev(t))}</th>'
        for t in grid_teams
    )
    rows = []
    for row_team in grid_teams:
        row_tid = safe_int(row_team.get("tid"))
        cells = [td(f'{team_dot(row_tid, palette)}{team_anchor(row_team)}', cls="name-cell")]
        for col_team in grid_teams:
            col_tid = safe_int(col_team.get("tid"))
            if row_tid == col_tid:
                cells.append(td("", cls="h2h-self"))
                continue
            won, lost = records.get((row_tid, col_tid), [0, 0])
            if won == 0 and lost == 0:
                cells.append(td('<span class="muted">—</span>'))
                continue
            frac = won / (won + lost)
            style = heat_style(frac, 0.0, 1.0, 1)
            cells.append(td(f"{won}-{lost}", sort=frac, style=style))
        rows.append(f'<tr data-tid="{row_tid}">{"".join(cells)}</tr>')

    return f"""
    <section class="card">
      <div class="section-title-row"><h2>Head-to-Head</h2><span class="muted small-copy">Season {season} · row team's record vs column team</span></div>
      <div class="table-wrap fit-table">
        <table id="h2h-grid" class="h2h-grid">
          <thead><tr><th>Team</th>{header}</tr></thead>
          <tbody>{''.join(rows)}</tbody>
        </table>
      </div>
    </section>
    """


def _game_projections(data: dict[str, Any], teams: list[dict[str, Any]], season: int, items: list[dict[str, Any]]) -> dict[str, tuple[float, float]]:
    """gid -> (p_home, projected home margin) for every unplayed scheduled game.

    Consumes simmodel.sim_client_inputs read-only, so the displayed numbers use
    the exact strengths/HCA/k the Monte Carlo sim applies inside win_prob
    (p_home = 1/(1+exp(-(sH-sA+HCA)*k)), HCA=+1.5 pts, k=0.16 — the P8 spec
    formula doubles as the fallback if the payload ever omits the constants).
    """
    if not any(not is_completed_game_item(item) for item in items):
        return {}
    try:
        sim = sim_client_inputs(data, teams, active_players(data), season)
        strengths = {safe_int(tid): safe_float(value) for tid, value in (sim.get("strengths") or {}).items()}
        hca = safe_float(sim.get("hca"), 1.5)
        k = safe_float(sim.get("logistic_k"), 0.16)
    except Exception:
        return {}
    if not strengths or k <= 0:
        return {}
    out: dict[str, tuple[float, float]] = {}
    for item in items:
        if is_completed_game_item(item):
            continue
        home, away = safe_int(item.get("home_tid"), -1), safe_int(item.get("away_tid"), -1)
        if home not in strengths or away not in strengths:
            continue
        margin = strengths[home] - strengths[away] + hca
        p_home = 1.0 / (1.0 + math.exp(-margin * k))
        out[str(item.get("gid"))] = (p_home, margin)
    return out


def _spread_label(team_margin: float) -> str:
    """Betting-style line from the team's own projected margin (favorite < 0)."""
    line = -team_margin
    if abs(line) < 0.05:
        line = 0.0
    return f"{line:+.1f}"


def render_schedule_page(data: dict[str, Any], teams: list[dict[str, Any]], schedule_season: int | None = None, schedule_days: int | None = None) -> str:
    teams_by_tid = {int(team.get("tid")): team for team in teams if team.get("tid") is not None}
    # Show only the upcoming season's schedule. In the offseason it has no games yet (we don't
    # synthesize one), so the page renders an empty state until a real schedule is exported.
    upcoming = schedule_season if schedule_season is not None else inferred_upcoming_schedule_season(data)
    items, _ = score_items_for_page(data, teams, schedule_season=schedule_season, schedule_days=schedule_days)
    items = [item for item in items if safe_int(item.get("season")) == upcoming]
    label = f"Season {upcoming} schedule"
    projections = _game_projections(data, teams, upcoming, items)
    grid_teams = sorted(
        [team for team in teams if team.get("tid") is not None and not team.get("disabled")],
        key=lambda team: team_abbrev(team),
    )
    days = sorted({safe_int(item.get("day"), 0) for item in items})
    by_day_tid: dict[tuple[int, int], list[dict[str, Any]]] = defaultdict(list)
    for item in items:
        for tid in (item.get("home_tid"), item.get("away_tid")):
            if tid is not None:
                by_day_tid[(safe_int(item.get("day")), safe_int(tid))].append(item)

    palette = team_palette_by_tid(teams)
    next_day = min(
        (safe_int(item.get("day")) for item in items if not is_completed_game_item(item)),
        default=None,
    )
    header_cells = [th("Day")] + [
        f'<th data-tid="{esc(team.get("tid"))}">{team_dot(team.get("tid"), palette)}{esc(team_abbrev(team))}</th>'
        for team in grid_teams
    ]
    rows: list[str] = []
    for day in days:
        cells = [td(fmt_number(day, 0), cls="day-label")]
        for team in grid_teams:
            tid = int(team.get("tid"))
            cell_items = by_day_tid.get((day, tid), [])
            if not cell_items:
                cells.append(td("", cls="off-day"))
                continue
            parts = []
            for item in cell_items:
                matchup = schedule_matchup_label(item, tid, teams_by_tid)
                cls = "sched-cell"
                result_html = ""
                title_attr = ""
                if is_completed_game_item(item):
                    result = team_schedule_result(item, tid)
                    cls += " sched-win" if result.startswith("W") else " sched-loss"
                    ot = game_ot_label(item)
                    if ot:
                        result = f"{result} {ot}"
                    result_html = f'<span class="sched-result">{esc(result)}</span>'
                else:
                    proj = projections.get(str(item.get("gid")))
                    if proj is not None:
                        p_home, home_margin = proj
                        is_home = safe_int(item.get("home_tid"), -1) == tid
                        p_team = p_home if is_home else 1.0 - p_home
                        team_margin = home_margin if is_home else -home_margin
                        spread = _spread_label(team_margin)
                        home_ab = team_abbrev_for_tid(item.get("home_tid"), teams_by_tid)
                        away_ab = team_abbrev_for_tid(item.get("away_tid"), teams_by_tid)
                        detail = (f"Projected: {home_ab} {fmt_number(100 * p_home, 1)}% · "
                                  f"{away_ab} {fmt_number(100 * (1.0 - p_home), 1)}% · "
                                  f"{home_ab if p_home >= 0.5 else away_ab} "
                                  f"{_spread_label(home_margin if p_home >= 0.5 else -home_margin)}")
                        title_attr = f' title="{esc(detail)}"'
                        cls += " sched-proj-cell"
                        fav_cls = " sched-fav" if p_team >= 0.5 else ""
                        result_html = (f'<span class="sched-proj{fav_cls}">{fmt_number(100 * p_team, 1)}%'
                                       f'<span class="sched-spread">{esc(spread)}</span></span>')
                parts.append(f'<a class="{cls}" href="{esc(game_url(item))}"{title_attr}>{matchup}{result_html}</a>')
            cells.append(td("".join(parts)))
        row_cls = ' class="next-day"' if next_day is not None and day == next_day else ""
        rows.append(f"<tr{row_cls}>" + "".join(cells) + "</tr>")

    if rows:
        table = f"""
        <div class="table-wrap schedule-grid-wrap">
          <table id="schedule-grid" class="schedule-grid">
            <thead><tr>{''.join(header_cells)}</tr></thead>
            <tbody>{''.join(rows)}</tbody>
          </table>
        </div>
        """
    else:
        table = f"""
        <div class="sched-empty">
          <p class="sched-empty-title">The {upcoming} schedule hasn't been released yet.</p>
          <p class="muted">Projected {upcoming} standings and title odds live on the <a href="index.html">home page</a>.</p>
        </div>
        """

    season_for_h2h = max((safe_int(item.get("season")) for item in items), default=upcoming)
    proj_bit = (' · <span title="Sim-model win probability and point spread for each team, '
                'including +1.5 home-court advantage">proj. win% &amp; spread</span>') if projections else ""
    hero_copy = (f'{esc(label)} · <strong>vs.</strong> home · <strong>@</strong> road · '
                 f'<span title="The highlighted row is the next game day">highlight = next day</span>{proj_bit}'
                 if rows else esc(label))
    body = f"""
    <section class="page-hero">
      <div>
        <h1>Schedule</h1>
        <p class="muted">{hero_copy}</p>
      </div>
    </section>
    {head_to_head_matrix(data, teams, season_for_h2h)}
    <section class="card">
      {table}
    </section>
    """
    return page_html("Schedule", body, teams, root="", active="schedule")


AWARD_DISPLAY = [
    ("mvp", "MVP"),
    ("dpoy", "Defensive POY"),
    ("smoy", "Sixth Man"),
    ("roy", "Rookie of the Year"),
    ("mip", "Most Improved"),
    ("finalsMvp", "Finals MVP"),
]


def award_winner_html(winner: dict[str, Any] | None, all_players_by_pid: dict[int, dict[str, Any]], teams_by_tid: dict[int, dict[str, Any]], root: str, led: dict[int, dict[str, float]] | None = None, season: int | None = None) -> str:
    if not isinstance(winner, dict) or winner.get("pid") is None:
        return '<span class="muted">—</span>'
    name = event_player_link(winner.get("pid"), all_players_by_pid, root, label=winner.get("name"))
    team = team_abbrev(teams_by_tid.get(safe_int(winner.get("tid"), -10)))
    leaders = (led or {}).get(season) or {} if season is not None else {}
    stats_bits = []
    for key, label in (("pts", "PTS"), ("trb", "TRB"), ("ast", "AST")):
        value = winner.get(key)
        if value is None:
            continue
        bit = esc(f"{fmt_number(value, 1)} {label}")
        lead = leaders.get(key)
        if lead is not None and abs(safe_float(value) - lead) <= 1e-6:
            bit = led_league_mark(bit, f"Led the league in {label} in {season}")
        stats_bits.append(bit)
    stat_text = f' <span class="muted small-copy">{esc(team)} · {" · ".join(stats_bits)}</span>' if stats_bits else f' <span class="muted small-copy">{esc(team)}</span>'
    return f"{name}{stat_text}"


def honors_html(award: dict[str, Any], all_players_by_pid: dict[int, dict[str, Any]], teams_by_tid: dict[int, dict[str, Any]], root: str) -> str:
    table_rows = []
    max_players = 0
    for key, title in (("allLeague", "All-League"), ("allDefensive", "All-Defensive")):
        groups = award.get(key)
        if not isinstance(groups, list) or not groups:
            continue
        if groups and isinstance(groups[0], dict) and "players" not in groups[0]:
            groups = [{"title": "", "players": groups}]
        if key == "allDefensive":
            groups = groups[:1]  # 1st team only
        for group in groups:
            if not isinstance(group, dict):
                continue
            members = [m for m in group.get("players") or [] if isinstance(m, dict)]
            if not members:
                continue
            group_title = group.get("title") or ""
            label = f"{title} {group_title}".strip()
            cells = [td(esc(label), cls="name-cell honor-label-cell")]
            for member in members:
                name = event_player_link(member.get("pid"), all_players_by_pid, root, label=member.get("name"))
                team = esc(team_abbrev(teams_by_tid.get(safe_int(member.get("tid"), -10))))
                cells.append(td(f'{name} <span class="muted small-copy">{team}</span>', cls="honor-cell"))
            max_players = max(max_players, len(members))
            table_rows.append(cells)
    if not table_rows:
        return ""
    rows = []
    for cells in table_rows:
        while len(cells) < max_players + 1:
            cells.append(td(""))
        rows.append("".join(cells))
    headers = ["Honor"] + [str(i) for i in range(1, max_players + 1)]
    header_html = "".join(th(label) for label in headers)
    body_html = "".join(f"<tr>{row}</tr>" for row in rows)
    return f"""
    <div class="table-wrap honors-table-wrap">
      <table class="honors-table">
        <thead><tr>{header_html}</tr></thead>
        <tbody>{body_html}</tbody>
      </table>
    </div>
    """


def playoff_bracket_html(ps: dict[str, Any], teams_by_tid: dict[int, dict[str, Any]], root: str) -> str:
    rounds = ps.get("series") or []
    if not rounds:
        return ""
    round_names = {1: ["Finals"], 2: ["Semifinals", "Finals"], 3: ["Quarterfinals", "Semifinals", "Finals"]}.get(len(rounds), [f"Round {i + 1}" for i in range(len(rounds))])
    cols = []
    for round_index, matchups in enumerate(rounds):
        cards = []
        for series in matchups:
            home, away = series.get("home") or {}, series.get("away") or {}
            home_won = safe_int(home.get("won"))
            away_won = safe_int(away.get("won"))
            winner_is_home = home_won > away_won
            def side(s, is_winner):
                team = teams_by_tid.get(safe_int(s.get("tid"), -10))
                label = f'({safe_int(s.get("seed"))}) {esc(team_abbrev(team))}'
                link = f'<a href="{team_url(team, root)}">{label}</a>' if team else label
                cls = "bracket-win" if is_winner else "bracket-loss"
                return f'<div class="{cls}"><span>{link}</span><strong>{safe_int(s.get("won"))}</strong></div>'
            cards.append(f'<div class="bracket-series">{side(home, winner_is_home)}{side(away, not winner_is_home)}</div>')
        cards_html = "".join(cards)
        cols.append(f'<div class="bracket-round"><h4>{esc(round_names[round_index])}</h4>{cards_html}</div>')
    return f'<div class="bracket">{"".join(cols)}</div>'


def past_season_leaders_html(data: dict[str, Any], season: int, all_players_by_pid: dict[int, dict[str, Any]], teams_by_tid: dict[int, dict[str, Any]], root: str, led: dict[int, dict[str, float]] | None = None) -> str:
    # Qualify on a share of the season, not a flat 20 games: that was 44% of a 45-game
    # year and would be 56% of a 36-game one.
    min_gp = max(5, round(0.45 * regular_season_length(data, season)))
    rows = []
    for player in data.get("players", []):
        stat = season_regular_stat(player, season)
        if stat_gp(stat) >= min_gp:
            rows.append((player, stat))
    if not rows:
        return ""
    categories = [
        ("PTS", "pts", lambda s: per_game(s, "pts")),
        ("TRB", "trb", lambda s: total_rebounds(s) / stat_gp(s) if stat_gp(s) else None),
        ("AST", "ast", lambda s: per_game(s, "ast")),
        ("PER", "per", lambda s: s.get("per")),
    ]
    leaders = (led or {}).get(season) or {}
    bits = []
    for label, led_key, fn in categories:
        scored = sorted(
            ((float(fn(s)), p) for p, s in rows if fn(s) is not None),
            key=lambda x: -x[0],
        )
        if not scored:
            continue
        value, player = scored[0]
        value_html = fmt_number(value, 1)
        lead = leaders.get(led_key)
        if lead is not None and abs(value - lead) <= 1e-6:
            value_html = led_league_mark(value_html, f"Led the league in {label} in {season}")
        bits.append(
            f'<span class="leader-inline"><strong>{esc(label)}</strong> '
            f'{event_player_link(player.get("pid"), all_players_by_pid, root)} {value_html}</span>'
        )
    return f'<div class="leaders-inline">{"".join(bits)}</div>'


def prospect_row(player: dict[str, Any], season: int, draft_year: int, rating_ranges: dict[str, tuple[float, float]], root: str = "") -> str:
    # Age is the prospect's age in the class he comes out in, not today's. The export
    # stamps a future prospect's ratings and height at his draft season, so an age
    # measured from `season` contradicts every other cell on the row -- the 2013 class
    # off the 2004 export lists ten-year-olds standing 6'6" with NBA overalls.
    born = (player.get("born") or {}).get("year")
    rating = latest_rating(player, season + 1) or latest_rating(player)
    cells = [
        td(f'<a class="player-link" href="{player_url(player, root)}">{esc(player_name(player))}</a>', sort=player_name(player), cls="name-cell"),
        td(esc(rating.get("pos", "—")), sort=rating.get("pos", "")),
        td(age(player, draft_year), sort=(draft_year - born if isinstance(born, int) else None)),
        td(fmt_height(player.get("hgt")), sort=player.get("hgt")),
        td(esc(rating.get("ovr", "—")), sort=rating.get("ovr")),
        td(esc(rating.get("pot", "—")), sort=rating.get("pot"), style=heat_style(rating.get("pot"), *rating_ranges.get("pot", (0, 0)), 1)),
    ]
    for key, _ in TEAM_RATING_RANK_KEYS:
        value = rating.get(key)
        lo, hi = rating_ranges.get(key, (0.0, 0.0))
        cls = "group-start" if key in RATING_GROUP_STARTS else ""
        cells.append(td(esc(value if value is not None else "—"), sort=value, style=heat_style(value, lo, hi, 1), cls=cls))
    return "".join(cells)


def _odds_pct(pct: float) -> str:
    """One-decimal percentage with the site's <0.1% / — conventions (input 0-100)."""
    if pct >= 0.05:
        return fmt_number(pct, 1) + "%"
    if pct > 0:
        return "&lt;0.1%"
    return "—"


def projected_lottery_html(data: dict[str, Any], teams: list[dict[str, Any]], season: int, draft_year: int) -> str:
    palette = team_palette_by_tid(teams)
    teams_by_tid = {int(t.get("tid")): t for t in teams if t.get("tid") is not None}
    active = active_teams_for_season(teams, season)
    order = standings_order(active, season)
    # Simulated slot odds apply only to the upcoming draft (this season's finish).
    slot_odds: dict[int, tuple[float, float]] = {}
    if draft_year == season:
        sim = league_sim(data, teams, season)
        n = len(order)
        for tid, o in (sim.get("teams") or {}).items():
            seeds = o.get("seeds") or []
            if len(seeds) == n:
                p1 = seeds[n - 1]
                top3 = sum(seeds[n - 3:])
                slot_odds[tid] = (100 * p1, 100 * top3)

    # Before any games are played every team is 0-0, so standings_order falls back to an
    # arbitrary tiebreak and the slot column ends up contradicting the odds column beside
    # it (measured in preseason: the team slotted 2nd held the league's *lowest* #1 odds).
    # With no results to reverse, the projection the page actually believes is the sim, so
    # order by it instead -- worst projected team picks first.
    # `order` runs best team first (reverse_order below is the pick order), and the best
    # team is the one least likely to land the #1 slot -- so sort ascending by those odds.
    if slot_odds and not any(safe_int((latest_team_season(t, season) or {}).get("gp")) for t in active):
        order = sorted(order, key=lambda tid: slot_odds.get(tid, (0.0, 0.0))[0])
    reverse_order = list(reversed(order))
    picks = [dp for dp in data.get("draftPicks", []) if isinstance(dp, dict) and dp.get("season") == draft_year]
    owner_by_slot: dict[tuple[int, int], int] = {}
    for dp in picks:
        owner_by_slot[(safe_int(dp.get("round")), safe_int(dp.get("originalTid"), -10))] = safe_int(dp.get("tid"), -10)
    rounds = sorted({safe_int(dp.get("round")) for dp in picks}) or [1, 2]
    rows = []
    pick_no = 0
    for rnd in rounds:
        for slot_tid in reverse_order:
            pick_no += 1
            slot_team = teams_by_tid.get(slot_tid, {})
            owner_tid = owner_by_slot.get((rnd, slot_tid), slot_tid)
            owner_team = teams_by_tid.get(owner_tid, {})
            team_season = latest_team_season(slot_team, season)
            record = fmt_record(team_season.get("won"), team_season.get("lost"))
            if owner_tid == slot_tid:
                owner_html = f'{team_dot(owner_tid, palette)}{team_anchor(owner_team)}'
            else:
                owner_html = (
                    f'{team_dot(owner_tid, palette)}{team_anchor(owner_team)} '
                    f'<span class="badge badge-good" title="Acquired via trade">via {esc(team_abbrev(slot_team))}</span>'
                )
            cells = [
                td(pick_no, sort=pick_no),
                td(f'{team_dot(slot_tid, palette)}{team_anchor(slot_team)} <span class="muted small-copy">({esc(record)})</span>', sort=team_full_name(slot_team), cls="name-cell"),
                td(owner_html, sort=team_full_name(owner_team), cls="name-cell"),
            ]
            if slot_odds:
                p1, top3 = slot_odds.get(slot_tid, (0.0, 0.0))
                cells.append(td(_odds_pct(p1), sort=p1, style=seed_cell_style(p1)))
                cells.append(td(_odds_pct(top3), sort=top3, style=seed_cell_style(top3)))
            rows.append(f'<tr data-tid="{owner_tid}">{"".join(cells)}</tr>')
    if not rows:
        return ""
    headers = ["Pick", "Slot (record)", "Owned by"]
    note = "reverse of current standings · green badge = traded pick"
    if slot_odds:
        headers += ["#1 slot %", "Top-3 %"]
        note = "reverse of current standings · simulated slot odds · green badge = traded pick"
    return f"""
    <section class="card home-section">
      <div class="section-title-row"><h2>Projected Draft Order</h2><span class="muted small-copy">{note}</span></div>
      {table_html(headers, rows, table_id=f"lottery-{draft_year}", empty_message="No draft picks found.", wrap_cls="fit-table")}
    </section>
    """


def draft_class_panel(data: dict[str, Any], teams: list[dict[str, Any]], season: int, draft_year: int, class_prospects: list[dict[str, Any]], hidden: bool) -> str:
    sorted_prospects = sorted(
        class_prospects,
        key=lambda p: (-safe_int(latest_rating(p).get("pot")), -safe_int(latest_rating(p).get("ovr")), player_name(p)),
    )
    rating_ranges: dict[str, tuple[float, float]] = {}
    for key in [k for k, _ in TEAM_RATING_RANK_KEYS] + ["pot"]:
        values = []
        for p in sorted_prospects:
            value = latest_rating(p).get(key)
            if value is not None and math.isfinite(safe_float(value, float("nan"))):
                values.append(float(value))
        rating_ranges[key] = (min(values), max(values)) if values else (0.0, 0.0)

    headers: list = ["Name", "Pos", "Age", "Ht", "Ovr", "Pot"]
    for key, label in TEAM_RATING_RANK_KEYS:
        headers.append((label, "group-start" if key in RATING_GROUP_STARTS else ""))
    rows = [prospect_row(p, season, draft_year, rating_ranges) for p in sorted_prospects]
    table_id = f"prospects-{draft_year}"
    hidden_attr = " hidden" if hidden else ""

    # Both overview cards slot prospects into picks derived from the current standings,
    # which only describe how *this* season finishes. The export carries classes out to
    # season + 9; a 2013 lottery ordered by a 2004 table is invented, not projected, so
    # the far classes are the prospect list and an honest note about why.
    overview = ""
    note = ""
    if draft_year <= season:
        overview = f"""
      <div class="draft-overview-row">
        {projected_lottery_html(data, teams, season, draft_year)}
        {mock_draft_card(data, teams, season, draft_year, class_prospects)}
      </div>"""
    else:
        away = draft_year - season
        note = (f'<span class="muted small-copy">'
                f'{"next year’s class" if away == 1 else f"{away} drafts out"}'
                f' · no standings yet to slot a board from</span>')
    return f"""
    <div id="draft-panel-{draft_year}" role="tabpanel" aria-labelledby="draft-tab-{draft_year}" data-draft-panel="{draft_year}"{hidden_attr}>{overview}
      <section class="card">
        <div class="section-title-row draft-class-title-row"><h2>Class of {draft_year}</h2>
          <span class="draft-class-meta">{note}<span class="count-pill">{len(sorted_prospects)} prospects</span></span></div>
        <div class="toolbar">
          <input class="table-search" data-table-filter="{table_id}" placeholder="Filter prospects…" aria-label="Filter prospects">
        </div>
        {table_html(headers, rows, table_id=table_id, empty_message="No prospects in this class.")}
      </section>
    </div>
    """


def mock_draft_card(data: dict[str, Any], teams: list[dict[str, Any]], season: int, draft_year: int, class_prospects: list[dict[str, Any]]) -> str:
    palette = team_palette_by_tid(teams)
    teams_by_tid = {int(t.get("tid")): t for t in teams if t.get("tid") is not None}
    order = list(reversed(standings_order(active_teams_for_season(teams, season), season)))
    picks = [dp for dp in data.get("draftPicks", []) if isinstance(dp, dict) and dp.get("season") == draft_year and safe_int(dp.get("round")) == 1]
    owner_by_slot = {safe_int(dp.get("originalTid"), -10): safe_int(dp.get("tid"), -10) for dp in picks}
    board = sorted(
        class_prospects,
        key=lambda p: (-safe_int(latest_rating(p).get("pot")), -safe_int(latest_rating(p).get("ovr")), player_name(p)),
    )
    if not board or not order:
        return ""
    rows = []
    for pick_no, slot_tid in enumerate(order, 1):
        if pick_no > len(board):
            break
        prospect = board[pick_no - 1]
        rating = latest_rating(prospect)
        owner_tid = owner_by_slot.get(slot_tid, slot_tid)
        owner_team = teams_by_tid.get(owner_tid, {})
        via = "" if owner_tid == slot_tid else f' <span class="muted small-copy">via {esc(team_abbrev(teams_by_tid.get(slot_tid)))}</span>'
        rows.append(f'<tr data-tid="{owner_tid}">' + "".join([
            td(pick_no, sort=pick_no),
            td(f'{team_dot(owner_tid, palette)}{team_anchor(owner_team)}{via}', sort=team_full_name(owner_team), cls="name-cell"),
            td(f'<a class="player-link" href="{player_url(prospect)}">{esc(player_name(prospect))}</a>', sort=player_name(prospect), cls="name-cell"),
            td(esc(rating.get("pos", "—")), sort=rating.get("pos", "")),
            td(esc(rating.get("ovr", "—")), sort=rating.get("ovr")),
            td(esc(rating.get("pot", "—")), sort=rating.get("pot")),
        ]) + "</tr>")
    return f"""
    <section class="card home-section">
      <div class="section-title-row"><h2>Mock Draft</h2><span class="muted small-copy">best available by potential at each projected slot</span></div>
      {table_html(["Pick", "Team", "Prospect", "Pos", "Ovr", "Pot"], rows, table_id=f"mock-{draft_year}", empty_message="No prospects.", wrap_cls="fit-table")}
    </section>
    """


def _regrade_note(pick: int, rank: int | None, tot: dict[str, Any], class_matured: bool) -> tuple[str, str] | None:
    """Factual steal/bust callout from pick number vs career-WS rank, or None.

    Steals need real production (30+ games, top-3 class value); busts need a
    high pick and a class that has had at least two seasons to prove out.
    """
    if rank is not None:
        if pick - rank >= 4 and rank <= 3 and tot["gp"] >= 30:
            return ("badge-good", f"{ordinal(rank)} in class by career WS, picked {ordinal(pick)}")
        if class_matured and rank - pick >= 4 and pick <= 5:
            return ("badge-bad", f"Picked {ordinal(pick)}, {ordinal(rank)} in class by career WS")
    elif class_matured and pick <= 5 and tot["gp"] <= 0:
        return ("badge-bad", f"Picked {ordinal(pick)}, yet to play a league game")
    return None


def draft_regrades_section(data: dict[str, Any], teams: list[dict[str, Any]], season: int) -> str:
    """Per-class draft recaps: what every past pick became, re-graded by career WS."""
    teams_by_tid = {int(t.get("tid")): t for t in teams if t.get("tid") is not None}
    palette = team_palette_by_tid(teams)
    all_players_by_pid = {safe_int(p.get("pid")): p for p in data.get("players", []) if p.get("pid") is not None}
    honors = player_honors_index(data)
    latest_completed = max(champions_by_season(data), default=season - 1)

    classes: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for p in data.get("players", []):
        d = p.get("draft") or {}
        year = d.get("year")
        if (isinstance(year, int) and year <= latest_completed
                and safe_int(d.get("round")) >= 1 and safe_int(d.get("tid"), -1) >= 0):
            classes[year].append(p)
    class_years = sorted(classes, reverse=True)
    if not class_years:
        return ""

    panels = []
    tabs = []
    for i, year in enumerate(class_years):
        picks = sorted(classes[year], key=lambda p: (safe_int((p.get("draft") or {}).get("round")),
                                                     safe_int((p.get("draft") or {}).get("pick")),
                                                     player_name(p)))
        totals = {safe_int(p.get("pid")): career_regular_totals(p) for p in picks}
        ranked = sorted((p for p in picks if totals[safe_int(p.get("pid"))]["gp"] > 0),
                        key=lambda p: (-totals[safe_int(p.get("pid"))]["ws"], player_name(p)))
        ws_rank = {safe_int(p.get("pid")): r for r, p in enumerate(ranked, 1)}
        class_matured = year + 2 <= latest_completed
        class_played = bool(ranked)

        rows = []
        for overall, p in enumerate(picks, 1):
            pid = safe_int(p.get("pid"))
            d = p.get("draft") or {}
            tot = totals[pid]
            rank = ws_rank.get(pid)
            draft_tid = safe_int(d.get("tid"), -1)
            orig_tid = safe_int(d.get("originalTid"), draft_tid)
            drafted_by = f'{team_dot(draft_tid, palette)}{team_anchor(teams_by_tid.get(draft_tid, {}))}'
            if orig_tid != draft_tid:
                drafted_by += f' <span class="muted small-copy">via {esc(team_abbrev_for_tid(orig_tid, teams_by_tid))}</span>'
            cur_tid = safe_int(p.get("tid"), RETIRED_TID if p.get("retiredYear") is not None else -9)
            if p.get("retiredYear") is not None:
                now_html, now_sort = '<span class="muted">Retired</span>', "zz-retired"
            elif cur_tid == FREE_AGENT_TID:
                now_html, now_sort = '<a href="free-agency.html">FA</a>', "z-fa"
            elif cur_tid >= 0:
                now_html = team_label(cur_tid, teams_by_tid)
                now_sort = team_abbrev_for_tid(cur_tid, teams_by_tid)
                if cur_tid == draft_tid:
                    now_html += ' <span class="badge badge-good regrade-still" title="Still with the team that drafted him">still</span>'
            else:
                now_html, now_sort = '<span class="muted">—</span>', "zz"
            note = _regrade_note(overall, rank, tot, class_matured)
            note_html = f'<span class="badge {note[0]}">{esc(note[1])}</span>' if note else ""
            rating = latest_rating(p)
            rows.append("".join([
                td(f'{overall} <span class="muted small-copy">R{safe_int(d.get("round"))}</span>', sort=overall),
                td(event_player_link(pid, all_players_by_pid, "", label=player_name(p)), sort=player_name(p), cls="name-cell"),
                td(esc(rating.get("pos", "—")), sort=rating.get("pos", "")),
                td(drafted_by, sort=team_abbrev_for_tid(draft_tid, teams_by_tid), cls="name-cell"),
                td(now_html, sort=now_sort),
                td(fmt_number(tot["gp"], 0), sort=tot["gp"], cls="group-start"),
                td(fmt_number(tot["ppg"], 1) if tot["ppg"] is not None else "—", sort=tot["ppg"]),
                td(fmt_number(tot["ws"], 1), sort=tot["ws"]),
                td(fmt_number(tot["ewa"], 1), sort=tot["ewa"]),
                td(honor_chips_html(honors.get(pid, [])), sort=len(honors.get(pid, [])), cls="group-start"),
                td(note_html, sort=(overall - rank) if rank is not None else None),
            ]))

        if class_played:
            note_copy = f"re-graded by career regular-season Win Shares · through {latest_completed}"
        else:
            note_copy = f"class debuts in {year + 1} · nothing to re-grade yet"
        headers = ["Pick", "Player", "Pos", "Drafted by", "Now", ("GP", "group-start"), "PPG", "WS", "EWA",
                   ("Honors", "group-start"), "Note"]
        table_id = f"regrade-{year}"
        panels.append(f"""
      <div id="panel-regrade-{year}" role="tabpanel" aria-labelledby="tab-regrade-{year}" data-tab-panel{"" if i == 0 else " hidden"}>
        <div class="section-title-row"><h3 class="regrade-class-title">Class of {year}</h3><span class="muted small-copy">{esc(note_copy)}</span></div>
        {table_html(headers, rows, table_id=table_id, empty_message="No picks recorded.", caption=f"{year} draft class re-grade")}
      </div>""")
        tabs.append(
            f'<button type="button" class="{"active" if i == 0 else ""}" role="tab" id="tab-regrade-{year}" '
            f'aria-controls="panel-regrade-{year}" aria-selected="{"true" if i == 0 else "false"}" '
            f'tabindex="{"0" if i == 0 else "-1"}" data-tab-target="panel-regrade-{year}">{year}</button>'
        )

    return f"""
    <section class="card regrade-card">
      <div class="section-title-row"><h2>Draft Re-Grades</h2><span class="muted small-copy" title="Steal and bust calls compare draft slot with career Win Shares">every past pick, re-graded by career Win Shares</span></div>
      <div class="tabs" role="tablist" aria-label="Past draft classes" data-tabs>
        {''.join(tabs)}
      </div>
      {''.join(panels)}
    </section>
    """


def render_draft_page(data: dict[str, Any], teams: list[dict[str, Any]], season: int) -> str:
    prospects = draft_prospects(data)
    by_year: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for p in prospects:
        year = (p.get("draft") or {}).get("year")
        if isinstance(year, int):
            by_year[year].append(p)
    draft_years = sorted(by_year)
    if not draft_years:
        draft_years = [season]
    tabs = "".join(
        f'<button type="button" id="draft-tab-{year}" role="tab" aria-controls="draft-panel-{year}" aria-selected="{"true" if i == 0 else "false"}" class="{"active" if i == 0 else ""}" data-draft-tab="{year}">{year}</button>'
        for i, year in enumerate(draft_years)
    )
    panels = "".join(
        draft_class_panel(data, teams, season, year, by_year.get(year, []), hidden=(i != 0))
        for i, year in enumerate(draft_years)
    )
    span = str(draft_years[0]) if len(draft_years) == 1 else f"{draft_years[0]}–{draft_years[-1]}"
    hero_note = f"{len(draft_years)} classes, {span} · each sorted by potential"
    if draft_years[-1] > season:
        hero_note += f" · pick slots come from current standings, so the board is drawn for the {season} draft only"
    body = f"""
    <section class="page-hero">
      <div>
        <h1>Draft</h1>
        <p class="muted">{esc(hero_note)}</p>
      </div>
      <div class="view-toggle draft-tabs" role="tablist" aria-label="Draft classes" data-draft-tabs>{tabs}</div>
    </section>
    {panels}
    {draft_regrades_section(data, teams, season)}
    """
    return page_html("Draft", body, teams, root="", active="draft")


# event type -> (filter key, badge label, badge class). Draft events get their own
# badge locally (core's EVENT_BADGES predates the draft filter).
_TX_TYPES = {
    "freeAgent": "sign",
    "reSigned": "sign",
    "release": "waive",
    "trade": "trade",
    "draft": "draft",
}

_TX_FILTER_BUTTONS = [
    ("all", "All"),
    ("sign", "Signings"),
    ("trade", "Trades"),
    ("waive", "Waivers"),
    ("draft", "Draft"),
]


def transactions_archive_html(data: dict[str, Any], teams: list[dict[str, Any]]) -> str:
    teams_by_tid = {int(t.get("tid")): t for t in teams if t.get("tid") is not None}
    all_players_by_pid = {safe_int(p.get("pid")): p for p in data.get("players", []) if p.get("pid") is not None}
    # The inaugural fantasy draft only seeded rosters — a pick per roster spot, league-wide —
    # so it is archive noise. A rookie draft is two rounds, which separates the two without
    # hardcoding the season they happen to share.
    draft_counts: dict[int, int] = defaultdict(int)
    for event in data.get("events", []):
        if event.get("type") == "draft" and isinstance(event.get("season"), int):
            draft_counts[event["season"]] += 1
    seeding_seasons = {yr for yr, count in draft_counts.items() if count > 2 * len(teams_by_tid)}
    by_season: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for event in data.get("events", []):
        if event.get("type") not in _TX_TYPES or not isinstance(event.get("season"), int):
            continue
        if event.get("type") == "draft" and event["season"] in seeding_seasons:
            continue
        by_season[event["season"]].append(event)
    if not by_season:
        return ""
    season_blocks = []
    for season in sorted(by_season, reverse=True):
        events = sorted(by_season[season], key=lambda e: -safe_int(e.get("eid")))
        items = []
        for event in events:
            html_text = compose_event_html(event, all_players_by_pid, teams_by_tid, season, set(), "")
            if not html_text:
                continue
            etype = event.get("type")
            label, badge_cls = EVENT_BADGES.get(etype, ("DRAFT", "badge-accent") if etype == "draft" else ("NEWS", "badge-muted"))
            tids = ",".join(str(safe_int(t)) for t in (event.get("tids") or []) if t is not None)
            items.append(
                f'<li data-tx-type="{esc(_TX_TYPES.get(etype, "other"))}" data-tx-tids=",{esc(tids)},">'
                f'<span class="badge {badge_cls}">{esc(label)}</span><span>{html_text}</span></li>'
            )
        if not items:
            continue
        open_attr = " open" if season == max(by_season) else ""
        season_blocks.append(
            f'<details class="tx-season"{open_attr}><summary>Season {season} '
            f'<span class="count-pill" data-tx-count="{len(items)}">{len(items)} moves</span></summary>'
            f'<ul class="news-list">{"".join(items)}</ul></details>'
        )
    type_buttons = "".join(
        f'<button type="button" class="{"active" if value == "all" else ""}" '
        f'data-tx-type="{value}" aria-pressed="{"true" if value == "all" else "false"}">{esc(label)}</button>'
        for value, label in _TX_FILTER_BUTTONS
    )
    team_options = ['<option value="all">All teams</option>'] + [
        f'<option value="{safe_int(t.get("tid"))}">{esc(team_abbrev(t))}</option>'
        for t in sorted(teams, key=team_abbrev)
        if t.get("tid") is not None and not t.get("disabled")
    ]
    return f"""
    <section class="card home-section" data-txlog>
      <div class="section-title-row"><h2>Transaction Log</h2><span class="muted small-copy">every signing, trade, waiver, and draft pick on record</span></div>
      <div class="toolbar txlog-toolbar">
        <div class="view-toggle" data-tx-type-filter role="group" aria-label="Filter transactions by type">{type_buttons}</div>
        <label class="select-label">Team
          <select data-tx-team-filter aria-label="Filter transactions by team">{''.join(team_options)}</select>
        </label>
      </div>
      {''.join(season_blocks)}
    </section>
    """


def render_history_page(data: dict[str, Any], teams: list[dict[str, Any]]) -> str:
    teams_by_tid = {int(t.get("tid")): t for t in teams if t.get("tid") is not None}
    all_players_by_pid = {safe_int(p.get("pid")): p for p in data.get("players", []) if p.get("pid") is not None}
    awards_by_season = {a.get("season"): a for a in data.get("awards", []) if isinstance(a, dict)}
    playoffs_by_season = {ps.get("season"): ps for ps in data.get("playoffSeries", []) if isinstance(ps, dict)}
    seasons = sorted(set(awards_by_season) | set(playoffs_by_season), reverse=True)
    led = led_league(data)

    # summary table
    summary_rows = []
    for season in seasons:
        ps = playoffs_by_season.get(season) or {}
        champion = runner_up = None
        rounds = ps.get("series") or []
        if rounds:
            final = rounds[-1][0] if rounds[-1] else {}
            home, away = final.get("home") or {}, final.get("away") or {}
            if home and away:
                champion = home if safe_int(home.get("won")) > safe_int(away.get("won")) else away
                runner_up = away if champion is home else home
        award = awards_by_season.get(season) or {}
        def team_cell(side):
            if not side:
                return '<span class="muted">—</span>'
            team = teams_by_tid.get(safe_int(side.get("tid"), -10))
            return f'{team_anchor(team)}' if team else "—"
        summary_rows.append("".join([
            td(f'<a href="#season-{esc(season)}">{esc(season)}</a>', sort=season),
            td(team_cell(champion), cls="name-cell"),
            td(team_cell(runner_up)),
            td(award_winner_html(award.get("finalsMvp"), all_players_by_pid, teams_by_tid, ""), cls="name-cell"),
            td(award_winner_html(award.get("mvp"), all_players_by_pid, teams_by_tid, "", led=led, season=season), cls="name-cell"),
        ]))

    season_cards = []
    for season in seasons:
        award = awards_by_season.get(season) or {}
        ps = playoffs_by_season.get(season)
        award_rows = "".join(
            f'<div class="detail-item"><span>{esc(label)}</span><strong>{award_winner_html(award.get(key), all_players_by_pid, teams_by_tid, "", led=led, season=season)}</strong></div>'
            for key, label in AWARD_DISPLAY if award.get(key)
        )
        bracket = playoff_bracket_html(ps, teams_by_tid, "") if ps else ""
        leaders = past_season_leaders_html(data, season, all_players_by_pid, teams_by_tid, "", led=led)
        honors = honors_html(award, all_players_by_pid, teams_by_tid, "")
        season_cards.append(f"""
        <section class="card home-section" id="season-{season}">
          <div class="section-title-row"><h2>Season {season}</h2></div>
          {bracket}
          {leaders}
          <div class="details-grid history-awards">{award_rows}</div>
          {honors}
        </section>
        """)

    body = f"""
    <section class="page-hero">
      <div>
        <h1>League History</h1>
        <p class="muted">Champions, awards, and brackets · <span class="led-league" title="Gold marks a stat that led the league that season">gold ★</span> = led the league</p>
      </div>
    </section>
    {rafters_strip_html(data, teams)}
    <section class="card home-section">
      <div class="section-title-row"><h2>Champions</h2></div>
      {table_html(["Season", "Champion", "Runner-up", "Finals MVP", "MVP"], summary_rows, table_id="champions", empty_message="No completed seasons yet.")}
    </section>
    {''.join(season_cards)}
    {transactions_archive_html(data, teams)}
    """
    return page_html("History", body, teams, root="", active="history")


def all_time_leaders_html(data: dict[str, Any], teams: list[dict[str, Any]], root: str = "", start_season: int | None = None) -> str:
    start_season = start_season if start_season is not None else league_start_season(data)
    all_players_by_pid = {safe_int(p.get("pid")): p for p in data.get("players", []) if p.get("pid") is not None}
    totals = []
    for player in data.get("players", []):
        rows = [
            s for s in player.get("stats", [])
            if isinstance(s, dict) and not s.get("playoffs") and safe_int(s.get("season")) >= start_season
        ]
        if not rows:
            continue
        combined = combine_stat_rows(rows)
        if stat_gp(combined) <= 0:
            continue
        totals.append((player, combined))
    if not totals:
        return ""

    def box(title, value_fn, digits=0, per_game=False, min_gp=0):
        scored = []
        for player, stat in totals:
            gp = stat_gp(stat)
            if gp < min_gp:
                continue
            value = value_fn(stat)
            if value is None:
                continue
            value = float(value)
            if per_game:
                if gp <= 0:
                    continue
                value = value / gp
            scored.append((value, player))
        scored.sort(key=lambda x: (-x[0], player_name(x[1])))
        rows = []
        for rank, (value, player) in enumerate(scored[:10], 1):
            retired = player.get("retiredYear") is not None
            name = event_player_link(player.get("pid"), all_players_by_pid, root)
            tag = ' <span class="muted small-copy">(ret.)</span>' if retired else ""
            rows.append(
                f'<li><span class="leader-rank">{rank}</span><span>{name}{tag}</span>'
                f'<span class="leader-value">{fmt_number(value, digits)}</span></li>'
            )
        return f'<div class="leader-box"><h3>{esc(title)}</h3><ol class="leader-list">{"".join(rows)}</ol></div>'

    categories = [
        ("Points", lambda s: s.get("pts")),
        ("Rebounds", lambda s: total_rebounds(s)),
        ("Assists", lambda s: s.get("ast")),
        ("Steals", lambda s: s.get("stl")),
        ("Blocks", lambda s: s.get("blk")),
    ]
    # Per-game boards re-rank with a modest floor so short cameos don't lead. The floor is a
    # share of one season, not a literal: a flat 40 can never be reached in a 36-game year.
    pg_min_gp = max(5, round(0.6 * regular_season_length(data, current_season(data))))
    totals_boxes = "".join(box(f"Career {label}", fn) for label, fn in categories)
    pg_boxes = "".join(box(f"{label} Per Game", fn, digits=1, per_game=True, min_gp=pg_min_gp) for label, fn in categories)
    return f"""
    <section class="card home-section">
      <div class="toolbar">
        <div class="section-title-row"><h2>All-Time Leaders</h2><span class="muted small-copy">regular season since {start_season}, including retired players</span></div>
        <div class="view-toggle" data-leaders-toggle role="group" aria-label="Leader boards as totals or per game">
          <button type="button" class="active" data-leaders-view="totals" aria-pressed="true">Totals</button>
          <button type="button" data-leaders-view="pg" aria-pressed="false">Per Game</button>
        </div>
      </div>
      <div class="leader-grid" data-leaders-panel="totals">{totals_boxes}</div>
      <div class="leader-grid" data-leaders-panel="pg" hidden>{pg_boxes}</div>
      <p class="muted small-copy" data-leaders-panel="pg" hidden>Per-game boards require at least {pg_min_gp} career games.</p>
    </section>
    """


def feat_badges(stats: dict[str, Any]) -> list[str]:
    badges = []
    pts = safe_int(stats.get("pts"))
    if pts >= 60:
        badges.append(f"{pts}-point game")
    elif pts >= 50:
        badges.append("50+ points")
    if safe_int(stats.get("fxf")):
        badges.append("5x5")
    if safe_int(stats.get("qd")):
        badges.append("Quadruple-double")
    elif safe_int(stats.get("td")):
        badges.append("Triple-double")
    trb = safe_int(stats.get("orb")) + safe_int(stats.get("drb"))
    if trb >= 25:
        badges.append(f"{trb} rebounds")
    if safe_int(stats.get("ast")) >= 20:
        badges.append(f"{stats.get('ast')} assists")
    if safe_int(stats.get("tp")) >= 10:
        badges.append(f"{stats.get('tp')} threes")
    if safe_int(stats.get("blk")) >= 10:
        badges.append(f"{stats.get('blk')} blocks")
    if safe_int(stats.get("stl")) >= 10:
        badges.append(f"{stats.get('stl')} steals")
    return badges or ["Feat"]


def feat_rank(stats: dict[str, Any]) -> int:
    """Sort priority for a single-game feat, so the feats table groups by feat type."""
    pts = safe_int(stats.get("pts"))
    trb = safe_int(stats.get("orb")) + safe_int(stats.get("drb"))
    if safe_int(stats.get("qd")):         return 0   # quadruple-double
    if safe_int(stats.get("td")):         return 1   # triple-double
    if safe_int(stats.get("fxf")):        return 2   # 5x5
    if pts >= 60:                         return 3
    if pts >= 50:                         return 4
    if trb >= 25:                         return 5
    if safe_int(stats.get("ast")) >= 20:  return 6
    if safe_int(stats.get("tp")) >= 10:   return 7
    if safe_int(stats.get("blk")) >= 10:  return 8
    if safe_int(stats.get("stl")) >= 10:  return 9
    return 10


def render_records_page(data: dict[str, Any], teams: list[dict[str, Any]], season: int, start_season: int | None = None) -> str:
    start_season = start_season if start_season is not None else league_start_season(data)
    teams_by_tid = {int(t.get("tid")): t for t in teams if t.get("tid") is not None}
    all_players_by_pid = {safe_int(p.get("pid")): p for p in data.get("players", []) if p.get("pid") is not None}
    current_gids = {str(g.get("gid")) for g in data.get("games", []) if g.get("season") == season}
    led = led_league(data)
    feats = [f for f in data.get("playerFeats", []) if isinstance(f, dict)]
    feats.sort(key=lambda f: (feat_rank(f.get("stats") or {}), -safe_int((f.get("stats") or {}).get("pts")), -safe_int(f.get("season"))))
    # No Season column: the feats tables live inside per-season tabs already.
    headers = ["Player", "Team", "Opp", "Result", "Line", "FPTS", "Feat"]

    def feat_row(feat: dict[str, Any]) -> str:
        stats = feat.get("stats") or {}
        feat_season = safe_int(feat.get("season"))
        leaders = led.get(feat_season) or {}
        trb = safe_int(stats.get("orb")) + safe_int(stats.get("drb"))
        badges = " ".join(f'<span class="badge badge-accent">{esc(b)}</span>' for b in feat_badges(stats))
        result_text = f"{esc(feat.get('result', ''))} {esc(feat.get('score', ''))}"
        if str(feat.get("gid")) in current_gids and feat_season == season:
            result_text = f'<a href="games/{esc(game_slug_from_gid(feat.get("gid")))}.html">{result_text}</a>'
        line_bits = []
        for value, max_key, label in ((safe_int(stats.get("pts")), "ptsMax", "PTS"), (trb, "trbMax", "TRB"),
                                      (safe_int(stats.get("ast")), "astMax", "AST"), (safe_int(stats.get("stl")), "stlMax", "STL"),
                                      (safe_int(stats.get("blk")), "blkMax", "BLK")):
            bit = f"{value} {label}"
            lead = leaders.get(max_key)
            if lead is not None and abs(value - lead) <= 1e-6:
                bit = led_league_mark(bit, f"Best single-game {label} total of {feat_season}")
            line_bits.append(bit)
        fpts = fantasy_pts(stats)
        return "".join([
            td(event_player_link(feat.get("pid"), all_players_by_pid, "", label=feat.get("name")), sort=feat.get("name"), cls="name-cell"),
            td(team_label(feat.get("tid"), teams_by_tid), sort=team_abbrev_for_tid(feat.get("tid"), teams_by_tid)),
            td(team_label(feat.get("oppTid"), teams_by_tid), sort=team_abbrev_for_tid(feat.get("oppTid"), teams_by_tid)),
            td(result_text, sort=feat.get("score")),
            td(" · ".join(line_bits), sort=safe_int(stats.get("pts"))),
            td(fmt_number(int(round(fpts)), 0) if fpts is not None else "—", sort=fpts, cls="lg-fpts-cell"),
            td(badges, sort=feat_rank(stats)),
        ])

    # Newest season first, and the CURRENT season is the default tab — honest
    # empty state early in the year, filling in automatically as games play.
    feat_seasons = list(range(season, start_season - 1, -1))
    rows_by_season: dict[int, list[str]] = {yr: [] for yr in feat_seasons}
    for feat in feats:
        yr = safe_int(feat.get("season"))
        if yr in rows_by_season:
            rows_by_season[yr].append(feat_row(feat))
    total_feats = sum(len(r) for r in rows_by_season.values())

    def feat_tab(yr: int, first: bool) -> str:
        return (f'<button type="button" class="{"active" if first else ""}" role="tab" id="tab-feats-{yr}" '
                f'aria-controls="panel-feats-{yr}" aria-selected="{"true" if first else "false"}" '
                f'tabindex="{"0" if first else "-1"}" data-tab-target="panel-feats-{yr}">{yr}</button>')

    feat_tabs = "".join(feat_tab(yr, i == 0) for i, yr in enumerate(feat_seasons))

    def feat_empty_message(yr: int) -> str:
        if yr == season:
            return f"No feats in {yr} yet — big nights land here as games are played."
        return f"No feats recorded in {yr}."

    feat_panels = "".join(
        f"""
      <div id="panel-feats-{yr}" role="tabpanel" aria-labelledby="tab-feats-{yr}" data-tab-panel{"" if i == 0 else " hidden"}>
        <div class="toolbar">
          <input class="table-search" data-table-filter="feats-{yr}" placeholder="Filter feats…" aria-label="Filter {yr} feats">
        </div>
        {table_html(headers, rows_by_season[yr], table_id=f"feats-{yr}", empty_message=feat_empty_message(yr))}
      </div>"""
        for i, yr in enumerate(feat_seasons)
    )
    body = f"""
    <section class="page-hero">
      <div>
        <h1>Records &amp; Feats</h1>
        <p class="muted">All-time leaderboards and {total_feats} notable single-game performances</p>
      </div>
    </section>
    {best_performances_card(data, teams, season)}
    {all_time_leaders_html(data, teams, start_season=start_season)}
    <section class="card">
      <div class="section-title-row"><h2>Single-Game Feats</h2><span class="muted small-copy"><span class="led-league" title="Gold marks the best single-game total of that season">gold ★</span> = season's best single-game total</span></div>
      <div class="tabs" role="tablist" aria-label="Feats by season" data-tabs>
        {feat_tabs}
      </div>
      {feat_panels}
    </section>
    """
    return page_html("Records", body, teams, root="", active="records")
