from __future__ import annotations

"""Shared client payload: assets/app-data.json.

One compact, deterministic JSON blob per build, consumed by the client-side
apps (Compare, Trade Machine, Lineup Lab, Win-Out Machine) instead of each page
embedding its own player JSON. Schema (see PLAN.md):

    { "season": int,
      "ws_season": int|null,  # season the players' "ws" is drawn from; null in year one
      "players": [{pid,name,pos,age,tid,jersey,ovr,pot,salary,exp,value,ws,
                   pg:{pts,trb,ast,stl,blk,tov,min,fg_pct,tp_pct,ft_pct,fpts},
                   ratings:{15 subratings}, skills:[...]}],
      "teams": [{tid,abbrev,region,name,colors:{primary,secondary,chart},
                 strength,payroll,record:{w,l}}],
      "sim": {"strengths":{tid:num}, "hca":num, "logistic_k":num,
              "schedule":[[day,home_tid,away_tid],...],
              "bench_ovrs":[5 floats desc], "season_games":int},
      "finance": {"cap":100000, "cap_type":"hard", "tax_line":100000,
                  "notes":"thousands"} }

All money is in Basketball GM "thousands" units. The sim block mirrors
simulate_league's win-probability model (see simmodel.sim_client_inputs) so
client sims agree with the server-side Monte Carlo; bench_ovrs is the
league-average 6th..10th-best current-roster OVR (Lineup Lab's bench);
season_games is the regular-season length (the Trade Machine's projected
records span it). "ws" is the player's regular-season Win Shares (ows+dws)
from ws_season — the newest COMPLETED season — and is null for players
without a stat row that year (rookies, prospects); the Trade Machine's
win-shares ledger sums it per side. ws_season is itself null until the league
has completed a season, so year one never names a season that never happened.
"""

import json
from pathlib import Path
from typing import Any

from .core import (
    ALL_PLAYERS_BY_PID,
    RATING_LABELS,
    active_players,
    current_season,
    draft_prospects,
    latest_rating,
    latest_regular_stat,
    made_pct,
    per_game,
    phase_value,
    player_name,
    regular_season_length,
    safe_float,
    safe_int,
    season_regular_stat,
    stat_gp,
    team_payroll,
    team_sort_key,
    total_rebounds,
)
from .derived import fantasy_pts
from .finance import league_cap, league_cap_type, team_dead_money, team_retention_delta
from .identity import TEAM_IDENTITY
from .simmodel import league_bench_ovrs, sim_client_inputs


def _team_colors(tid: int, team: dict[str, Any]) -> dict[str, str]:
    """Identity colors for a team: the identity.py registry, else the export's own
    colors (keeps the payload data-driven for an expansion team nobody has branded).

    identity.py is the single owner of the tid -> color table. appdata used to keep
    its own copy, which silently went stale the moment a color changed there.
    """
    if tid in TEAM_IDENTITY:
        ident = TEAM_IDENTITY[tid]
        return {
            "primary": str(ident["primary"]),
            "secondary": str(ident["secondary"]),
            "chart": str(ident.get("chart", ident["secondary"])),
        }
    export_colors = [c for c in (team.get("colors") or []) if isinstance(c, str)]
    primary = export_colors[0] if export_colors else "#39424f"
    secondary = export_colors[1] if len(export_colors) > 1 else "#8899aa"
    return {"primary": primary, "secondary": secondary, "chart": secondary}


def _round(value: float | None, digits: int = 1) -> float | None:
    if value is None:
        return None
    # round() then re-add 0.0 to normalize -0.0 -> 0.0 for deterministic JSON
    return round(float(value), digits) + 0.0


# Basketball GM phase 4 (draft lottery) is the first phase at which the current
# season's playoffs are decided, so its Win Shares are final. Mirrors the cap
# in pages/wrapped.newest_completed_season.
_PHASE_SEASON_COMPLETE = 4


def ws_reference_season(data: dict[str, Any], season: int) -> int | None:
    """The newest season with FINAL Win Shares: the current season once its
    playoffs have finished (phase >= draft lottery), else the previous one.

    ``None`` before any season has been completed. In year one the previous season
    is older than the league itself, and naming it would label an all-blank Win
    Shares column "2025" — a season that never happened.
    """
    if phase_value(data) >= _PHASE_SEASON_COMPLETE:
        return season
    previous = season - 1
    starting = safe_int((data.get("gameAttributes") or {}).get("startingSeason"), previous)
    return previous if previous >= starting else None


def _player_ws(player: dict[str, Any], ws_season: int | None) -> float | None:
    """Regular-season Win Shares (ows+dws) from ``ws_season``; None without a row."""
    if ws_season is None:
        return None
    stat = season_regular_stat(player, ws_season)
    if not stat:
        return None
    return _round(safe_float(stat.get("ows")) + safe_float(stat.get("dws")), 1)


