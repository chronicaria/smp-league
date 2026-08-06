from __future__ import annotations

"""wrapped.html — "SMP Wrapped": a full-bleed scroll-snap recap of the newest
COMPLETED season (the latest season whose playoffs produced a champion).

Phase-gated and data-driven: the season is computed from the export every
build — never hardcoded — so the page regenerates itself when a new season
finishes. While a season's playoffs are still undecided the page recaps the
previous completed season; if no season has ever finished it renders an
honest empty state instead.

Slides: title → season in numbers → best single-game fantasy line →
league-leaders wall → playoff story (bracket recap + champion banner) →
one card per team (record, playoff result, top performer) → outro. Team slides link to standalone share-card SVGs written by
``emit_wrapped_cards`` to ``assets/wrapped/{season}-{abbrev}.svg`` — those
SVGs deliberately hardcode the identity colors (they leave the site's CSS
when pasted into a group chat).
"""

import html as html_lib
from pathlib import Path
from typing import Any, Optional, Union

from ..core import (
    FREE_AGENT_TID,
    RETIRED_TID,
    active_teams_for_season,
    combine_stat_rows,
    completed_game_items,
    current_season,
    esc,
    fmt_number,
    game_slug_from_gid,
    initials,
    latest_game_season,
    latest_team_season,
    page_html,
    phase_value,
    player_name,
    player_url,
    safe_float,
    safe_int,
    season_regular_stat,
    standings_order,
    stat_gp,
    team_abbrev,
    team_full_name,
    team_url,
    total_rebounds,
)
from ..derived import fantasy_pts, led_league
from ..identity import crest_svg, monogram_svg, team_css_vars, team_identity
from ..portraits import portrait_html

# Basketball GM phase 4 is the draft lottery — the first phase at which the
# current season's playoffs are guaranteed complete.
PHASE_DRAFT_LOTTERY = 4

# Leaders wall: (stat key in seasonLeaders.regularSeason, per-game label, word).
LEADER_KEYS = [
    ("pts", "PPG", "Points"),
    ("trb", "RPG", "Rebounds"),
    ("ast", "APG", "Assists"),
    ("stl", "SPG", "Steals"),
    ("blk", "BPG", "Blocks"),
]


# ---------------------------------------------------------------------------
# Season gating: which season does Wrapped cover?
# ---------------------------------------------------------------------------


def playoff_series_row(data: dict[str, Any], season: int) -> dict[str, Any] | None:
    for row in data.get("playoffSeries") or []:
        if isinstance(row, dict) and safe_int(row.get("season"), -1) == season:
            return row
    return None


def playoff_rounds(data: dict[str, Any], season: int) -> list[list[dict[str, Any]]]:
    row = playoff_series_row(data, season)
    if not row:
        return []
    return [rnd for rnd in row.get("series") or [] if isinstance(rnd, list)]


def season_champion_tid(data: dict[str, Any], season: int) -> int | None:
    """The champion's tid, or None while that season's playoffs are undecided.

    A team is the champion iff its season row's ``playoffRoundsWon`` equals the
    number of playoff rounds — BBGM only writes that once the final ends, so
    this doubles as the "playoffs complete" check.
    """
    rounds = len(playoff_rounds(data, season))
    if rounds <= 0:
        return None
    for team in data.get("teams") or []:
        for row in team.get("seasons") or []:
            if isinstance(row, dict) and row.get("season") == season and safe_int(row.get("playoffRoundsWon"), -1) == rounds:
                return safe_int(team.get("tid"), -1)
    return None


def newest_completed_season(data: dict[str, Any]) -> int | None:
    """Newest season with a decided champion. Never hardcoded.

    The export's own phase caps the search: before the draft lottery the
    current season cannot be complete, so Wrapped recaps the prior season
    until the playoffs actually finish.
    """
    season = current_season(data)
    cap = season if phase_value(data) >= PHASE_DRAFT_LOTTERY else season - 1
    best: int | None = None
    for row in data.get("playoffSeries") or []:
        s = safe_int(row.get("season") if isinstance(row, dict) else None, -1)
        if s < 0 or s > cap:
            continue
        if season_champion_tid(data, s) is None:
            continue
        if best is None or s > best:
            best = s
    return best


def _round_name(index: int, rounds: int) -> str:
    if index == rounds - 1:
        return "Finals"
    if index == rounds - 2:
        return "Semifinals"
    if index == rounds - 3:
        return "Quarterfinals"
    return f"Round {index + 1}"


