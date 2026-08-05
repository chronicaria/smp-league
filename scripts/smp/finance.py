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

from .core import (
    ALL_PLAYERS_BY_PID,
    esc,
    fmt_money,
    fmt_number,
    get_attr_value,
    latest_rating,
    latest_team_season,
    player_link,
    player_name,
    safe_float,
    safe_int,
    table_html,
    td,
    team_payroll,
)


def team_finances_table(roster: list[dict[str, Any]], season: int, data: dict[str, Any] | None = None, tid: int | None = None) -> str:
    # Window on the contract horizon starting with the CURRENT season. The old
    # window started at season + 1 ("drop the finished one"), which was right for a
    # mid-season export of a league with history but blanks out every expiring deal
    # in year one, when the current season hasn't been played yet.
    highlight_season = season
    seasons = list(range(season, season + 5))
    players = sorted(
        roster,
        key=lambda p: (-safe_float((p.get("contract") or {}).get("amount"), 0.0), player_name(p)),
    )
    headers = ["Pos", "Name"] + [(str(s), "cur-season" if s == highlight_season else "") for s in seasons]
    rows = []
    totals = {s: 0.0 for s in seasons}
    under_contract = {s: 0 for s in seasons}

    def salary_for(player: dict[str, Any], salary_season: int) -> float:
        contract = player.get("contract") or {}
        exp = safe_int(contract.get("exp"), season)
        if salary_season > exp:
            return 0.0
        exact = [
            salary for salary in player.get("salaries", [])
            if isinstance(salary, dict) and safe_int(salary.get("season"), -1) == salary_season
        ]
        if exact:
            return safe_float(exact[-1].get("amount"), 0.0)
        return safe_float(contract.get("amount"), 0.0)

    for player in players:
        contract = player.get("contract") or {}
        exp = safe_int(contract.get("exp"), season)
        rating = latest_rating(player, season)
        cells = [
            td(esc(rating.get("pos", "—")), sort=rating.get("pos", "")),
            td(player_link(player, "../"), sort=player_name(player), cls="name-cell"),
        ]
        for s in seasons:
            season_amount = salary_for(player, s)
            if s <= exp and season_amount > 0:
                totals[s] += season_amount
                under_contract[s] += 1
                cells.append(td(fmt_money(season_amount), sort=season_amount, cls="cur-season" if s == highlight_season else ""))
            else:
                cells.append(td("", sort=-1, cls="cur-season" if s == highlight_season else ""))
        rows.append("".join(cells))

    # Dead money: released players whose contracts are still owed.
    if data is not None and tid is not None:
        for released in data.get("releasedPlayers", []):
            if safe_int(released.get("tid"), -10) != tid:
                continue
            contract = released.get("contract") or {}
            amount = safe_float(contract.get("amount"), 0.0)
            exp = safe_int(contract.get("exp"), season)
            ghost = ALL_PLAYERS_BY_PID.get(safe_int(released.get("pid"), -10))
            name = player_name(ghost) if ghost else f"Released player {released.get('pid')}"
            cells = [
                td('<span class="muted">—</span>'),
                td(f'<span class="dead-money" title="Waived; contract still owed">{esc(name)} <span class="muted small-copy">(dead money)</span></span>', sort=name, cls="name-cell"),
            ]
            for s in seasons:
                if s <= exp and amount > 0:
                    totals[s] += amount
                    cells.append(td(fmt_money(amount), sort=amount, cls=("cur-season dead-cell" if s == highlight_season else "dead-cell")))
                else:
                    cells.append(td("", sort=-1, cls="cur-season" if s == highlight_season else ""))
            rows.append(f'<tr class="dead-row">{"".join(cells)}</tr>')

    # Retained salary from trades: the payer keeps its share (+); the roster team gets a credit (−).
    if tid is not None:
        for pid, r in FIN_RETENTION.items():
            retained_player = ALL_PLAYERS_BY_PID.get(pid)
            if retained_player is None:
                continue
            held_by = safe_int(r.get("held_by"), -10)
            roster_tid = safe_int(retained_player.get("tid"), -11)
            if tid not in (held_by, roster_tid):
                continue
            signed = safe_float(r.get("amount"), 0.0) * (1 if tid == held_by else -1)
            exp = safe_int((retained_player.get("contract") or {}).get("exp"), season)
            name = player_name(retained_player)
            tag = "retained salary" if tid == held_by else f'retained by {r.get("note", "another team")}'
            cells = [
                td('<span class="muted">—</span>'),
                td(f'<span class="dead-money" title="Salary retained in a trade">{esc(name)} <span class="muted small-copy">({tag})</span></span>', sort=name, cls="name-cell"),
            ]
            for s in seasons:
                if s <= exp and abs(signed) > 1e-9:
                    totals[s] += signed
                    cells.append(td(fmt_money(signed), sort=signed, cls=("cur-season dead-cell" if s == highlight_season else "dead-cell")))
                else:
                    cells.append(td("", sort=-1, cls="cur-season" if s == highlight_season else ""))
            rows.append(f'<tr class="dead-row">{"".join(cells)}</tr>')

    counts_cells = [td(""), td("Under Contract", cls="name-cell total-label")]
    totals_cells = [td(""), td("Committed Salary", cls="name-cell total-label")]
    for s in seasons:
        cur = " cur-season" if s == highlight_season else ""
        counts_cells.append(td(fmt_number(under_contract[s], 0), sort=under_contract[s], cls=cur.strip()))
        totals_cells.append(td(fmt_money(totals[s]), sort=totals[s], cls=cur.strip()))
    rows.append(f'<tr class="total-row">{"".join(counts_cells)}</tr>')
    rows.append(f'<tr class="total-row">{"".join(totals_cells)}</tr>')

    return f"""
    <section class="card">
      <div class="section-title-row">
        <h2>Salaries</h2>
        <span class="muted small-copy">Salary commitments through {seasons[-1]}</span>
      </div>
      {table_html(headers, rows, table_id="team-finances", empty_message="No contracts found.", wrap_cls="fit-table")}
    </section>
    """