def _player_entry(player: dict[str, Any], season: int, start_season: int, ws_season: int | None) -> dict[str, Any]:
    rating = latest_rating(player, season)
    stat = latest_regular_stat(player, start_season, season)
    gp = stat_gp(stat)
    contract = player.get("contract") or {}
    fpts_total = fantasy_pts(stat)
    born_year = (player.get("born") or {}).get("year")
    jersey = player.get("jerseyNumber")
    return {
        "pid": safe_int(player.get("pid"), -1),
        "name": player_name(player),
        "pos": str(rating.get("pos") or ""),
        "age": (season - born_year) if isinstance(born_year, int) else None,
        "tid": safe_int(player.get("tid"), -1),
        "jersey": str(jersey) if jersey not in (None, "") else None,
        "ovr": safe_int(rating.get("ovr")),
        "pot": safe_int(rating.get("pot")),
        "salary": int(round(safe_float(contract.get("amount")))),
        "exp": safe_int(contract.get("exp")) if contract.get("exp") is not None else None,
        "value": _round(safe_float(player.get("value")), 1),
        "ws": _player_ws(player, ws_season),
        "pg": {
            "pts": _round(per_game(stat, "pts")),
            "trb": _round(total_rebounds(stat) / gp if gp else 0.0),
            "ast": _round(per_game(stat, "ast")),
            "stl": _round(per_game(stat, "stl")),
            "blk": _round(per_game(stat, "blk")),
            "tov": _round(per_game(stat, "tov")),
            "min": _round(per_game(stat, "min")),
            "fg_pct": _round(made_pct(stat.get("fg"), stat.get("fga"))),
            "tp_pct": _round(made_pct(stat.get("tp"), stat.get("tpa"))),
            "ft_pct": _round(made_pct(stat.get("ft"), stat.get("fta"))),
            "fpts": _round(fpts_total / gp) if (fpts_total is not None and gp) else None,
        },
        "ratings": {key: safe_int(rating.get(key)) for key in RATING_LABELS},
        "skills": [str(s) for s in (rating.get("skills") or [])],
    }


def build_app_data(
    data: dict[str, Any],
    teams: list[dict[str, Any]] | None = None,
    players: list[dict[str, Any]] | None = None,
    season: int | None = None,
    start_season: int = 2026,
) -> dict[str, Any]:
    """Build the shared client payload dict from a league export.

    ``teams``/``players``/``season`` default to the same selections build.py
    makes, so the standalone call and the build-time call produce identical
    payloads. Deterministic: same export in, same dict out (all floats rounded,
    no wall-clock reads, no RNG).
    """
    if season is None:
        season = current_season(data)
    if teams is None:
        teams = sorted(data.get("teams", []), key=team_sort_key)
    if players is None:
        players = active_players(data)
    if not ALL_PLAYERS_BY_PID:
        # finance retention lookups resolve pids through this registry; build.py
        # populates it, standalone callers (tests) may not have.
        ALL_PLAYERS_BY_PID.update(
            {safe_int(p.get("pid")): p for p in data.get("players", []) if p.get("pid") is not None}
        )

    sim = sim_client_inputs(data, teams, players, season)
    fresh = bool(sim.get("fresh"))
    ws_season = ws_reference_season(data, season)

    pool = sorted(
        players + draft_prospects(data),
        key=lambda p: (-safe_int(latest_rating(p, season).get("ovr")), player_name(p), safe_int(p.get("pid"))),
    )
    player_entries = [_player_entry(p, season, start_season, ws_season) for p in pool]

    team_entries: list[dict[str, Any]] = []
    for team in sorted(teams, key=lambda t: safe_int(t.get("tid"), 10**9)):
        tid = safe_int(team.get("tid"), -1)
        if tid < 0 or team.get("disabled"):
            continue
        roster = [p for p in players if safe_int(p.get("tid"), -9) == tid]
        payroll = (
            team_payroll(roster, season)
            + team_dead_money(data, tid, season)
            + team_retention_delta(tid, season)
        )
        team_entries.append({
            "tid": tid,
            "abbrev": str(team.get("abbrev") or f"T{tid}"),
            "region": str(team.get("region") or ""),
            "name": str(team.get("name") or ""),
            "colors": _team_colors(tid, team),
            "strength": _round(sim["strengths"].get(tid, 0.0), 4),
            "payroll": int(round(payroll)),
            "record": {
                "w": 0 if fresh else safe_int(sim["wins"].get(tid)),
                "l": 0 if fresh else safe_int(sim["losses"].get(tid)),
            },
        })

    return {
        "season": season,
        "ws_season": ws_season,
        "players": player_entries,
        "teams": team_entries,
        "sim": {
            "strengths": {str(tid): _round(value, 4) for tid, value in sim["strengths"].items()},
            "hca": sim["hca"],
            "logistic_k": sim["logistic_k"],
            "schedule": [[safe_int(day), safe_int(home), safe_int(away)] for day, home, away in sim["schedule"]],
            "bench_ovrs": league_bench_ovrs(players, season),
            "season_games": regular_season_length(data, season),
        },
        # A hard cap is a legality boundary, not a penalty threshold, so "cap" is the
        # honest noun; "tax_line" is the same number under the old key, kept until the
        # three client apps that read it (lineup.js, trade-extras.js, site.js) move over.
        "finance": {
            "cap": int(round(league_cap(data, season))),
            "cap_type": league_cap_type(data, season),
            "tax_line": int(round(league_cap(data, season))),
            "notes": "thousands",
        },
    }


def write_app_data(
    out_dir: Path,
    data: dict[str, Any],
    teams: list[dict[str, Any]] | None = None,
    players: list[dict[str, Any]] | None = None,
    season: int | None = None,
    start_season: int = 2026,
) -> Path:
    """Build and write <out>/assets/app-data.json (compact, sorted keys, deterministic)."""
    app = build_app_data(data, teams=teams, players=players, season=season, start_season=start_season)
    path = Path(out_dir) / "assets" / "app-data.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(app, separators=(",", ":"), sort_keys=True, ensure_ascii=False)
    path.write_text(payload, encoding="utf-8")
    return path