def playoff_result_label(rounds_won: Any, rounds: int) -> str:
    prw = safe_int(rounds_won, -1)
    if rounds <= 0 or prw < 0:
        return "Missed the playoffs"
    if prw >= rounds:
        return "League champions"
    if prw == rounds - 1:
        return "Runners-up"
    return f"{_round_name(prw, rounds)} exit"


def _team_seed(data: dict[str, Any], season: int, tid: int) -> int | None:
    rounds = playoff_rounds(data, season)
    if not rounds:
        return None
    for series in rounds[0]:
        for side_key in ("home", "away"):
            side = series.get(side_key) or {}
            if safe_int(side.get("tid"), -1) == tid:
                return safe_int(side.get("seed"), 0) or None
    return None


# ---------------------------------------------------------------------------
# Derived slide inputs (pure computation)
# ---------------------------------------------------------------------------


def _season_games(data: dict[str, Any], season: int) -> list[dict[str, Any]]:
    games = [g for g in data.get("games") or [] if safe_int(g.get("season"), -1) == season]
    games.sort(key=lambda g: (safe_int(g.get("day")), str(g.get("gid"))))
    return games


def _fmt_big(value: float) -> str:
    return f"{int(round(value)):,}"


def season_numbers(data: dict[str, Any], season: int) -> list[tuple[str, str, str]]:
    """(value, label, sublabel) tiles for the "season in numbers" slide.

    Totals come from the regular-season team stat rows (retained for every
    season); the overtime count needs the game log so it only appears when
    those games are still in the export.
    """
    pts = threes = tds = gp = 0.0
    for team in data.get("teams") or []:
        for row in team.get("stats") or []:
            if isinstance(row, dict) and row.get("season") == season and not row.get("playoffs"):
                pts += safe_float(row.get("pts"))
                threes += safe_float(row.get("tp"))
                tds += safe_float(row.get("td"))
                gp += safe_float(row.get("gp"))
    tiles: list[tuple[str, str, str]] = []
    if gp > 0:
        tiles.append((_fmt_big(gp / 2), "games played", "regular season"))
    if pts > 0:
        tiles.append((_fmt_big(pts), "points scored", "regular season"))
    if threes > 0:
        tiles.append((_fmt_big(threes), "threes made", "regular season"))
    games = _season_games(data, season)
    if games:
        ot = sum(1 for g in games if safe_int(g.get("overtimes")) > 0)
        tiles.append((_fmt_big(ot), "overtime games", "incl. playoffs"))
    if tds > 0:
        tiles.append((_fmt_big(tds), "triple-doubles", "regular season"))
    return tiles


def best_fantasy_line(data: dict[str, Any], season: int) -> dict[str, Any] | None:
    """The season's best single-game fantasy line (FPTS, incl. playoffs).

    Deterministic: games iterate in (day, gid) order and only a strictly
    better score replaces the champion line, so ties keep the earliest game.
    """
    best: dict[str, Any] | None = None
    for game in _season_games(data, season):
        boxes = game.get("teams") or []
        for i, team_box in enumerate(boxes):
            opp_box = boxes[1 - i] if len(boxes) == 2 else {}
            for box in team_box.get("players") or []:
                fpts = fantasy_pts(box)
                if fpts is None:
                    continue
                if best is None or fpts > best["fpts"]:
                    best = {
                        "fpts": fpts,
                        "box": box,
                        "gid": game.get("gid"),
                        "playoffs": bool(game.get("playoffs")),
                        "day": safe_int(game.get("day")),
                        "tid": safe_int(team_box.get("tid"), -1),
                        "opp_tid": safe_int(opp_box.get("tid"), -1) if opp_box else -1,
                    }
    return best


def _per_game_value(row: dict[str, Any], key: str) -> float | None:
    gp = stat_gp(row)
    if gp <= 0:
        return None
    total = total_rebounds(row) if key == "trb" else safe_float(row.get(key))
    return total / gp


