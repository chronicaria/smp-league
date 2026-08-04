from __future__ import annotations

"""Trade Center page.

Like the Compare page, the Trade Machine is a server-rendered shell whose
client (static/js/trade-extras.js) fetches assets/app-data.json for rosters,
contracts, Win Shares, payrolls (incl. dead money) and the finance block's
$100M hard-cap line. The client grades each build with a post-trade roster
projection — team OVR, projected record, and a win-shares ledger — instead of
the engine's abstract "value" number, which the page no longer surfaces
anywhere. The only page-embedded data is a tiny draft-pick supplement —
app-data.json does not carry picks.

The contract efficiency table stays fully server-rendered.
"""

import json
from typing import Any

from ..core import (
    age,
    esc,
    fmt_money,
    fmt_number,
    heat_style,
    latest_rating,
    page_html,
    player_link,
    player_name,
    safe_float,
    safe_int,
    season_regular_stat,
    table_html,
    td,
    team_abbrev,
    team_dot,
    team_label,
    team_palette_by_tid,
)


def contract_efficiency_table(players: list[dict[str, Any]], teams: list[dict[str, Any]], season: int, root: str = "") -> str:
    teams_by_tid = {t["tid"]: t for t in teams}
    palette = team_palette_by_tid(teams)
    rows_data = []
    for player in players:
        if safe_int(player.get("tid"), -9) < 0:
            continue
        contract = player.get("contract") or {}
        amount = safe_float(contract.get("amount"))
        if amount < 1000:
            continue  # minimum contracts are trivially "efficient"
        stat = season_regular_stat(player, season)
        ws = safe_float(stat.get("ows")) + safe_float(stat.get("dws"))
        vorp = safe_float(stat.get("vorp"))
        ws_per_m = ws / (amount / 1000.0)
        rows_data.append((player, amount, contract.get("exp"), ws, vorp, ws_per_m))
    if not rows_data:
        return ""
    eff_values = [r[5] for r in rows_data]
    lo, hi = min(eff_values), max(eff_values)
    rows_data.sort(key=lambda r: -r[5])
    rows = []
    for player, amount, exp, ws, vorp, ws_per_m in rows_data:
        rows.append("".join([
            td(player_link(player, root, show_number=False), sort=player_name(player), cls="name-cell"),
            td(f'{team_dot(player.get("tid"), palette)}{team_label(player.get("tid"), teams_by_tid, root)}', sort=team_label(player.get("tid"), teams_by_tid, as_link=False)),
            td(age(player, season), sort=age(player, season)),
            td(esc(latest_rating(player, season).get("ovr", "—")), sort=latest_rating(player, season).get("ovr")),
            td(fmt_money(amount), sort=amount),
            td(esc(exp or "—"), sort=exp),
            td(fmt_number(ws, 1), sort=ws),
            td(fmt_number(vorp, 1), sort=vorp),
            td(fmt_number(ws_per_m * 10, 2), sort=ws_per_m, style=heat_style(ws_per_m, lo, hi, 1)),
        ]))
    headers = ["Player", "Team", "Age", "Ovr", "Salary", "Thru", "WS", "VORP", "WS per $10M"]
    return f"""
    <section class="card home-section">
      <div class="section-title-row"><h2>Contract Efficiency</h2><span class="muted small-copy">non-minimum contracts · this season</span></div>
      <div class="toolbar">
        <input class="table-search" data-table-filter="contracts" placeholder="Filter contracts…" aria-label="Filter contracts">
      </div>
      {table_html(headers, rows, table_id="contracts", empty_message="No contracts found.")}
    </section>
    """


def trade_extras_payload(data: dict[str, Any], teams: list[dict[str, Any]]) -> str:
    """Compact JSON supplement: tradeable draft picks per team.

    ``picks`` maps tid -> [{id, label}] (dpid + a human label like
    "2032 2nd (via MAN)"). Everything else the Trade Machine needs comes from
    assets/app-data.json.
    """
    teams_by_tid = {int(t.get("tid")): t for t in teams if t.get("tid") is not None}
    picks: dict[str, list[dict[str, Any]]] = {}
    for dp in data.get("draftPicks", []):
        tid = safe_int(dp.get("tid"), -10)
        if tid < 0 or tid not in teams_by_tid or not isinstance(dp.get("season"), int):
            continue
        via = ""
        if safe_int(dp.get("originalTid"), -10) != tid:
            via = team_abbrev(teams_by_tid.get(safe_int(dp.get("originalTid"), -10)))
        picks.setdefault(str(tid), []).append({
            "id": dp.get("dpid"),
            "label": f"{dp.get('season')}{'' if safe_int(dp.get('round')) == 1 else ' 2nd'}" + (f" (via {via})" if via else ""),
        })
    payload = {"picks": picks}
    return json.dumps(payload, separators=(",", ":"), sort_keys=True).replace("</", "<\\/")


def _trade_side(index: int, label: str) -> str:
    return f"""
        <div class="trade-side">
          <label class="select-label combo-label" for="trade-combo-{index}">{label}</label>
          <div class="combo" data-trade-combo="{index}">
            <input id="trade-combo-{index}" type="text" class="combo-input" role="combobox"
              aria-autocomplete="list" aria-expanded="false" aria-controls="trade-combo-list-{index}"
              aria-activedescendant="" autocomplete="off" autocapitalize="off" spellcheck="false"
              placeholder="Type a team…" disabled>
            <div class="combo-list" id="trade-combo-list-{index}" role="listbox" aria-label="{label} matches" hidden></div>
          </div>
          <input class="table-search combo-roster-filter" type="search" data-trade-filter="{index}"
            placeholder="Filter roster…" aria-label="Filter {label} roster" disabled>
          <div class="trade-list" data-trade-list="{index}">
            <p class="app-loading">Loading rosters…</p>
          </div>
        </div>"""


def render_trade_page(data: dict[str, Any], teams: list[dict[str, Any]], players: list[dict[str, Any]], season: int) -> str:
    extras = trade_extras_payload(data, teams)
    machine = f"""
    <section class="card home-section" data-app="trade">
      <div class="section-title-row"><h2>Trade Machine</h2><span class="muted small-copy"
        title="Each side is re-projected after the swap: engine team OVR, a record from the sim's win-probability model, last season's Win Shares in vs out, and payroll against the $100M hard cap.">post-trade
        OVR, record &amp; win-share projections · payrolls incl. dead money</span></div>
      <div class="trade-grid">{_trade_side(0, "Team A")}{_trade_side(1, "Team B")}
      </div>
      <div class="trade-summary" data-trade-summary aria-live="polite"></div>
      <noscript><p class="empty-state">The trade machine needs JavaScript.</p></noscript>
    </section>
    <script type="application/json" id="trade-extra">{extras}</script>
    """
    body = f"""
    <section class="page-hero">
      <div>
        <h1>Trade Center</h1>
        <p class="muted">Build a trade, see what each roster becomes</p>
      </div>
    </section>
    {machine}
    {contract_efficiency_table(players, teams, season)}
    """
    return page_html("Trade Center", body, teams, root="", active="trade")