# ---------- league finance model ----------
# All amounts in Basketball GM "thousands" units (100000 == $100M).
# There is NO league share and NO carried cash: every dollar is earned on the
# court, and each season's net revenue IS the team's budget for the next season.
#
# SMP II has NO SALARY CAP and NO LUXURY TAX. Revenue is the only limit on spending,
# which makes this curve the single most important balance lever in the league.
#
# Every dollar is earned on the court. There is no national pot and no appearance money:
# a team that wins nothing earns nothing.
#
#   every regular-season win  +$5M   (all 36 weigh the same -- no ladder, no diminishing)
#   playoff berth             +$10M
#   each playoff win          +$2.5M
#   reaching the finals       +$7.5M
#   winning the title         +$15M
#
# Derivation to the $1,000M league target (10 teams x $100M average payroll):
#   180 league wins x $5M                                     = $900M
#   postseason pool = 4 berths*10 + ~12 wins*2.5 + 2*7.5 + 15  = $100M
#   league total $1,000M -> exactly $100M average. An average 18-win team earns
#   18*5 = $90M on the court plus ~$10M of postseason expected value.
#
# The postseason is deliberately only 10% of league revenue. Wins are already the
# proxy for making the playoffs, so paying a big berth bonus on top double-counts the
# same achievement and makes one bracket swing a franchise's next three summers.
#
# THE TRADEOFF, stated plainly: with no base, revenue still spreads. A 28-8 champion
# banks 28*5 + 10 + 6*2.5 + 7.5 + 15 = $187.5M against an 8-28 team's $40M -- a 4.7x
# gap. That is down from 8.0x under the heavier postseason, but still well above the
# 1.6x of the concave ladder these replaced. With no salary cap, revenue IS spending
# power, so the gap compounds year over year. It only actually bites if the
# commissioner enforces "spend no more than you earned" -- nothing in Basketball GM
# reads these numbers. If the standings start ossifying, the cheapest brake is to
# raise FIN_BASE off zero; every dollar of base compresses the ratio without touching
# the per-win headline.
FIN_BASE = 0            # no appearance money: win nothing, earn nothing
FIN_PER_WIN = 5000      # +$5M per regular-season win, every win equal
FIN_PLAYOFF = 10000     # +$10M for a playoff berth (clinch-gated)
FIN_PLAYOFF_WIN = 2500  # +$2.5M per playoff game won
FIN_FINALS = 7500       # +$7.5M for reaching the finals
FIN_CHAMP = 15000       # +$15M for the title (a full run banks 10+15+7.5+15 = $47.5M)

# No cap and no tax. Kept as a display anchor only: the target average payroll, which
# is what price_contracts.py calibrates the salary curve against.
FIN_TARGET_PAYROLL = 100000
FIN_CAP = 0             # 0 == uncapped; league_cap() still reads the export
FIN_SOFT_CAP = FIN_TARGET_PAYROLL  # ponytail: import alias for pages/lineup.py