def leaders_wall(data: dict[str, Any], season: int) -> list[dict[str, Any]]:
    """League leaders for the wall slide: one entry per LEADER_KEYS stat.

    Matches each player's per-game value against the export's own
    ``seasonLeaders`` figure (so BBGM's qualification rules apply); if a stat
    has no stored leader, falls back to the best mark among players with at
    least half a season played.
    """
    led = led_league(data).get(season) or {}
    candidates: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for player in sorted(
        (p for p in data.get("players") or [] if isinstance(p, dict)),
        key=lambda p: (player_name(p), safe_int(p.get("pid"))),
    ):
        row = season_regular_stat(player, season)
        if row and stat_gp(row) > 0:
            candidates.append((player, row))
    if not candidates:
        return []
    max_gp = max(stat_gp(row) for _, row in candidates)
    out: list[dict[str, Any]] = []
    for key, label, word in LEADER_KEYS:
        target = led.get(key)
        chosen: tuple[dict[str, Any], float] | None = None
        if target is not None:
            for player, row in candidates:
                value = _per_game_value(row, key)
                if value is not None and abs(value - target) <= 1e-6:
                    chosen = (player, value)
                    break
        if chosen is None:
            qualified = [
                (player, row) for player, row in candidates if stat_gp(row) >= max_gp / 2
            ] or candidates
            ranked = sorted(
                ((player, _per_game_value(row, key) or 0.0) for player, row in qualified),
                key=lambda pv: (-pv[1], player_name(pv[0])),
            )
            if not ranked or ranked[0][1] <= 0:
                continue
            chosen = ranked[0]
        out.append({"key": key, "label": label, "word": word, "player": chosen[0], "value": chosen[1]})
    return out


def team_top_performer(data: dict[str, Any], season: int, tid: int) -> dict[str, Any] | None:
    """The team's best season-total fantasy scorer (its stats while on this team)."""
    best: dict[str, Any] | None = None
    for player in sorted(
        (p for p in data.get("players") or [] if isinstance(p, dict)),
        key=lambda p: (player_name(p), safe_int(p.get("pid"))),
    ):
        rows = [
            s for s in player.get("stats") or []
            if isinstance(s, dict) and s.get("season") == season and not s.get("playoffs")
            and safe_int(s.get("tid"), -9) == tid and safe_float(s.get("gp")) > 0
        ]
        if not rows:
            continue
        agg = dict(rows[0]) if len(rows) == 1 else combine_stat_rows(rows)
        fpts = fantasy_pts(agg)
        if fpts is None:
            continue
        if best is None or fpts > best["fpts"]:
            best = {"player": player, "row": agg, "fpts": fpts}
    return best


def _default_linkable_gids(data: dict[str, Any]) -> set:
    """Which game pages exist in the current build (mirrors build.py today):
    the latest game season's completed regular-season games plus every
    completed game of the current season. Integration may pass the real set."""
    gids = set()
    latest = latest_game_season(data)
    if latest is not None:
        for item in completed_game_items(data, latest, playoffs=False):
            if item.get("gid") is not None:
                gids.add(str(item.get("gid")))
    for item in completed_game_items(data, current_season(data), playoffs=None):
        if item.get("gid") is not None:
            gids.add(str(item.get("gid")))
    return gids


# ---------------------------------------------------------------------------
# HTML fragments
# ---------------------------------------------------------------------------


def _portrait(player: dict[str, Any], cls: str, root: str = "") -> str:
    try:
        return portrait_html(player, cls=cls, root=root)
    except TypeError:
        # portraits.portrait_html's monogram branch currently passes a ``size``
        # kwarg monogram_svg does not accept; stay resilient until that lands.
        mono = monogram_svg(
            initials(player), player.get("tid"),
            jersey_number=player.get("jerseyNumber"), css_class="monogram",
        )
        return (
            f'<span class="{esc(cls)} portrait-monogram" role="img" '
            f'aria-label="{esc(player_name(player))}">{mono}</span>'
        )


def _player_link(player: dict[str, Any], root: str = "") -> str:
    # Pages exist only for active (non-retired, rostered or FA) players.
    if player.get("retiredYear") is None and safe_int(player.get("tid"), RETIRED_TID) >= FREE_AGENT_TID:
        return f'<a href="{player_url(player, root)}">{esc(player_name(player))}</a>'
    return esc(player_name(player))


def _slide(slide_id: str, title: str, body: str, cls: str = "") -> str:
    cls_attr = f"wr-slide {cls}".strip()
    return (
        f'<section class="{cls_attr}" id="{esc(slide_id)}" data-wr-title="{esc(title)}" '
        f'aria-label="{esc(title)}"><div class="wr-inner">{body}</div></section>'
    )


