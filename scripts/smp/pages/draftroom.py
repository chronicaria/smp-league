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

The pool's default order is the league's own board (league-data/draft_board_order.csv),
exported from the game's Undrafted screen, so the page opens on the same ranking the room
is looking at. Sorting by overall instead would put a 28-year-old 73 above LeBron.
"""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

from ..core import (
    RATING_GROUP_STARTS,
    heat_style_pct,
    is_draftable,
    pct_ramp,
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

# Cards in the Top of the Board strip. Kept to one row -- .fa-card-grid lays out
# exactly this many columns, so changing it here means changing it in league.css too.
TOP_BOARD_CARDS = 8

BOARD_ORDER_FILE = "draft_board_order.csv"


def load_board_order(path: Path | str | None) -> dict[str, int]:
    """``{player name: rank}`` from the league's exported Undrafted board.

    Row order is the ranking; the other columns are ignored (they duplicate the export).
    A missing or unreadable file just means "no board", and the pool falls back to
    overall — the page must never fail to build over a cosmetic ordering.
    """
    if path is None:
        return {}
    path = Path(path)
    if not path.is_file():
        return {}
    try:
        with path.open(encoding="utf-8-sig", newline="") as fh:
            rows = list(csv.DictReader(fh))
    except (OSError, csv.Error, UnicodeDecodeError):
        return {}
    order: dict[str, int] = {}
    for rank, row in enumerate(rows):
        name = (row.get("Name") or "").strip()
        if name:
            order.setdefault(name, rank)
    return order


def board_rank(player: dict[str, Any], order: dict[str, int]) -> int:
    """Board position, or a sentinel that parks unlisted players after the board.

    Anyone the board does not name is either newly drafted (so gone from the pool
    anyway) or arrived after it was exported; either way he sorts last, by overall.
    """
    return order.get(player_name(player).strip(), len(order) + 1)


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


def _pool_row(player: dict[str, Any], season: int, ramps: dict[str, list[float]]) -> str:
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
        td(esc(rating.get("ovr") if rating.get("ovr") is not None else "—"), sort=rating.get("ovr"),
           style=heat_style_pct(rating.get("ovr"), ramps.get("ovr", []))),
        td(esc(rating.get("pot") if rating.get("pot") is not None else "—"), sort=rating.get("pot"),
           style=heat_style_pct(rating.get("pot"), ramps.get("pot", []))),
        td(fmt_money(amount) if amount else "—", sort=amount, cls="group-start"),
        td(esc(safe_int(contract.get("exp"), 0) or "—"), sort=safe_int(contract.get("exp"), 0)),
    ]
    for key, _ in TEAM_RATING_RANK_KEYS:
        value = rating.get(key)
        cls = "group-start" if key in RATING_GROUP_STARTS else ""
        cells.append(td(esc(value if value is not None else "—"), sort=value, cls=cls,
                        style=heat_style_pct(value, ramps.get(key, []))))
    return "".join(cells)


def _board_sort_key(season: int, order: dict[str, int]):
    """Board rank first, then overall/potential for anyone the board doesn't list."""
    def key(p: dict[str, Any]) -> tuple:
        r = latest_rating(p, season)
        return (board_rank(p, order), -safe_int(r.get("ovr")), -safe_int(r.get("pot")), player_name(p))
    return key


def pool_html(players: list[dict[str, Any]], season: int, order: dict[str, int] | None = None) -> str:
    order = order or {}
    # Hide players who are under 50 in BOTH ovr and pot -- no use now, no upside later.
    ordered = sorted((p for p in players if is_draftable(p, season)), key=_board_sort_key(season, order))

    # Heat ramps are built from the AVAILABLE draftees only, so the color a cell gets
    # answers "how does this rate against who is actually still on the board".
    ramps: dict[str, list[float]] = {}
    for key in ["ovr", "pot"] + [k for k, _ in TEAM_RATING_RANK_KEYS]:
        ramps[key] = pct_ramp(latest_rating(p, season).get(key) for p in ordered)

    headers: list = ["Player", "Pos", "Age", "Ovr", "Pot",
                     ("Salary", "group-start"), "Thru"]
    for key, label in TEAM_RATING_RANK_KEYS:
        headers.append((label, "group-start" if key in RATING_GROUP_STARTS else ""))
    rows = [_pool_row(p, season, ramps) for p in ordered]

    return f"""
    <section class="card">
      <div class="section-title-row">
        <h2>Available Players</h2>
        <span class="muted small-copy">{len(ordered)} available · {"league board order" if order else "by overall"} · shaded by percentile among them · click any column to sort</span>
      </div>
      {table_html(headers, rows, table_id="draft-pool",
                  empty_message="Nobody left.", pos_filter=True,
                  wrap_cls="fit-table")}
    </section>"""


def top_board_html(players: list[dict[str, Any]], season: int, limit: int = TOP_BOARD_CARDS,
                   order: dict[str, int] | None = None) -> str:
    """The consensus top of the board, as cards — what people look at first."""
    order = order or {}
    cards = []
    eligible = [p for p in players if is_draftable(p, season)]
    for rank, p in enumerate(sorted(eligible, key=_board_sort_key(season, order))[:limit], 1):
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
        <span class="muted small-copy">{"best available, league board order" if order else "best available by overall"}</span>
      </div>
      <div class="fa-card-grid">{"".join(cards)}</div>
    </section>"""


def render_league_draft_page(data: dict[str, Any], teams: list[dict[str, Any]],
                             season: int, pool: list[dict[str, Any]],
                             board_order: dict[str, int] | None = None) -> str:
    active = active_teams_for_season(teams, season)
    rounds = _rounds(data, season)
    total = rounds * len(active)
    eligible = [p for p in pool if is_draftable(p, season)]
    order = board_order or {}
    body = f"""
    <section class="page-hero">
      <div>
        <h1>League Draft</h1>
        <p class="muted">{rounds} rounds · {len(active)} teams · {total} picks · snake order —
        {len(eligible)} eligible players on the board</p>
      </div>
    </section>
    {top_board_html(pool, season, order=order)}
    {board_html(data, teams, season)}
    {pool_html(pool, season, order=order)}
    """
    return page_html("League Draft", body, teams, root="", active="league-draft")