def win_revenue(wins: float) -> float:
    """Regular-season win money. Flat rate -- every win is worth the same."""
    return FIN_PER_WIN * max(0.0, float(wins))


def league_cap(data: dict[str, Any] | None, season: int | None = None) -> float:
    """The salary cap for ``season``, read from ``gameAttributes.salaryCap``.

    Read from the export so the site can never disagree with the league file the
    group actually plays; ``FIN_CAP`` is only the fallback for a file without one.
    """
    ga = (data or {}).get("gameAttributes") or {}
    cap = safe_float(get_attr_value(ga.get("salaryCap"), season), 0.0)
    return cap if cap > 0 else float(FIN_CAP)


def league_cap_type(data: dict[str, Any] | None, season: int | None = None) -> str:
    """``"hard"`` or ``"soft"`` from the export, so pages can branch on the rule."""
    ga = (data or {}).get("gameAttributes") or {}
    value = get_attr_value(ga.get("salaryCapType"), season)
    return str(value) if value else "hard"


# Manual cash adjustments outside the auto-computed ledger (thousands), keyed by
# season -> tid. Cash that changes hands in a trade, since BBGM exports don't record
# it. Signed: negative = cash out, positive = cash in; each season's entries must net
# to zero. ponytail: hand-maintained; add rows as trades happen.
FIN_ADJUSTMENTS: dict[int, dict[int, dict[str, Any]]] = {
    # Empty for SMP II. The SMP I rows (2030-2031) referenced a league that no longer
    # exists; add new rows as cash actually changes hands.
}

# Salary retained in a trade: the original team keeps paying part of a traded player's
# salary while the player sits on the new roster at full contract. BBGM exports don't
# record retention, so we move the retained share (thousands/yr) off the roster team's
# books onto the payer's — for payroll, cap room, and the salaries table — every season
# through the contract's exp. Keyed by pid. ponytail: hand-maintained; add rows as trades happen.
FIN_RETENTION: dict[int, dict[str, Any]] = {
    # Empty for SMP II. The SMP I entries were keyed by raw pid, and those pids belong
    # to players that no longer exist in the league file -- carrying them forward would
    # have silently charged retention against whichever new player inherited the id.
}


def team_retention_delta(tid: int, season: int) -> float:
    """Net salary-retention adjustment to a team's payroll for ``season`` (thousands).

    The payer (``held_by``) carries its retained share; the roster team is relieved of it.
    Only counts while the player is still under contract (``season <= exp``).
    """
    delta = 0.0
    for pid, r in FIN_RETENTION.items():
        player = ALL_PLAYERS_BY_PID.get(pid)
        if not player:
            continue
        exp = safe_int((player.get("contract") or {}).get("exp"), season)
        if season > exp:
            continue
        amount = safe_float(r.get("amount"), 0.0)
        if safe_int(r.get("held_by"), -10) == tid:
            delta += amount                       # payer keeps this on their books
        if safe_int(player.get("tid"), -10) == tid:
            delta -= amount                       # roster team is relieved of it
    return delta


def finals_games_to_win(data: dict[str, Any], season: int | None = None) -> int:
    """Wins that clinch the Finals series in ``season``.

    Derived from ``gameAttributes.numGamesPlayoffSeries`` (the last round is the
    Finals): SMP II is [5, 5], so three wins take the title, where SMP I's [7, 7]
    needed four. Hardcoding this is how the championship bonus silently stops being
    paid after a format change, so the export is the source of truth; the retained
    playoff game rows are the fallback, and a best-of-7 the last resort.
    """
    ga = (data or {}).get("gameAttributes") or {}
    lengths = get_attr_value(ga.get("numGamesPlayoffSeries"), season)
    if isinstance(lengths, list) and lengths:
        best_of = safe_int(lengths[-1], 0)
        if best_of > 0:
            return best_of // 2 + 1
    for game in ((data or {}).get("games") or []):
        if (game.get("playoffs") and game.get("numGamesToWinSeries") is not None
                and (season is None or safe_int(game.get("season"), -1) == season)):
            return max(1, safe_int(game.get("numGamesToWinSeries"), 4))
    return 4