def _pennant_svg(tid: Any, season: int) -> str:
    """Championship pennant in the team's colors (site version — theme vars)."""
    return (
        f'<svg class="wr-pennant" viewBox="0 0 120 160" style="{team_css_vars(tid)}" role="img" '
        f'aria-label="Season {season} championship banner" xmlns="http://www.w3.org/2000/svg">'
        '<path d="M8 6h104v92L60 152 8 98Z" fill="var(--team-primary)" '
        'stroke="var(--team-secondary)" stroke-width="4" stroke-linejoin="round"/>'
        '<path d="M20 18h80v6H20z" fill="var(--team-secondary)" opacity=".85"/>'
        f'<text x="60" y="58" text-anchor="middle" font-weight="700" font-size="28" '
        f'fill="var(--team-on-primary)">{season}</text>'
        '<text x="60" y="84" text-anchor="middle" font-weight="700" font-size="15" '
        'letter-spacing="2" fill="var(--team-on-primary)">CHAMPS</text>'
        "</svg>"
    )


def _title_slide(season: int) -> str:
    return _slide(
        "wr-title",
        f"SMP Wrapped {season}",
        f"""
        <p class="wr-eyebrow">SMP Basketball League</p>
        <h1 class="wr-huge">Wrapped<span class="wr-accent">’{str(season)[-2:]}</span></h1>
        <p class="wr-sub">The season {season} recap.</p>
        <p class="wr-scroll-hint" aria-hidden="true">↓</p>
        """,
        cls="wr-slide-title",
    )


def _numbers_slide(data: dict[str, Any], season: int) -> str:
    tiles = season_numbers(data, season)
    if not tiles:
        return ""
    tile_html = "".join(
        f'<div class="wr-stat"><span class="wr-big">{esc(value)}</span>'
        f'<span class="wr-label">{esc(label)}</span>'
        f'<span class="wr-sublabel">{esc(sub)}</span></div>'
        for value, label, sub in tiles
    )
    return _slide(
        "wr-numbers",
        "The season in numbers",
        f"""
        <h2 class="wr-h2">The season in numbers</h2>
        <div class="wr-stats">{tile_html}</div>
        """,
    )


def _fantasy_slide(data: dict[str, Any], season: int, teams_by_tid: dict[int, dict[str, Any]],
                   all_players_by_pid: dict[int, dict[str, Any]], linkable_gids: set) -> str:
    best = best_fantasy_line(data, season)
    if best is None:
        return ""
    box = best["box"]
    player = all_players_by_pid.get(safe_int(box.get("pid"), -1))
    name_html = _player_link(player) if player else esc(box.get("name") or "Unknown")
    portrait = _portrait(player, "wr-portrait") if player else ""
    trb = safe_float(box.get("orb")) + safe_float(box.get("drb"))
    line = " · ".join([
        f"{fmt_number(box.get('pts'), 0)} PTS",
        f"{fmt_number(trb, 0)} TRB",
        f"{fmt_number(box.get('ast'), 0)} AST",
        f"{fmt_number(box.get('stl'), 0)} STL",
        f"{fmt_number(box.get('blk'), 0)} BLK",
    ])
    abbrev = team_abbrev(teams_by_tid.get(best["tid"]), best["tid"])
    opp = team_abbrev(teams_by_tid.get(best["opp_tid"]), best["opp_tid"])
    context = f"{esc(abbrev)} vs {esc(opp)} · Day {best['day']}" + (" · Playoffs" if best["playoffs"] else "")
    if best["gid"] is not None and str(best["gid"]) in linkable_gids:
        game_link = (
            f'<p class="wr-share"><a class="button-link" '
            f'href="games/{game_slug_from_gid(best["gid"])}.html">Relive the box score</a></p>'
        )
    else:
        game_link = ""
    return _slide(
        "wr-fantasy",
        "Best fantasy line",
        f"""
        <h2 class="wr-h2">Fantasy line of the year</h2>
        <div class="wr-feature">
          {portrait}
          <div class="wr-feature-copy">
            <p class="wr-big wr-tabular">{fmt_number(best['fpts'], 0)} <span class="wr-unit">FPTS</span></p>
            <p class="wr-feature-name">{name_html}</p>
            <p class="wr-sub">{line}</p>
            <p class="wr-sublabel">{context}</p>
          </div>
        </div>
        {game_link}
        <p class="wr-footnote">Fantasy points across every box score, playoffs included.</p>
        """,
    )


