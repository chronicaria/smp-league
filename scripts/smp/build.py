from __future__ import annotations

import argparse
import json
import re
import shutil
from pathlib import Path
from typing import Any

from .core import (
    ALL_PLAYERS_BY_PID,
    NAV_LEAGUE,
    SITE_META,
    active_players,
    latest_game_season,
    register_site_meta,
    active_teams_for_season,
    build_game_logs,
    completed_game_items,
    current_season,
    draft_prospects,
    free_agents,
    game_slug_from_gid,
    is_completed_game_item,
    normalize_positions,
    phase_value,
    player_name,
    player_slug,
    player_url,
    safe_int,
    schedule_items_for_page,
    score_items_for_page,
    standings_order,
    team_abbrev,
    team_abbrev_for_tid,
    team_full_name,
    team_slug,
    team_sort_key,
    team_url,
)

from .finance import compute_league_finances

from .simmodel import league_sim

from .pages.home import render_home_page

from .pages.team import (
    render_team_finances_page,
    render_team_games_page,
    render_team_history_page,
    render_team_roster_page,
)

from .pages.player import render_player_pages

from .pages.game import render_game_page

from .pages.league import (
    render_draft_page,
    render_free_agency_page,
    render_history_page,
    render_players_index,
    render_records_page,
    render_schedule_page,
)

from .pages.compare import render_compare_page

from .pages.trade import render_trade_page

from .pages.extras import render_extras_pages

from .pages.wrapped import emit_wrapped_cards, render_wrapped

from .pages.lineup import render_lineup_pages

from .pages.simulator import render_simulator_pages

from .appdata import write_app_data

from .derived import feats_index

from .ledger import load_odds_history, update_odds_ledger

from .portraits import emit_faces

# Static assets: split from the old inline stylesheet()/javascript() strings.
# Concatenated in this exact order; the result is byte-identical to the old output.
_STATIC_DIR = Path(__file__).resolve().parent / "static"

CSS_FILES = [
    "base.css",
    "nav.css",
    "layout.css",
    "tables.css",
    "cards.css",
    "identity.css",
    "scatter.css",
    "player.css",
    "team.css",
    "game.css",
    "home.css",
    "team-extras.css",
    "charts.css",
    "history.css",
    "league.css",
    "extras.css",
    "wrapped.css",
    "search.css",
    "misc.css",
    "apps.css",
    "tools.css",
    "mobile.css",
    "print.css",
]

# core.js opens a shared IIFE that charts.js closes; fragments in between run
# inside it (theme.js must immediately follow core.js — later fragments read its
# consts). Files after charts.js are standalone self-contained IIFEs.
JS_FILES = [
    "core.js",
    "theme.js",
    "scatter.js",
    "hover.js",
    "home.js",
    "search.js",
    "tables.js",
    "nav.js",
    "tabs.js",
    "player.js",
    "charts.js",
    "team.js",
    "league.js",
    "compare.js",
    "trade-extras.js",
    "lineup.js",
    "simulator.js",
    "wrapped.js",
]


def stylesheet() -> str:
    return "".join((_STATIC_DIR / "css" / name).read_text(encoding="utf-8") for name in CSS_FILES)


def javascript() -> str:
    return "".join((_STATIC_DIR / "js" / name).read_text(encoding="utf-8") for name in JS_FILES)



def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


# Day exports are named "2026_day1.json"; the season prefix is optional so the
# older bare "day1.json" form still matches.
DAY_EXPORT_RE = re.compile(r"(?:(?P<season>\d{4})_)?day(?P<day>\d+)")


def previous_day_json(json_path: Path) -> Path | None:
    """Find the closest earlier day export next to the given one.

    The season prefix has to match, so day-over-day standings movement never
    compares the first day of a season against the last day of the one before.
    """
    match = DAY_EXPORT_RE.fullmatch(json_path.stem)
    if not match:
        return None
    prefix = f"{match.group('season')}_" if match.group("season") else ""
    day = int(match.group("day"))
    for prev_day in range(day - 1, max(-1, day - 15), -1):
        candidate = json_path.with_name(f"{prefix}day{prev_day}.json")
        if candidate.exists():
            return candidate
    return None


# Pristine copy of the nav's League group, so gating a page off the nav below is
# idempotent across repeated generate_site() calls in one process.
NAV_LEAGUE_ALL = list(NAV_LEAGUE)