def playoff_wins(data: dict[str, Any], tid: int, season: int) -> int:
    """Playoff GAMES won by a team in a season, summed across every round.

    Each series row carries ``home.won`` / ``away.won``. Returns 0 during the regular
    season, so the per-playoff-win payout only accrues once games are actually played.
    """
    series_by_season = {safe_int(ps.get("season")): ps
                        for ps in (data.get("playoffSeries") or []) if isinstance(ps, dict)}
    rounds = (series_by_season.get(season) or {}).get("series") or []
    total = 0
    for rnd in rounds:
        for m in (rnd or []):
            if not isinstance(m, dict):
                continue
            for side in ("home", "away"):
                entry = m.get(side) or {}
                if safe_int(entry.get("tid"), -90) == tid:
                    total += safe_int(entry.get("won"), 0)
    return total


def playoff_status(data: dict[str, Any], tid: int, season: int) -> tuple[bool, bool, bool]:
    """(made_playoffs, made_finals, won_championship) for a team in a season.

    Read from ``playoffSeries``; during the regular season there is no series yet,
    so this returns all-False and the playoff bonuses stay $0 until earned.

    ``playoffSeries.series`` GROWS one round at a time, so ``rounds[-1]`` is only the
    Finals once the bracket reaches its last round. The Finals is round index
    ``expected_rounds - 1`` (= log2(first-round matchups) + 1 total rounds); until that
    round exists no team has "made the finals", and the title is awarded only once the
    Finals series is clinched. This keeps the bonuses honest mid-playoff.
    """
    series_by_season = {safe_int(ps.get("season")): ps for ps in (data.get("playoffSeries") or []) if isinstance(ps, dict)}
    rounds = [rnd for rnd in ((series_by_season.get(season) or {}).get("series") or []) if rnd]
    if not rounds:
        return (False, False, False)

    matchups = lambda rnd: [m for m in (rnd or []) if isinstance(m, dict)]

    def in_matchup(m: dict[str, Any]) -> bool:
        return tid in (safe_int((m.get("home") or {}).get("tid"), -91), safe_int((m.get("away") or {}).get("tid"), -92))

    made = any(in_matchup(m) for rnd in rounds for m in matchups(rnd))
    first_round = matchups(rounds[0])
    expected_rounds = (int(round(math.log2(len(first_round)))) + 1) if first_round else len(rounds)

    made_finals = won_champ = False
    if len(rounds) >= expected_rounds:
        finals = matchups(rounds[expected_rounds - 1])
        made_finals = any(in_matchup(m) for m in finals)
        clinch = finals_games_to_win(data, season)
        for m in finals:
            home, away = m.get("home") or {}, m.get("away") or {}
            hw, aw = safe_int(home.get("won")), safe_int(away.get("won"))
            if max(hw, aw) < clinch:
                continue  # Finals series not clinched yet
            winner = safe_int(home.get("tid")) if hw > aw else safe_int(away.get("tid"))
            if winner == tid:
                won_champ = True
    return (made, made_finals, won_champ)


def team_dead_money(data: dict[str, Any] | None, tid: int, season: int) -> float:
    """Salary still owed to this team's waived players in ``season`` (dead money).

    A released player keeps being paid through their contract's ``exp`` year, so it
    counts against payroll/luxury tax even though they're off the roster.
    """
    total = 0.0
    for released in ((data or {}).get("releasedPlayers") or []):
        if safe_int(released.get("tid"), -10) != tid:
            continue
        contract = released.get("contract") or {}
        amount = safe_float(contract.get("amount"), 0.0)
        if amount > 0 and season <= safe_int(contract.get("exp"), season):
            total += amount
    return total