def _leaders_slide(data: dict[str, Any], season: int, teams_by_tid: dict[int, dict[str, Any]]) -> str:
    entries = leaders_wall(data, season)
    if not entries:
        return ""
    cards = []
    for entry in entries:
        player = entry["player"]
        abbrev = team_abbrev(teams_by_tid.get(safe_int(player.get("tid"), -1)), player.get("tid"))
        cards.append(
            f'<div class="wr-leader">'
            f'{_portrait(player, "wr-portrait wr-portrait-sm")}'
            f'<div><p class="wr-leader-value wr-tabular">{fmt_number(entry["value"], 1)} '
            f'<span class="wr-unit">{esc(entry["label"])}</span></p>'
            f'<p class="wr-leader-name">{_player_link(player)}</p>'
            f'<p class="wr-sublabel">{esc(entry["word"])} · {esc(abbrev)}</p></div></div>'
        )
    return _slide(
        "wr-leaders",
        "League leaders",
        f"""
        <h2 class="wr-h2">The leaders wall</h2>
        <div class="wr-leaders">{''.join(cards)}</div>
        """,
    )


def _playoff_slide(data: dict[str, Any], season: int, teams_by_tid: dict[int, dict[str, Any]]) -> str:
    rounds = playoff_rounds(data, season)
    if not rounds:
        return ""
    n_rounds = len(rounds)
    round_blocks = []
    for i, series_list in enumerate(rounds):
        lines = []
        for series in series_list:
            sides = []
            for side_key in ("home", "away"):
                side = series.get(side_key) or {}
                tid = safe_int(side.get("tid"), -1)
                team = teams_by_tid.get(tid)
                label = f'<a href="{team_url(team)}">{esc(team_abbrev(team, tid))}</a>' if team else esc(str(tid))
                sides.append({
                    "tid": tid,
                    "seed": safe_int(side.get("seed"), 0),
                    "won": safe_int(side.get("won"), 0),
                    "label": label,
                })
            if len(sides) < 2:
                continue
            a, b = sides
            winner = a if a["won"] >= b["won"] else b
            loser = b if winner is a else a
            lines.append(
                f'<li><span class="wr-seed">{winner["seed"]}</span> <strong>{winner["label"]}</strong> '
                f'<span class="wr-series-score wr-tabular">{winner["won"]}–{loser["won"]}</span> '
                f'<span class="wr-seed">{loser["seed"]}</span> {loser["label"]}</li>'
            )
        round_blocks.append(
            f'<div class="wr-round"><h3>{esc(_round_name(i, n_rounds))}</h3>'
            f'<ul class="wr-series-list">{"".join(lines)}</ul></div>'
        )
    return _slide(
        "wr-playoffs",
        "The playoff story",
        f"""
        <h2 class="wr-h2">The playoff story</h2>
        <div class="wr-bracket">{''.join(round_blocks)}</div>
        """,
    )


def _champion_slide(data: dict[str, Any], season: int, teams_by_tid: dict[int, dict[str, Any]],
                    all_players_by_pid: dict[int, dict[str, Any]]) -> str:
    champ_tid = season_champion_tid(data, season)
    if champ_tid is None:
        return ""
    team = teams_by_tid.get(champ_tid)
    if not team:
        return ""
    srow = latest_team_season(team, season)
    record = f"{safe_int(srow.get('won'))}–{safe_int(srow.get('lost'))}"
    finals_mvp_html = ""
    for award in data.get("awards") or []:
        if isinstance(award, dict) and safe_int(award.get("season"), -1) == season:
            fmvp = award.get("finalsMvp") or {}
            player = all_players_by_pid.get(safe_int(fmvp.get("pid"), -1))
            if player or fmvp.get("name"):
                name_html = _player_link(player) if player else esc(fmvp.get("name"))
                line = " · ".join([
                    f"{fmt_number(fmvp.get('pts'), 1)} PPG",
                    f"{fmt_number(fmvp.get('trb'), 1)} RPG",
                    f"{fmt_number(fmvp.get('ast'), 1)} APG",
                ])
                portrait = _portrait(player, "wr-portrait wr-portrait-sm") if player else ""
                finals_mvp_html = (
                    f'<div class="wr-finals-mvp">{portrait}<div>'
                    f'<p class="wr-label">{crest_svg("finals_mvp", css_class="crest crest--gold")} Finals MVP</p>'
                    f'<p class="wr-leader-name">{name_html}</p>'
                    f'<p class="wr-sublabel">{line} in the Finals</p></div></div>'
                )
            break
    return _slide(
        "wr-champion",
        "Your champions",
        f"""
        <div class="wr-champ" style="{team_css_vars(champ_tid)}">
          {_pennant_svg(champ_tid, season)}
          <div class="wr-champ-copy">
            <p class="wr-eyebrow">{crest_svg("champion", css_class="crest crest--gold")} Season {season} champions</p>
            <h2 class="wr-huge wr-champ-name"><a href="{team_url(team)}">{esc(team_full_name(team))}</a></h2>
            <p class="wr-sub">Finished {record} and raised the banner.</p>
            {finals_mvp_html}
          </div>
        </div>
        """,
        cls="wr-slide-champion",
    )


