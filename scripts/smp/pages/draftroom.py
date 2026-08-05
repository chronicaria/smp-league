"""The League Draft page: the snake board and the full player pool.

This is the room the league sits in on draft night. Two halves:

  The board   -- all 120 slots (12 rounds x 10 teams), snaking, so everyone can see
                 who is on the clock and what their next pick is. Slots fill in as
                 players come off the pool; before the draft every slot is open.
  The pool    -- every available player, sortable on any column and filterable by
                 position, with photos. This is the board people actually scan.

The pick order is derived the same way zengm's draft/genOrderFantasy.ts builds it:
round 1 runs in tid order and the order reverses every round. Deriving it (rather than
reading draftPicks) means the page is correct before the draft has been staged, which is
exactly when people want to look at it.
"""

from __future__ import annotations

import math
from typing import Any

from ..core import (
    RATING_GROUP_STARTS,
    is_draftable,
    TEAM_RATING_RANK_KEYS,
    active_teams_for_season,
    age,
    esc,
    fmt_money,
    get_attr_value,
    latest_rating,
    page_html,
    player_link,
    player_name,
    player_url,
    safe_float,
    safe_int,
    table_html,
    td,
    team_full_name,
)
from ..identity import team_identity
from ..portraits import portrait_html

DEFAULT_ROUNDS = 12


def _rounds(data: dict[str, Any], season: int) -> int:
    """Draft length. genOrderFantasy.ts uses minRosterSize as the round count."""
    ga = (data or {}).get("gameAttributes") or {}
    n = safe_int(get_attr_value(ga.get("minRosterSize"), season), 0)
    return n or DEFAULT_ROUNDS


def snake_order(tids: list[int], rounds: int) -> list[list[int]]:
    """[round][slot] -> tid, reversing every round. Mirrors genOrderFantasy.ts."""
    order, cur = [], list(tids)
    for _ in range(rounds):
        order.append(list(cur))
        cur.reverse()
    return order


def _drafted_by_slot(data: dict[str, Any]) -> dict[tuple[int, int], dict[str, Any]]:
    """(round, pick) -> player, for picks already made. Empty before the draft."""
    out: dict[tuple[int, int], dict[str, Any]] = {}
    for p in (data or {}).get("players", []):
        d = p.get("draft") or {}
        rnd, pick = safe_int(d.get("round")), safe_int(d.get("pick"))
        if rnd > 0 and pick > 0 and safe_int(p.get("tid"), -1) >= 0:
            out[(rnd, pick)] = p
    return out


def board_html(data: dict[str, Any], teams: list[dict[str, Any]], season: int) -> str:
    active = active_teams_for_season(teams, season)
    by_tid = {safe_int(t.get("tid")): t for t in active}
    tids = sorted(by_tid)
    rounds = _rounds(data, season)
    order = snake_order(tids, rounds)
    drafted = _drafted_by_slot(data)
    made = len(drafted)
    total = rounds * len(tids)

    head = "".join(f"<th>{i + 1}</th>" for i in range(len(tids)))
    body = []
    for r, row_tids in enumerate(order, start=1):
        cells = []
        for slot, tid in enumerate(row_tids, start=1):
            team = by_tid.get(tid) or {}
            ident = team_identity(tid)
            abbrev = esc(team.get("abbrev") or "?")
            player = drafted.get((r, slot))
            overall = (r - 1) * len(tids) + slot
            if player:
                inner = (f'<span class="dr-slot-team">{abbrev}</span>'
                         f'<a class="dr-slot-player" href="{player_url(player)}">'
                         f'{esc(player_name(player))}</a>')
                cls = "dr-slot dr-slot--filled"
            else:
                inner = (f'<span class="dr-slot-team">{abbrev}</span>'
                         f'<span class="dr-slot-open">#{overall}</span>')
                cls = "dr-slot"
            cells.append(
                f'<td class="{cls}" style="--slot-team:{ident["primary"]}" '
                f'title="Round {r}, pick {slot} — {esc(team_full_name(team))}">{inner}</td>'
            )
        body.append(f'<tr><th class="dr-round">R{r}</th>{"".join(cells)}</tr>')

    direction = ('<p class="muted small-copy">Snake order — round 1 runs left to right, '
                 'and every round after that reverses. Your first-round slot is your '
                 'last in round two.</p>')
    return f"""
    <section class="card">
      <div class="section-title-row">
        <h2>The Board</h2>
        <span class="muted small-copy">{made} of {total} picks made</span>
      </div>
      {direction}
      <div class="table-wrap">
        <table class="dr-board">
          <thead><tr><th class="dr-round"></th>{head}</tr></thead>
          <tbody>{"".join(body)}</tbody>
        </table>
      </div>
    </section>"""