def compute_league_finances(data: dict[str, Any], teams: list[dict[str, Any]], players: list[dict[str, Any]], season: int, odds: dict[int, dict[str, Any]] | None = None) -> dict[str, Any]:
    """Per-team revenue ledger for the season, recomputed each build from game results.

    Returns ``{"teams": {tid: ledger}, "cap", "cap_type"}``.
    There is no league share and no carried cash: revenue (win payouts +
    clinch-gated bonuses + trade adjustments) IS the team's NET REVENUE — its
    whole budget for next season. Under a hard cap there is no luxury tax to net
    out and no tax pool to redistribute. Extra keys:
    ``cap_room`` (cap minus payroll) and ``over_cap``, which can only be true on a
    god-mode-edited roster because the engine blocks any move past the line;
    ``season_balance_*`` (net revenue minus this season's payroll),
    ``committed_next`` (next season's payroll incl. dead money/retention) and
    ``surplus_next`` (projected net revenue minus committed_next; negative means
    the team must shed salary). "Projected" figures use the 10k-sim projected wins
    and the expected value of the playoff bonuses (prob-weighted).
    """
    odds = odds or {}
    cap = league_cap(data, season)
    fin: dict[int, dict[str, Any]] = {}
    for team in teams:
        tid = safe_int(team.get("tid"), -99)
        if tid < 0 or team.get("disabled"):
            continue
        roster = [p for p in players if safe_int(p.get("tid"), -98) == tid]
        dead = team_dead_money(data, tid, season)
        retained = team_retention_delta(tid, season)  # traded-away salary kept on the books
        payroll = team_payroll(roster, season) + dead + retained  # waived + retained still get paid
        # Full next-season commitment (roster + dead money + retained) — matches the Salaries
        # table's committed-salary total, so "available to spend" nets out every obligation.
        payroll_next = (team_payroll(roster, season + 1)
                        + team_dead_money(data, tid, season + 1)
                        + team_retention_delta(tid, season + 1))
        ts = latest_team_season(team, season)
        won, lost = safe_int(ts.get("won"), 0), safe_int(ts.get("lost"), 0)
        made_po, made_finals, won_champ = playoff_status(data, tid, season)
        po_wins = playoff_wins(data, tid, season)
        earned_playoff = ((FIN_PLAYOFF if made_po else 0)
                          + FIN_PLAYOFF_WIN * po_wins
                          + (FIN_FINALS if made_finals else 0)
                          + (FIN_CHAMP if won_champ else 0))
        o = odds.get(tid) or {}
        proj_w = safe_float(o.get("proj_w"), float(won))
        po_p, fin_p, champ_p = safe_float(o.get("po")), safe_float(o.get("finals")), safe_float(o.get("champ"))
        # Expected playoff wins: a berth is worth ~1.5 games won, a finals trip ~3 more,
        # a title ~3 more on top. Rough, but it keeps the projection on the same scale as
        # the earned figure instead of understating a contender's postseason revenue.
        proj_po_wins = 1.5 * po_p + 3.0 * fin_p + 3.0 * champ_p
        proj_playoff = (FIN_PLAYOFF * po_p + FIN_PLAYOFF_WIN * proj_po_wins
                        + FIN_FINALS * fin_p + FIN_CHAMP * champ_p)
        adj_info = (FIN_ADJUSTMENTS.get(season) or {}).get(tid) or {}
        adj = safe_float(adj_info.get("amount"), 0.0)
        fin[tid] = {
            "adj": adj, "adj_note": adj_info.get("note", ""),
            "payroll": payroll, "committed_next": payroll_next, "dead": dead, "retained": retained, "won": won, "lost": lost,
            # Uncapped: there is no line to be over. `cap` is kept as the target-payroll
            # anchor so pages can show "vs league average" instead of "vs the cap".
            "cap": cap, "cap_room": cap - payroll, "over_cap": False,
            "base_rev": FIN_BASE,
            "win_rev_now": win_revenue(won), "win_rev_proj": win_revenue(proj_w),
            "earned_playoff": earned_playoff, "proj_playoff": proj_playoff,
            "proj_w": proj_w, "po": po_p, "finals": fin_p, "champ": champ_p,
            "revenue_now": FIN_BASE + win_revenue(won) + earned_playoff + adj,
            "revenue_proj": FIN_BASE + win_revenue(proj_w) + proj_playoff + adj,
        }
    for tid, f in fin.items():
        # Net revenue = the team's whole budget for next season. Nothing is netted
        # out of it: no carried cash, and no luxury tax under a hard cap.
        f["net_revenue_now"] = f["revenue_now"]
        f["net_revenue_proj"] = f["revenue_proj"]
        # Sanity line: net revenue vs this season's payroll.
        f["season_balance_now"] = f["net_revenue_now"] - f["payroll"]
        f["season_balance_proj"] = f["net_revenue_proj"] - f["payroll"]
        # Budget left after next season's already-committed salaries are paid.
        f["surplus_next"] = f["net_revenue_proj"] - f["committed_next"]
    return {"teams": fin, "cap": cap, "cap_type": league_cap_type(data, season)}


def fmt_money_pm(amount: Any) -> str:
    """Money with an explicit +/- sign; $0 for zero."""
    a = safe_float(amount, 0.0)
    if abs(a) < 1e-9:
        return "$0"
    return ("+" + fmt_money(a)) if a > 0 else fmt_money(a)