def _team_slide(data: dict[str, Any], season: int, team: dict[str, Any], rank: int,
                n_rounds: int) -> str:
    tid = safe_int(team.get("tid"), -1)
    abbrev = team_abbrev(team, tid)
    srow = latest_team_season(team, season)
    record = f"{safe_int(srow.get('won'))}–{safe_int(srow.get('lost'))}"
    result = playoff_result_label(srow.get("playoffRoundsWon"), n_rounds)
    seed = _team_seed(data, season, tid)
    seed_html = f'<span class="wr-sublabel">#{seed} seed</span>' if seed else '<span class="wr-sublabel">regular season</span>'
    best = team_top_performer(data, season, tid)
    if best:
        row = best["row"]
        gp = stat_gp(row) or 1.0
        line = " · ".join([
            f"{fmt_number(safe_float(row.get('pts')) / gp, 1)} PPG",
            f"{fmt_number(total_rebounds(row) / gp, 1)} RPG",
            f"{fmt_number(safe_float(row.get('ast')) / gp, 1)} APG",
        ])
        performer_html = f"""
          <div class="wr-performer">
            {_portrait(best['player'], 'wr-portrait wr-portrait-sm')}
            <div>
              <p class="wr-label">Top performer</p>
              <p class="wr-performer-name">{_player_link(best['player'])}</p>
              <p class="wr-sublabel">{line} · {fmt_number(best['fpts'], 0)} FPTS</p>
            </div>
          </div>
        """
    else:
        performer_html = ""
    share_href = f"assets/wrapped/{season}-{esc(abbrev)}.svg"
    return _slide(
        f"wr-team-{abbrev.lower()}",
        f"{team_full_name(team)} wrapped",
        f"""
        <article class="wr-team-card" style="{team_css_vars(tid)}">
          <header class="wr-team-head">
            {monogram_svg(abbrev, tid, css_class="monogram monogram--lg wr-team-mono")}
            <div>
              <p class="wr-eyebrow">Season {season} · #{rank} of {len(active_teams_for_season(data.get('teams') or [], season))}</p>
              <h2 class="wr-team-name"><a href="{team_url(team)}">{esc(team_full_name(team))}</a></h2>
            </div>
          </header>
          <div class="wr-team-stats">
            <div class="wr-team-stat"><span class="wr-big wr-tabular">{record}</span><span class="wr-label">record</span></div>
            <div class="wr-team-stat"><span class="wr-team-result">{esc(result)}</span>{seed_html}</div>
          </div>
          {performer_html}
          <p class="wr-share"><a class="button-link wr-share-link" href="{share_href}" download>Save / share card</a></p>
        </article>
        """,
        cls="wr-slide-team",
    )


def _outro_slide(season: int) -> str:
    return _slide(
        "wr-outro",
        "That's a wrap",
        f"""
        <h2 class="wr-huge">That’s a wrap on {season}.</h2>
        <p class="wr-sub">The full record lives in the archives.</p>
        <p class="wr-share"><a class="button-link" href="history.html">Browse league history</a>
        <a class="button-link" href="index.html">Back to today</a></p>
        """,
        cls="wr-slide-title",
    )


# The deck's running order, as prose. Shown on the pre-champion page so the
# slot each slide will occupy is legible before any of them can be built; keep
# in sync with the ``slides`` list in render_wrapped_page.
_SLIDE_PREVIEW = [
    ("The season in numbers", "games, points, threes, overtimes and triple-doubles across the year"),
    ("Fantasy line of the year", "the single best box score anyone posted, playoffs included"),
    ("The leaders wall", "points, rebounds, assists, steals and blocks"),
    ("The playoff story", "every series, round by round, with seeds"),
    ("Your champions", "the banner, the final record and the Finals MVP"),
]