def _pool_row(player: dict[str, Any], season: int, ranges: dict[str, tuple[float, float]]) -> str:
    rating = latest_rating(player, season)
    born = (player.get("born") or {}).get("year")
    contract = player.get("contract") or {}
    amount = safe_float(contract.get("amount"), 0.0)
    cells = [
        td(f'{portrait_html(player, "dr-pool-portrait", root="", size=32)}'
           f'{player_link(player, "", show_number=False)}',
           sort=player_name(player), cls="name-cell"),
        td(esc(rating.get("pos", "—")), sort=rating.get("pos", "")),
        td(age(player, season), sort=(season - born if isinstance(born, int) else None)),
        td(esc(rating.get("ovr") if rating.get("ovr") is not None else "—"), sort=rating.get("ovr")),
        td(esc(rating.get("pot") if rating.get("pot") is not None else "—"), sort=rating.get("pot")),
        td(fmt_money(amount) if amount else "—", sort=amount, cls="group-start"),
        td(esc(safe_int(contract.get("exp"), 0) or "—"), sort=safe_int(contract.get("exp"), 0)),
    ]
    for key, _ in TEAM_RATING_RANK_KEYS:
        value = rating.get(key)
        cls = "group-start" if key in RATING_GROUP_STARTS else ""
        cells.append(td(esc(value if value is not None else "—"), sort=value, cls=cls))
    return "".join(cells)


def pool_html(players: list[dict[str, Any]], season: int) -> str:
    def board_sort(p: dict[str, Any]) -> tuple:
        r = latest_rating(p, season)
        return (-safe_int(r.get("ovr")), -safe_int(r.get("pot")), player_name(p))

    # Hide players who are under 50 in BOTH ovr and pot -- no use now, no upside later.
    ordered = sorted((p for p in players if is_draftable(p, season)), key=board_sort)

    ranges: dict[str, tuple[float, float]] = {}
    for key, _ in TEAM_RATING_RANK_KEYS:
        vals = [float(latest_rating(p, season).get(key))
                for p in ordered
                if latest_rating(p, season).get(key) is not None
                and math.isfinite(safe_float(latest_rating(p, season).get(key), float("nan")))]
        ranges[key] = (min(vals), max(vals)) if vals else (0.0, 0.0)

    headers: list = ["Player", "Pos", "Age", "Ovr", "Pot",
                     ("Salary", "group-start"), "Thru"]
    for key, label in TEAM_RATING_RANK_KEYS:
        headers.append((label, "group-start" if key in RATING_GROUP_STARTS else ""))
    rows = [_pool_row(p, season, ranges) for p in ordered]

    return f"""
    <section class="card">
      <div class="section-title-row">
        <h2>Available Players</h2>
        <span class="muted small-copy">{len(ordered)} available · click any column to sort</span>
      </div>
      {table_html(headers, rows, table_id="draft-pool",
                  empty_message="Nobody left.", pos_filter=True,
                  wrap_cls="fit-table")}
    </section>"""


def top_board_html(players: list[dict[str, Any]], season: int, limit: int = 12) -> str:
    """The consensus top of the board, as cards — what people look at first."""
    def key(p: dict[str, Any]) -> tuple:
        r = latest_rating(p, season)
        return (-safe_int(r.get("ovr")), -safe_int(r.get("pot")), player_name(p))

    cards = []
    eligible = [p for p in players if is_draftable(p, season)]
    for rank, p in enumerate(sorted(eligible, key=key)[:limit], 1):
        r = latest_rating(p, season)
        amount = safe_float((p.get("contract") or {}).get("amount"), 0.0)
        cards.append(
            f'<a class="fa-card" href="{player_url(p)}">'
            f'<span class="fa-card-rank" aria-hidden="true">{rank}</span>'
            f'{portrait_html(p, "fa-card-portrait", root="", size=56)}'
            f'<span class="fa-card-name">{esc(player_name(p))}</span>'
            f'<span class="fa-card-meta">{esc(r.get("pos") or "—")} · {age(p, season)} yr · '
            f'{esc(r.get("ovr", "—"))} ovr / {esc(r.get("pot", "—"))} pot</span>'
            f'<span class="fa-card-ask">{fmt_money(amount) if amount else ""}</span>'
            f'</a>')
    return f"""
    <section class="card">
      <div class="section-title-row">
        <h2>Top of the Board</h2>
        <span class="muted small-copy">best available by overall</span>
      </div>
      <div class="fa-card-grid">{"".join(cards)}</div>
    </section>"""


def render_league_draft_page(data: dict[str, Any], teams: list[dict[str, Any]],
                             season: int, pool: list[dict[str, Any]]) -> str:
    active = active_teams_for_season(teams, season)
    rounds = _rounds(data, season)
    total = rounds * len(active)
    eligible = [p for p in pool if is_draftable(p, season)]
    body = f"""
    <section class="page-hero">
      <div>
        <h1>League Draft</h1>
        <p class="muted">{rounds} rounds · {len(active)} teams · {total} picks · snake order —
        {len(eligible)} eligible players on the board</p>
      </div>
    </section>
    {top_board_html(pool, season)}
    {board_html(data, teams, season)}
    {pool_html(pool, season)}
    """
    return page_html("League Draft", body, teams, root="", active="league-draft")