def generate_site(
    json_path: Path,
    out_dir: Path,
    start_season: int = 2026,
    clean: bool = False,
    schedule_season: int | None = None,
    schedule_days: int | None = None,
    prev_json_path: Path | None = None,
) -> dict[str, int | str]:
    data = json.loads(json_path.read_text(encoding="utf-8"))
    normalize_positions(data)
    register_site_meta(data, json_path.name)
    season = current_season(data)
    teams = sorted(data.get("teams", []), key=team_sort_key)
    players = active_players(data)
    fa_players = free_agents(data)
    ga = data.get("gameAttributes") or {}
    ALL_PLAYERS_BY_PID.clear()
    ALL_PLAYERS_BY_PID.update({safe_int(p.get("pid")): p for p in data.get("players", []) if p.get("pid") is not None})
    if prev_json_path is None:
        prev_json_path = previous_day_json(json_path)
    if prev_json_path and prev_json_path.exists():
        try:
            prev_data = json.loads(prev_json_path.read_text(encoding="utf-8"))
            prev_season = current_season(prev_data)
            prev_teams = sorted(prev_data.get("teams", []), key=team_sort_key)
            order = standings_order(active_teams_for_season(prev_teams, prev_season), prev_season)
            SITE_META["prev_ranks"] = {tid: rank for rank, tid in enumerate(order, 1)}
        except Exception:
            SITE_META["prev_ranks"] = None
    else:
        SITE_META["prev_ranks"] = None
    SITE_META["season"] = season
    SITE_META["day"] = max((safe_int(g.get("day")) for g in data.get("games", []) if g.get("season") == season), default=0)

    # Rivalries are head-to-head history and nothing else: with no games played the
    # grid is 90 cells of 0-0 and all 45 pair pages read "these teams have never
    # met", so year one skips them entirely. Every nav surface (header, footer
    # sitemap, command palette) reads NAV_LEAGUE at render time, so dropping the
    # entry here is what keeps the skipped page from being linked as a 404.
    rivalries_ready = bool(data.get("games"))
    NAV_LEAGUE[:] = [entry for entry in NAV_LEAGUE_ALL if rivalries_ready or entry[2] != "rivalries"]

    game_items, score_label = score_items_for_page(data, teams, schedule_season=schedule_season, schedule_days=schedule_days)
    schedule_items, schedule_label = schedule_items_for_page(data, teams, schedule_season=schedule_season, schedule_days=schedule_days)

    if clean and out_dir.exists():
        if out_dir.resolve() in {Path("/").resolve(), Path.cwd().resolve()}:
            raise RuntimeError(f"Refusing to clean unsafe output directory: {out_dir}")
        shutil.rmtree(out_dir)

    out_dir.mkdir(parents=True, exist_ok=True)
    write_text(out_dir / "assets" / "styles.css", stylesheet())
    write_text(out_dir / "assets" / "site.js", javascript())

    teams_by_tid = {int(t.get("tid")): t for t in teams if t.get("tid") is not None}
    search_index = {
        "teams": [
            {"n": team_full_name(t), "t": team_abbrev(t), "u": team_url(t)}
            for t in teams
        ],
        "players": [
            {
                "n": player_name(p),
                "t": team_abbrev_for_tid(p.get("tid"), teams_by_tid) if safe_int(p.get("tid"), -1) >= 0 else "FA",
                "u": player_url(p),
            }
            for p in sorted(players, key=player_name)
        ] + [
            {"n": player_name(p), "t": "Draft", "u": player_url(p)}
            for p in sorted(draft_prospects(data), key=player_name)
        ],
    }
    write_text(out_dir / "assets" / "search-index.json", json.dumps(search_index, separators=(",", ":")))
    emit_faces(out_dir, data.get("players", []))
    write_app_data(out_dir, data, teams=teams, players=players, season=season, start_season=start_season)

    # The ledger lives beside the export it was built from, one file per league.
    # Its append guard is monotonic in (season, phase, games), which a league
    # reboot breaks — SMP II restarts at 2026 and would be refused forever by
    # SMP I's 2031 snapshots. Archiving a finished league moves its exports and
    # its ledger together, so the new league starts from an empty one.
    ledger_path = json_path.parent / "odds_history.json"
    sim_result = league_sim(data, teams, season) or {}
    update_odds_ledger(data, sim_result, path=ledger_path)
    write_text(out_dir / "index.html", render_home_page(data, teams, players, season, start_season, odds_history=load_odds_history(str(ledger_path))))
    write_text(out_dir / "schedule.html", render_schedule_page(data, teams, schedule_season=schedule_season, schedule_days=schedule_days))
    fa_market_year = season + 1 if phase_value(data) >= 8 else season
    write_text(out_dir / "free-agency.html", render_free_agency_page(fa_players, teams, season, start_season, all_players=players, market_year=fa_market_year))
    write_text(out_dir / "players" / "index.html", render_players_index(players, teams, season, start_season, data=data))
    write_text(out_dir / "history.html", render_history_page(data, teams))
    write_text(out_dir / "records.html", render_records_page(data, teams, season, start_season=start_season))
    write_text(out_dir / "draft.html", render_draft_page(data, teams, season))
    write_text(out_dir / "trade.html", render_trade_page(data, teams, players, season))
    write_text(out_dir / "compare.html", render_compare_page(data, teams, players, season, start_season))

    game_logs = build_game_logs(data, season)
    league_fin = compute_league_finances(data, teams, players, season, sim_result.get("teams"))
    for team in teams:
        roster = [player for player in players if player.get("tid") == team.get("tid")]
        slug = team_slug(team)
        tfin = league_fin["teams"].get(safe_int(team.get("tid"), -99))
        write_text(out_dir / "teams" / f"{slug}.html", render_team_roster_page(team, roster, teams, season, start_season, data=data, game_items=game_items, game_logs=game_logs, tfin=tfin))
        write_text(out_dir / "teams" / f"{slug}-games.html", render_team_games_page(team, roster, teams, season, start_season, data=data, game_items=game_items, game_logs=game_logs, tfin=tfin))
        write_text(out_dir / "teams" / f"{slug}-finances.html", render_team_finances_page(team, roster, teams, season, start_season, data=data, tfin=tfin, league_fin=league_fin))
        write_text(out_dir / "teams" / f"{slug}-history.html", render_team_history_page(team, roster, teams, season, start_season, data=data, tfin=tfin))

    def write_player_pages(p: dict[str, Any], log_entries: list[dict[str, Any]] | None) -> None:
        slug = player_slug(p)
        for suffix, html in render_player_pages(p, teams, season, start_season, log_entries=log_entries, data=data).items():
            write_text(out_dir / "players" / f"{slug}{suffix}.html", html)

    prospects = draft_prospects(data)
    for prospect in prospects:
        write_player_pages(prospect, None)

    for player in players:
        write_player_pages(player, game_logs.get(safe_int(player.get("pid"), -1)))

    # Write a page for every game linked from the site: the schedule/team slate (game_items)
    # plus the current season's completed games incl. playoffs (home "Latest Results", the
    # playoff bracket, and records feats all link to these gids), plus the latest completed
    # game season incl. its playoffs (bracket/records/classics links in offseason exports).
    page_items = {str(item.get("gid")): item for item in game_items if item.get("gid") is not None}
    for item in completed_game_items(data, season, playoffs=None):
        page_items.setdefault(str(item.get("gid")), item)
    last_game_season = latest_game_season(data)
    if last_game_season is not None and last_game_season != season:
        for item in completed_game_items(data, last_game_season, playoffs=None):
            page_items.setdefault(str(item.get("gid")), item)
    all_game_pages = list(page_items.values())
    feats = feats_index(data)
    for item in all_game_pages:
        write_text(out_dir / "games" / f"{game_slug_from_gid(item.get('gid'))}.html", render_game_page(item, all_game_pages, teams, players, safe_int(item.get("season"), season), feats_by_gid=feats))

    extras_pages = render_extras_pages(data, teams)
    if not rivalries_ready:
        extras_pages = {name: page for name, page in extras_pages.items() if not name.startswith("rivalries")}
    for name, page in extras_pages.items():
        write_text(out_dir / name, page)
    for name, page in render_wrapped(data, teams, linkable_gids=set(page_items.keys())).items():
        write_text(out_dir / name, page)
    emit_wrapped_cards(out_dir, data, teams)
    for name, page in render_lineup_pages(data, teams, players, season, start_season).items():
        write_text(out_dir / name, page)
    for name, page in render_simulator_pages(data, teams, players, season, start_season).items():
        write_text(out_dir / name, page)

    completed_scores = [item for item in game_items if is_completed_game_item(item)]
    return {
        "season": season,
        "teams": len(teams),
        "players": len(players),
        "free_agents": len(fa_players),
        "team_pages": len(teams),
        "player_pages": len(players),
        "schedule_games": len(schedule_items),
        "score_games": len(game_items),
        "completed_scores": len(completed_scores),
        "game_pages": len(game_items),
        "schedule_label": schedule_label,
        "score_label": score_label,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate a static HTML basketball league site from a JSON export.")
    parser.add_argument("json_file", type=Path, help="Path to the Basketball GM-style JSON file, such as league-data/2026_day1.json")
    parser.add_argument("--out", type=Path, default=Path("site"), help="Output directory for the generated website")
    parser.add_argument("--start-season", type=int, default=2026, help="First season to show on player stat pages")
    parser.add_argument("--schedule-season", type=int, default=None, help="Season to use for Schedule/Scores pages. Defaults to an exported schedule, or the upcoming season during offseason exports.")
    parser.add_argument("--schedule-days", type=int, default=None, help="Optional target number of calendar days for a generated schedule, such as 46.")
    parser.add_argument("--clean", action="store_true", help="Delete the output directory before generating")
    parser.add_argument("--prev", type=Path, default=None, help="Previous export for day-over-day standings movement. Defaults to the closest earlier day*.json.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    summary = generate_site(
        args.json_file,
        args.out,
        start_season=args.start_season,
        clean=args.clean,
        schedule_season=args.schedule_season,
        schedule_days=args.schedule_days,
        prev_json_path=args.prev,
    )
    print(f"Generated site in {args.out.resolve()}")
    print(f"Season: {summary['season']}")
    print(f"Schedule/Scores: {summary['schedule_label']} / {summary['score_label']}")
    print(f"Teams: {summary['teams']}; team pages: {summary['team_pages']}")
    print(f"Players: {summary['players']}; player pages: {summary['player_pages']}; free agents: {summary['free_agents']}")
    print(f"Schedule games: {summary['schedule_games']}; score rows: {summary['score_games']}; completed scores: {summary['completed_scores']}; game pages: {summary['game_pages']}")