def _empty_state_page(teams: list[dict[str, Any]], season: int) -> str:
    """The page before any season has finished.

    A one-line "not yet" card left the page 74px tall on an otherwise blank
    screen. The season is still unplayed, so there is nothing to recap and
    nothing worth inventing — instead the page states the gate once and then
    lists the deck it will build, which is the only useful thing it knows.
    """
    n_teams = len([t for t in teams if t.get("tid") is not None and not t.get("disabled")])
    preview = list(_SLIDE_PREVIEW)
    preview.append((
        f"{n_teams} team cards" if n_teams else "A card for every team",
        "record, playoff finish and top performer — each one a downloadable share card",
    ))
    rows = "".join(
        f'<li><span class="wr-preview-name">{esc(name)}</span>'
        f'<span class="wr-preview-note muted">{esc(note)}</span></li>'
        for name, note in preview
    )
    body = f"""
    <section class="page-hero">
      <div>
        <p class="eyebrow">SMP Wrapped</p>
        <h1>Wrapped ’{str(season)[-2:]} opens when the season closes</h1>
      </div>
      <div class="muted">{esc(season)} season</div>
    </section>
    <section class="card wr-waiting">
      <p class="empty-state">Wrapped recaps a finished season, and {esc(season)} has not crowned a champion
      yet. The page rebuilds itself from the export the day the Finals end — nothing here is hand-written.</p>
      <div class="section-title-row"><h2>The deck it will build</h2></div>
      <ol class="wr-preview">{rows}</ol>
      <p class="wr-waiting-links">
        <a class="button-link" href="index.html">Back to today</a>
        <a class="button-link" href="schedule.html">The {esc(season)} schedule</a>
        <a class="button-link" href="history.html">League history</a>
      </p>
    </section>
    """
    return page_html("SMP Wrapped", body, teams, root="", active="wrapped")


# ---------------------------------------------------------------------------
# Page + share-card entry points
# ---------------------------------------------------------------------------


def render_wrapped_page(data: dict[str, Any], teams: list[dict[str, Any]],
                        linkable_gids: Optional[set] = None) -> str:
    season = newest_completed_season(data)
    if season is None:
        return _empty_state_page(teams, current_season(data))
    if linkable_gids is None:
        linkable_gids = _default_linkable_gids(data)
    teams_by_tid = {safe_int(t.get("tid"), -1): t for t in teams if t.get("tid") is not None}
    all_players_by_pid = {
        safe_int(p.get("pid"), -1): p for p in data.get("players") or [] if p.get("pid") is not None
    }
    season_teams = active_teams_for_season(teams, season)
    order = standings_order(season_teams, season)
    ordered_teams = [teams_by_tid[tid] for tid in order if tid in teams_by_tid]
    n_rounds = len(playoff_rounds(data, season))

    slides = [
        _title_slide(season),
        _numbers_slide(data, season),
        _fantasy_slide(data, season, teams_by_tid, all_players_by_pid, linkable_gids),
        _leaders_slide(data, season, teams_by_tid),
        _playoff_slide(data, season, teams_by_tid),
        _champion_slide(data, season, teams_by_tid, all_players_by_pid),
    ]
    slides.extend(
        _team_slide(data, season, team, rank, n_rounds)
        for rank, team in enumerate(ordered_teams, 1)
    )
    slides.append(_outro_slide(season))

    body = f"""
    <div class="wr-deck" data-wrapped-deck role="region" aria-label="SMP Wrapped, season {season}">
      {''.join(s for s in slides if s)}
    </div>
    """
    return page_html(f"SMP Wrapped {season}", body, teams, root="", active="wrapped")


def render_wrapped(data: dict[str, Any], teams: list[dict[str, Any]],
                   linkable_gids: Optional[set] = None) -> dict[str, str]:
    """Build entry point: {output_filename: html}."""
    return {"wrapped.html": render_wrapped_page(data, teams, linkable_gids=linkable_gids)}


# ---------------------------------------------------------------------------
# Share-card SVGs (standalone — hardcoded colors by design; they get pasted
# into chats far away from the site's stylesheet)
# ---------------------------------------------------------------------------

_CARD_FONT = "'Helvetica Neue',Helvetica,Arial,sans-serif"


def _sx(value: Any) -> str:
    return html_lib.escape(str(value), quote=True)


def team_share_card_svg(data: dict[str, Any], team: dict[str, Any], season: int,
                        rank: int, n_teams: int, n_rounds: int) -> str:
    tid = safe_int(team.get("tid"), -1)
    ident = team_identity(tid)
    primary, secondary, on_primary = ident["primary"], ident["secondary"], ident["on_primary"]
    abbrev = team_abbrev(team, tid)
    srow = latest_team_season(team, season)
    record = f"{safe_int(srow.get('won'))}–{safe_int(srow.get('lost'))}"
    result = playoff_result_label(srow.get("playoffRoundsWon"), n_rounds)
    seed = _team_seed(data, season, tid)
    result_line = f"{result} · #{seed} seed" if seed else result
    region = str(team.get("region") or "").strip()
    name = str(team.get("name") or "").strip()

    best = team_top_performer(data, season, tid)
    if best:
        row = best["row"]
        gp = stat_gp(row) or 1.0
        performer_name = player_name(best["player"])
        performer_line = (
            f"{safe_float(row.get('pts')) / gp:.1f} PPG · "
            f"{total_rebounds(row) / gp:.1f} RPG · "
            f"{safe_float(row.get('ast')) / gp:.1f} APG · "
            f"{best['fpts']:,.0f} FPTS"
        )
    else:
        performer_name, performer_line = "—", ""

    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1200 630" width="1200" height="630" '
        f'role="img" aria-label="{_sx(team_full_name(team))} — SMP Wrapped, season {season}">'
        f'<rect width="1200" height="630" fill="{primary}"/>'
        # giant abbrev watermark
        f'<text x="1176" y="600" text-anchor="end" font-family="{_CARD_FONT}" font-weight="800" '
        f'font-size="400" fill="{on_primary}" opacity="0.07">{_sx(abbrev)}</text>'
        # top + bottom accent bars
        f'<rect width="1200" height="10" fill="{secondary}"/>'
        f'<rect y="620" width="1200" height="10" fill="{secondary}"/>'
        # eyebrow
        f'<text x="72" y="100" font-family="{_CARD_FONT}" font-weight="700" font-size="30" '
        f'letter-spacing="6" fill="{secondary}">SMP WRAPPED · SEASON {season}</text>'
        # team name (two lines)
        f'<text x="72" y="186" font-family="{_CARD_FONT}" font-weight="800" font-size="74" '
        f'fill="{on_primary}">{_sx(region)}</text>'
        f'<text x="72" y="264" font-family="{_CARD_FONT}" font-weight="800" font-size="74" '
        f'fill="{on_primary}">{_sx(name)}</text>'
        # record + finish
        f'<text x="72" y="404" font-family="{_CARD_FONT}" font-weight="800" font-size="118" '
        f'fill="{on_primary}">{_sx(record)}</text>'
        f'<text x="72" y="452" font-family="{_CARD_FONT}" font-weight="600" font-size="32" '
        f'fill="{secondary}">{_sx(result_line)} · #{rank} of {n_teams}</text>'
        # top performer block
        f'<text x="72" y="524" font-family="{_CARD_FONT}" font-weight="700" font-size="24" '
        f'letter-spacing="4" fill="{secondary}">TOP PERFORMER</text>'
        f'<text x="72" y="566" font-family="{_CARD_FONT}" font-weight="800" font-size="40" '
        f'fill="{on_primary}">{_sx(performer_name)}</text>'
        f'<text x="72" y="600" font-family="{_CARD_FONT}" font-weight="500" font-size="26" '
        f'fill="{on_primary}" opacity="0.82">{_sx(performer_line)}</text>'
        # roundel top-right
        f'<circle cx="1078" cy="120" r="60" fill="none" stroke="{secondary}" stroke-width="6"/>'
        f'<text x="1078" y="122" text-anchor="middle" dominant-baseline="central" '
        f'font-family="{_CARD_FONT}" font-weight="800" font-size="40" '
        f'fill="{on_primary}">{_sx(abbrev)}</text>'
        "</svg>"
    )


def emit_wrapped_cards(out_dir: Union[str, Path], data: dict[str, Any],
                       teams: list[dict[str, Any]]) -> list[Path]:
    """Write one standalone share-card SVG per team for the wrapped season to
    ``<out_dir>/assets/wrapped/{season}-{abbrev}.svg``. Returns the written
    paths (empty when no season has completed playoffs yet). Deterministic."""
    season = newest_completed_season(data)
    if season is None:
        return []
    dest = Path(out_dir) / "assets" / "wrapped"
    dest.mkdir(parents=True, exist_ok=True)
    season_teams = active_teams_for_season(teams, season)
    teams_by_tid = {safe_int(t.get("tid"), -1): t for t in season_teams if t.get("tid") is not None}
    order = standings_order(season_teams, season)
    n_rounds = len(playoff_rounds(data, season))
    written: list[Path] = []
    for rank, tid in enumerate(order, 1):
        team = teams_by_tid.get(tid)
        if not team:
            continue
        svg = team_share_card_svg(data, team, season, rank, len(order), n_rounds)
        path = dest / f"{season}-{team_abbrev(team, tid)}.svg"
        path.write_text(svg, encoding="utf-8")
        written.append(path)
    return written
