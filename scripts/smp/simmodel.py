from __future__ import annotations

import random
import math
from collections import defaultdict
from typing import Any, Iterable

# Projection engine (faithful zengm port + Monte Carlo). Imported defensively so
# the site still builds if numpy / projections.py is unavailable -- in that case
# projection charts gracefully fall back to the static development chart.
try:
    import projections as _proj
except Exception:  # pragma: no cover - degraded build path
    _proj = None

from .core import (
    SITE_META,
    active_players,
    completed_game_items,
    generated_schedule_items,
    get_attr_value,
    is_completed_game_item,
    latest_rating,
    latest_team_season,
    latest_team_stat,
    raw_schedule_items,
    regular_season_length,
    safe_float,
    safe_int,
    score_items_for_page,
    season_regular_stat,
    stat_gp,
    team_mov,
)


# Free-agent asking-salary model. SMP II prices every contract in the league on one
# exponential curve (scripts/price_contracts.py) -- salary doubles every FA_PRICE_WIDTH
# points of overall, times an age factor -- and a free agent's ask is that same curve.
# A market where the ask and the going rate disagree is not a market: these numbers are
# what the roster next to them was actually paid. All values here are in $M; BBGM stores
# thousands (×1000). The old anchor table was interpolated in "salary score" space and
# tuned to a $300M soft cap; against the $100M hard cap it asked 222% of the league's
# total cap space for the 120 rostered players.
FA_PRICE_PIVOT = 60.0     # ovr at which the curve passes through FA_PRICE_AT_PIVOT
FA_PRICE_WIDTH = 5.0      # the ask doubles every 5 points of overall
# price_contracts.solve_scale() does not choose this, it SOLVES it: the scale that makes
# the best 120 players (10 teams × 12) total 78.5% of the league's $1,000M of cap space.
# $4.27M at 60 ovr is where the SMP II pool lands. Re-solve it (price_contracts.py
# --report prints it) if the talent pool is ever repriced.
FA_PRICE_AT_PIVOT = 4.266
FA_MIN_CONTRACT = 1.0     # gameAttributes.minContract 1000
FA_MAX_CONTRACT = 50.0    # gameAttributes.maxContract 50000
# A short deal on the same player costs more per year -- the team is buying flexibility,
# and length is the only per-year structure BBGM can natively enforce. Mirrors
# price_contracts.DURATION_PREMIUM, continued one step for the 5-year deals quoted here.
FA_DURATION_PREMIUM = {1: 1.25, 2: 1.10, 3: 1.00, 4: 0.95, 5: 0.92}


def fa_age_factor(age: int) -> float:
    """Youth and old age are both discounts (price_contracts.age_factor).

    Unproven upside is the drafter's surplus, decline is the buyer's risk, and
    peak-age players pay full freight for production you can bank on.
    """
    if age <= 21:
        return 0.55
    if age <= 23:
        return 0.70
    if age <= 25:
        return 0.85
    if age <= 31:
        return 1.00
    if age <= 33:
        return 0.90
    if age <= 35:
        return 0.75
    return 0.60


def _fa_curve_millions(ovr: int, age: int) -> float:
    """Unclamped, unrounded market value in $M for one season of this player."""
    return FA_PRICE_AT_PIVOT * (2.0 ** ((ovr - FA_PRICE_PIVOT) / FA_PRICE_WIDTH)) * fa_age_factor(age)


def _fa_round(millions: float) -> float:
    """Clamp to the contract range and round to BBGM's $10K grid."""
    return min(max(round(millions, 2), FA_MIN_CONTRACT), FA_MAX_CONTRACT)


def fa_salary_millions(ovr: int, pot: int, age: int) -> float:
    """Single-year UFA asking salary in $M, clamped to the min/max contract.

    ``pot`` is accepted (and ignored) on purpose: under SMP II pricing potential
    does not move the ask, it moves the contract LENGTH a team is willing to
    offer, and here the caller picks the length -- see fa_salary_by_length.
    """
    return fa_salary_by_length(ovr, pot, age)[0]


def fa_salary_by_length(ovr: int, pot: int, age: int) -> list[float]:
    """Annual asking salary ($M) for 1..5-year deals.

    The curve is age-based, so a longer deal averages the yearly figure as the
    player ages across it (ovr/pot held), then takes that length's duration
    premium. A 34-year-old therefore quotes a steep one-year number and a cheap
    five-year one; a 24-year-old quotes the reverse.
    """
    out = []
    for length in range(1, 6):
        years = [_fa_curve_millions(ovr, age + i) for i in range(length)]
        out.append(_fa_round(sum(years) / len(years) * FA_DURATION_PREMIUM[length]))
    return out


# --- projection-backed development chart ------------------------------------
PROJ_SEASONS_AHEAD = 6
PROJ_N_SIMS = 1000
PROJ_MASTER_SEED = 8675309


def _player_projection(player: dict[str, Any], season: int) -> dict[str, Any] | None:
    """Monte Carlo OVR projection for a player from the current season forward.

    Returns None (caller falls back to the static chart) when projections are
    unavailable: the projection engine/numpy is not importable, the player is
    retired, or there is no current rating row carrying all 15 subratings.
    The seed is derived from the pid so rebuilds are byte-identical.
    """
    if _proj is None:
        return None
    if player.get("retiredYear") is not None:
        return None
    born_year = (player.get("born") or {}).get("year")
    if born_year is None:
        return None
    rows = [r for r in player.get("ratings", []) if isinstance(r.get("season"), int)]
    if not rows:
        return None
    rows.sort(key=lambda r: r["season"])
    cur = next((r for r in rows if r["season"] == season), rows[-1])
    if not all(k in cur for k in _proj.RATINGS):
        return None
    cur_season = int(cur["season"])
    age = cur_season - int(born_year)
    if age < 14 or age > 50:
        return None
    seed = PROJ_MASTER_SEED * 100003 + safe_int(player.get("pid"), 0)
    try:
        sim = _proj.simulate_player(
            cur, age, cur_season,
            seasons_ahead=PROJ_SEASONS_AHEAD, n_sims=PROJ_N_SIMS, seed=seed,
        )
    except Exception:
        return None
    return {"cur_season": cur_season, "age": age, "sim": sim}


# --- team projection --------------------------------------------------------
# Roster-construction floor: a freely-available filler. Only a fallback inside
# league_bench_ovrs, and the literal is mirrored in static/js/lineup.js, so it cannot
# move on its own -- SMP II's real replacement level is far higher (the best undrafted
# player is 59 ovr), but the fallback almost never fires against a full ten rosters.
REPLACEMENT_OVR = 40.0

# Games at which current-season scoring margin carries half the strength weight:
# weight = gp / (gp + SIM_MOV_BLEND_K). At gp=0 (fresh season) strength is 100%
# roster-based; by a full 36-game season MOV carries ~78%. K is denominated in
# games played, not in fraction-of-season, so the shorter SMP II schedule does
# not move it -- twenty games of margin are exactly as noisy either way.
SIM_MOV_BLEND_K = 10.0

# zengm rates a team as a RANK-DECAYED sum over its top ten players, not a flat one
# (team/ovr.basketball.ts, ported at projections.team_ovr): the best man on the roster
# is worth ROTATION_W_A points of scoring margin per point of overall and each slot
# below him is worth exp(ROTATION_W_B) as much, because that is roughly how the engine
# hands out minutes. On a 12-man SMP II roster the top ten take ~94% of them. Using
# these constants is what makes the projected records here agree with the Trade Machine
# and Lineup Lab, which already run this exact formula client-side (trade-extras.js).
ROTATION_SLOTS = 10
ROTATION_W_A = 0.3334
ROTATION_W_B = -0.1609
# 50 is an average player on the engine's rating scale: a rotation of ten 50s projects
# to an even scoring margin, and an impact is the margin a player adds over that.
ROTATION_PAR_OVR = 50.0


def rotation_weight(rank: int) -> float:
    """Scoring margin per point of overall for the ``rank``-th rotation player (0 = best)."""
    return ROTATION_W_A * math.exp(ROTATION_W_B * max(0, rank))


# What a caller with no roster context gets: the average of the ten rotation slots.
MEAN_ROTATION_WEIGHT = sum(rotation_weight(i) for i in range(ROTATION_SLOTS)) / ROTATION_SLOTS


def _player_current_ovr(player: dict[str, Any], season: int) -> int | None:
    """The player's overall this season (the stored value, == player_ovr)."""
    rows = [r for r in player.get("ratings", []) if isinstance(r.get("season"), int)]
    if not rows:
        return None
    rows.sort(key=lambda r: r["season"])
    cur = next((r for r in rows if r["season"] == season), rows[-1])
    v = cur.get("ovr")
    return safe_int(v) if v is not None else None


def current_team_ovr(roster: list[dict[str, Any]], season: int) -> int | None:
    """Raw engine team OVR from a roster's current player overalls (unclamped)."""
    if _proj is None:
        return None
    ovrs = [o for o in (_player_current_ovr(p, season) for p in roster) if o is not None]
    if not ovrs:
        return None
    return _proj.team_ovr(ovrs)


def player_game_impact(player: dict[str, Any], season: int, rank: int | None = None) -> float:
    """Estimated per-game scoring-margin contribution above an average player.

    ``rank`` is the slot the player holds in his team's rotation (0 = best, 9 =
    tenth man). A box-score impact already carries the minutes he actually
    played, so the rank changes nothing there; a rating-only impact has no
    minutes in it at all, so the rank is where they come from. Callers with no
    roster in hand omit ``rank`` and get the average rotation slot -- the right
    sort key, but it understates stars, so sort first and then re-read each
    player at his rank (rotation_impacts does exactly that).
    """
    stat = season_regular_stat(player, season)
    gp = stat_gp(stat)
    mpg = (safe_float(stat.get("min")) / gp) if gp else 0.0
    if gp >= 3 and mpg >= 8:
        bpm = safe_float(stat.get("obpm")) + safe_float(stat.get("dbpm"))
        impact = (bpm + 2.0) * (mpg / 48.0)  # replacement level is roughly -2 BPM
    else:
        rating = latest_rating(player, season)
        weight = MEAN_ROTATION_WEIGHT if rank is None else rotation_weight(rank)
        impact = (safe_float(rating.get("ovr"), 40.0) - ROTATION_PAR_OVR) * weight
    return max(-2.0, min(10.0, impact))


def rotation_impacts(roster: list[dict[str, Any]], season: int) -> list[tuple[dict[str, Any], float]]:
    """The top-``ROTATION_SLOTS`` players and each one's margin contribution at his slot."""
    rotation = sorted(roster, key=lambda p: -player_game_impact(p, season))[:ROTATION_SLOTS]
    return [(p, player_game_impact(p, season, rank)) for rank, p in enumerate(rotation)]


def rotation_strength(roster: list[dict[str, Any]], season: int) -> float:
    """Team scoring-margin signal from a roster as it stands: the rank-weighted rotation sum.

    On a roster with no games played this reproduces zengm's own team rating
    (projections.team_ovr) exactly, up to the constant that centering removes.
    Slots a short roster cannot fill contribute nothing -- they count as an
    average player rather than zengm's 0-overall pad, because an 11-man roster
    is a rotation one man light, not a 30-point underdog.
    """
    return sum(impact for _, impact in rotation_impacts(roster, season))


def playoff_series_lengths(data: dict[str, Any], season: int) -> list[int]:
    """Games in each playoff round, from ``gameAttributes.numGamesPlayoffSeries``.

    SMP II runs [5, 5] — two best-of-fives, three wins to advance — where SMP I
    ran [7, 7]. Both are two rounds, so the field is four teams either way and
    only the series length changed; publishing title odds for a format the league
    does not play is the thing to avoid. Falls back to two best-of-sevens when the
    export carries no usable value.
    """
    lengths = get_attr_value(((data or {}).get("gameAttributes") or {}).get("numGamesPlayoffSeries"), season)
    if isinstance(lengths, list):
        out = [safe_int(value) for value in lengths if safe_int(value) > 0]
        if out:
            return out
    return [7, 7]


def simulate_league(data: dict[str, Any], teams: list[dict[str, Any]], players: list[dict[str, Any]], season: int, sims: int = 10000) -> dict[str, Any]:
    """Monte Carlo the rest of the season and the playoffs.

    Team strength is a roster signal from the CURRENT roster — the rank-weighted
    top-10 rotation (rotation_strength), centered on the league mean — blended
    with THIS season's scoring margin only as games accumulate (MOV weight =
    gp/(gp+SIM_MOV_BLEND_K)). A season with no games played is 100% roster-based;
    last season's margin is never used. Injured rotation players subtract their
    impact until their expected return, so odds dip while stars are out and
    recover as they heal; a twelfth man's absence moves nothing, because the
    rotation closes over him. Trades are picked up automatically because strength
    comes from the roster as it stands today.

    A season that hasn't been played yet starts every team at 0-0 and runs over
    the exported schedule when the export carries one, else a projected
    round-robin.
    """
    fresh = not completed_game_items(data, season, playoffs=False)
    tids = [safe_int(t.get("tid")) for t in teams if t.get("tid") is not None]
    wins0: dict[int, float] = {}
    mov_now: dict[int, float] = {}
    gp_now: dict[int, float] = {}
    for team in teams:
        tid = safe_int(team.get("tid"))
        team_season = latest_team_season(team, season)
        stat = latest_team_stat(team, season)
        wins0[tid] = 0.0 if fresh else safe_float(team_season.get("won"))
        # latest_team_stat falls back to an earlier season's row when this season
        # has no stats yet — never seed strength from last season's margin.
        if safe_int(stat.get("season")) == season:
            gp_now[tid] = safe_float(stat.get("gp"))
            mov_now[tid] = team_mov(stat) or 0.0
        else:
            gp_now[tid] = 0.0
            mov_now[tid] = 0.0

    # Roster strength (healthy) and per-team injured list (impact, games remaining).
    roster_by_tid: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for player in players:
        tid = safe_int(player.get("tid"), -9)
        if tid >= 0:
            roster_by_tid[tid].append(player)
    roster_strength: dict[int, float] = {}
    injured_by_tid: dict[int, list[tuple[float, int]]] = defaultdict(list)
    for tid in tids:
        rotation = rotation_impacts(roster_by_tid.get(tid, []), season)
        roster_strength[tid] = sum(impact for _, impact in rotation)
        for player, impact in rotation:
            injury = player.get("injury") or {}
            games_out = safe_int(injury.get("gamesRemaining"))
            if injury.get("type") and injury.get("type") != "Healthy" and games_out > 0:
                if impact > 0.2:
                    injured_by_tid[tid].append((impact, games_out))
    mean_roster = sum(roster_strength.values()) / len(roster_strength) if roster_strength else 0.0
    base_strength: dict[int, float] = {}
    for tid in tids:
        mov_weight = gp_now[tid] / (gp_now[tid] + SIM_MOV_BLEND_K)
        roster_signal = roster_strength.get(tid, 0.0) - mean_roster
        base_strength[tid] = (1.0 - mov_weight) * roster_signal + mov_weight * mov_now[tid]

    # Remaining schedule in chronological order. Prefer the exported schedule;
    # an unplayed season with none is projected over a generated round-robin.
    remaining: list[tuple[int, int, int, str]] = []

    def collect(items: Iterable[dict[str, Any]]) -> None:
        for item in items:
            if is_completed_game_item(item) or safe_int(item.get("season")) != season:
                continue
            home, away = safe_int(item.get("home_tid")), safe_int(item.get("away_tid"))
            if home in wins0 and away in wins0:
                remaining.append((safe_int(item.get("day")), home, away, str(item.get("gid"))))

    collect(score_items_for_page(data, teams)[0])
    if fresh and not remaining:
        collect(generated_schedule_items(data, teams, schedule_season=season))
    remaining.sort(key=lambda g: (g[0], g[3]))
    games_left = defaultdict(int)
    for _, home, away, _ in remaining:
        games_left[home] += 1
        games_left[away] += 1

    # Injury penalty by "games into the rest of the season" — deterministic per team.
    max_left = max(games_left.values()) if games_left else 0
    penalty_at: dict[int, list[float]] = {}
    for tid in tids:
        series = []
        for k in range(max_left + 1):
            series.append(sum(impact for impact, games_out in injured_by_tid.get(tid, []) if k < games_out))
        penalty_at[tid] = series

    first_day = remaining[0][0] if remaining else None
    stakes_games = [g for g in remaining if g[0] == first_day] if first_day is not None else []
    stake_counts: dict[str, dict[str, list[int]]] = {
        gid: {"home_win": [0, 0], "home_loss": [0, 0], "away_win": [0, 0], "away_loss": [0, 0]}
        for _, _, _, gid in stakes_games
    }

    def win_prob(home: int, away: int, k_home: int, k_away: int) -> float:
        # The module-level logistic (strength gap + SIM_HCA home edge) over the
        # injury-adjusted strengths k games into the rest of the season.
        return game_win_prob(
            base_strength[home] - penalty_at[home][min(k_home, max_left)],
            base_strength[away] - penalty_at[away][min(k_away, max_left)],
        )

    # 20290101 is an SMP I date, kept as-is only because it is the seed: changing it
    # would reshuffle every published number for no gain, and simulator.js mirrors the
    # literal so the Win-Out Machine's odds match the home page's.
    rng = random.Random(20290101)
    playoff_count = defaultdict(int)
    finals_count = defaultdict(int)
    champ_count = defaultdict(int)
    seed_counts: dict[int, list[int]] = {tid: [0] * len(tids) for tid in tids}
    win_total = defaultdict(float)
    round_lengths = playoff_series_lengths(data, season)

    def sim_series(a: int, b: int, length: int) -> int:
        """Best-of-`length`; team `a` has home court. Returns the winner."""
        needed = length // 2 + 1
        a_wins = b_wins = 0
        # 2-2-1-1-1 sliced to the series length: for a best-of-five that is 2-2-1,
        # which is what the engine plays.
        home_pattern = [True, True, False, False, True, False, True]
        for game_index in range(length):
            a_home = home_pattern[game_index % 7]
            prob = win_prob(a, b, max_left, max_left) if a_home else 1.0 - win_prob(b, a, max_left, max_left)
            if rng.random() < prob:
                a_wins += 1
            else:
                b_wins += 1
            if a_wins == needed:
                return a
            if b_wins == needed:
                return b
        return a if a_wins > b_wins else b

    for _ in range(sims):
        wins = dict(wins0)
        played = {tid: 0 for tid in tids}
        results_first_day: dict[str, bool] = {}
        for day, home, away, gid in remaining:
            home_won = rng.random() < win_prob(home, away, played[home], played[away])
            if home_won:
                wins[home] += 1
            else:
                wins[away] += 1
            played[home] += 1
            played[away] += 1
            if gid in stake_counts:
                results_first_day[gid] = home_won
        order = sorted(tids, key=lambda tid: (-wins[tid], rng.random()))
        made_playoffs = set(order[:4])
        for seed, tid in enumerate(order, 1):
            if seed <= 4:
                playoff_count[tid] += 1
            seed_counts[tid][seed - 1] += 1
        for tid in tids:
            win_total[tid] += wins[tid]
        # playoffs: 1v4 and 2v3, then the final; higher seed has home court
        finalist_a = sim_series(order[0], order[3], round_lengths[0])
        finalist_b = sim_series(order[1], order[2], round_lengths[0])
        finals_count[finalist_a] += 1
        finals_count[finalist_b] += 1
        if order.index(finalist_a) <= order.index(finalist_b):
            champ = sim_series(finalist_a, finalist_b, round_lengths[-1])
        else:
            champ = sim_series(finalist_b, finalist_a, round_lengths[-1])
        champ_count[champ] += 1
        # what's-at-stake bookkeeping for the next game day
        for _, home, away, gid in stakes_games:
            home_won = results_first_day.get(gid, False)
            key_home = "home_win" if home_won else "home_loss"
            key_away = "away_loss" if home_won else "away_win"
            stake_counts[gid][key_home][0] += 1
            stake_counts[gid][key_home][1] += 1 if home in made_playoffs else 0
            stake_counts[gid][key_away][0] += 1
            stake_counts[gid][key_away][1] += 1 if away in made_playoffs else 0

    results: dict[int, dict[str, Any]] = {}
    for tid in tids:
        results[tid] = {
            "po": playoff_count[tid] / sims,
            "finals": finals_count[tid] / sims,
            "champ": champ_count[tid] / sims,
            "seeds": [count / sims for count in seed_counts[tid]],
            "proj_w": win_total[tid] / sims,
            "games_left": games_left[tid],
        }

    # Per-game projection payload for the next slate. Win probability and
    # spread reuse the exact strengths the Monte Carlo fed win_prob for these
    # games (injury-adjusted at k=0), so any display built on this payload
    # agrees with the sim; the conditional playoff odds are tallied inside
    # the same sims.
    stakes = []
    for day, home, away, gid in stakes_games:
        counts = stake_counts[gid]

        def rate(key: str) -> float | None:
            total, made = counts[key][0], counts[key][1]
            return made / total if total else None

        eff_home = base_strength[home] - penalty_at[home][0]
        eff_away = base_strength[away] - penalty_at[away][0]
        stakes.append({
            "gid": gid, "day": day, "home_tid": home, "away_tid": away,
            "home_wp": game_win_prob(eff_home, eff_away),
            "spread": projected_spread(eff_home, eff_away),
            "home_po_win": rate("home_win"), "home_po_loss": rate("home_loss"),
            "away_po_win": rate("away_win"), "away_po_loss": rate("away_loss"),
        })
    return {"teams": results, "stakes": stakes, "day": first_day, "fresh": fresh}


def league_sim(data: dict[str, Any], teams: list[dict[str, Any]], season: int) -> dict[str, Any]:
    """League simulation, cached per season (each season is simulated once per build)."""
    cache = SITE_META.setdefault("sim", {})
    if season not in cache:
        cache[season] = simulate_league(data, teams, active_players(data), season)
    return cache[season]


# --- shared game model (consumed by simulate_league, appdata.py, pages) ------
# simulate_league decides every game with
#     p(home) = 1 / (1 + exp(-(strength_diff + SIM_HCA) * SIM_LOGISTIC_K))
# The constants and the helpers below ARE that model: simulate_league's inner
# win_prob calls game_win_prob, and the client-side simulator (Win-Out Machine /
# Lineup Lab) mirrors the same constants. Tests assert projected-win parity.
SIM_HCA = 1.5
SIM_LOGISTIC_K = 0.16


def game_win_prob(home_strength: float, away_strength: float) -> float:
    """Home team's single-game win probability from two team strengths.

    This is THE formula the Monte Carlo (simulate_league) decides games with:
    a logistic over the projected home scoring margin — the strength gap plus
    the +1.5-point home-court edge (SIM_HCA), scaled by SIM_LOGISTIC_K::

        p(home) = 1 / (1 + exp(-((home - away) + SIM_HCA) * SIM_LOGISTIC_K))

    Read-only consumers (home-page game cards, game previews) call this so
    their displayed probabilities agree with the sim exactly. Strengths are
    per-game scoring-margin signals from sim_client_inputs / simulate_league.
    """
    return 1.0 / (1.0 + math.exp(-(home_strength - away_strength + SIM_HCA) * SIM_LOGISTIC_K))


def projected_margin(home_strength: float, away_strength: float) -> float:
    """Projected home scoring margin, in points, for a single game.

    Team strengths are per-game scoring-margin signals, so the expected margin
    is simply ``(home_strength - away_strength) + SIM_HCA`` — the same quantity
    the win-probability logistic is applied to. Positive means the home team is
    projected to win by that many points.
    """
    return (home_strength - away_strength) + SIM_HCA


def projected_spread(home_strength: float, away_strength: float) -> float:
    """Sportsbook-style point spread for the HOME team, in half-point steps.

    The projected home margin (projected_margin) is quoted the way a book
    lists a line: negated (the favorite "lays" points) and rounded half-up to
    the nearest 0.5. A +4.4-point home margin returns -4.5 ("HOME -4.5"); a
    2.1-point away edge returns +2.0 ("AWAY -2.0"); a dead-even matchup
    returns 0.0 (a pick'em). Sign only says which side is favored — negative
    is the home team.
    """
    margin = projected_margin(home_strength, away_strength)
    return -math.floor(margin * 2.0 + 0.5) / 2.0


def sim_strengths(data: dict[str, Any], teams: list[dict[str, Any]], players: list[dict[str, Any]], season: int) -> dict[int, float]:
    """Read-only team strengths, exactly as the sim computes them.

    Convenience view over sim_client_inputs (which documents the model:
    current-roster impact blended with current-season MOV, never last
    season's margin). Feed pairs of these to game_win_prob / projected_spread
    for displays that must agree with simulate_league's Monte Carlo.
    """
    return sim_client_inputs(data, teams, players, season)["strengths"]


def sim_client_inputs(data: dict[str, Any], teams: list[dict[str, Any]], players: list[dict[str, Any]], season: int) -> dict[str, Any]:
    """Team strengths + remaining schedule for the client-side simulator.

    Mirrors the strength model and remaining-schedule selection at the top of
    simulate_league exactly (fresh-season detection, the current roster's
    rank-weighted rotation centered on the league mean, blended with
    CURRENT-season MOV at weight gp/(gp+SIM_MOV_BLEND_K) — never last season's
    margin) so that a
    client sim over this payload agrees with the server-side Monte Carlo. Injury
    penalties are intentionally left out of the payload — they decay per game and
    matter only mid-season; the client sims the healthy baseline.

    Returns {"strengths": {tid: float}, "hca", "logistic_k",
             "schedule": [[day, home_tid, away_tid], ...], "fresh": bool,
             "wins": {tid: int}, "losses": {tid: int}}.
    """
    fresh = not completed_game_items(data, season, playoffs=False)
    tids = [safe_int(t.get("tid")) for t in teams if t.get("tid") is not None]
    mov_now: dict[int, float] = {}
    gp_now: dict[int, float] = {}
    wins: dict[int, int] = {}
    losses: dict[int, int] = {}
    for team in teams:
        tid = safe_int(team.get("tid"))
        team_season = latest_team_season(team, season)
        stat = latest_team_stat(team, season)
        wins[tid] = 0 if fresh else safe_int(team_season.get("won"))
        losses[tid] = 0 if fresh else safe_int(team_season.get("lost"))
        # latest_team_stat falls back to an earlier season's row when this season
        # has no stats yet — never seed strength from last season's margin.
        if safe_int(stat.get("season")) == season:
            gp_now[tid] = safe_float(stat.get("gp"))
            mov_now[tid] = team_mov(stat) or 0.0
        else:
            gp_now[tid] = 0.0
            mov_now[tid] = 0.0

    roster_by_tid: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for player in players:
        tid = safe_int(player.get("tid"), -9)
        if tid >= 0:
            roster_by_tid[tid].append(player)
    roster_strength: dict[int, float] = {}
    for tid in tids:
        roster_strength[tid] = rotation_strength(roster_by_tid.get(tid, []), season)
    mean_roster = sum(roster_strength.values()) / len(roster_strength) if roster_strength else 0.0
    strengths: dict[int, float] = {}
    for tid in tids:
        mov_weight = gp_now[tid] / (gp_now[tid] + SIM_MOV_BLEND_K)
        roster_signal = roster_strength.get(tid, 0.0) - mean_roster
        strengths[tid] = (1.0 - mov_weight) * roster_signal + mov_weight * mov_now[tid]

    # Mirrors simulate_league: exported schedule first, generated round-robin
    # only for an unplayed season with no exported schedule.
    remaining: list[tuple[int, int, int, str]] = []

    def collect(items: Iterable[dict[str, Any]]) -> None:
        for item in items:
            if is_completed_game_item(item) or safe_int(item.get("season")) != season:
                continue
            home, away = safe_int(item.get("home_tid")), safe_int(item.get("away_tid"))
            if home in strengths and away in strengths:
                remaining.append((safe_int(item.get("day")), home, away, str(item.get("gid"))))

    collect(score_items_for_page(data, teams)[0])
    if fresh and not remaining:
        collect(generated_schedule_items(data, teams, schedule_season=season))
    remaining.sort(key=lambda g: (g[0], g[3]))

    return {
        "strengths": strengths,
        "hca": SIM_HCA,
        "logistic_k": SIM_LOGISTIC_K,
        "schedule": [[day, home, away] for day, home, away, _ in remaining],
        "fresh": fresh,
        "wins": wins,
        "losses": losses,
    }


def league_bench_ovrs(players: list[dict[str, Any]], season: int) -> list[float]:
    """League-average 6th..10th-best current-roster OVRs, sorted desc (5 floats, 1dp).

    Emitted as app-data.json's sim.bench_ovrs; Lineup Lab pads a five-man
    selection with these instead of a flat replacement OVR. Rank-wise mean
    across the current rosters: a team with fewer than ten players simply
    doesn't count toward the deeper ranks; a rank no team fills falls back
    to REPLACEMENT_OVR.
    """
    by_tid: dict[int, list[int]] = defaultdict(list)
    for player in players:
        tid = safe_int(player.get("tid"), -9)
        if tid < 0:
            continue
        ovr = latest_rating(player, season).get("ovr")
        if ovr is not None:
            by_tid[tid].append(safe_int(ovr))
    rosters = [sorted(ovrs, reverse=True) for ovrs in by_tid.values()]
    out: list[float] = []
    for rank in range(5, 10):
        values = [ovrs[rank] for ovrs in rosters if len(ovrs) > rank]
        avg = sum(values) / len(values) if values else REPLACEMENT_OVR
        out.append(round(avg, 1) + 0.0)
    return sorted(out, reverse=True)




def playoff_clinch_marks(data: dict[str, Any], teams: list[dict[str, Any]], season: int) -> dict[int, str]:
    """Computed clinch ("x") / elimination ("e") marks for a top-4 playoff cut.

    Uses each team's record plus its remaining schedule (games not yet played).
    Conservative pairwise math: a team is marked clinched only when fewer than
    four rivals can still reach its current win total, and eliminated only when
    at least four rivals already exceed its maximum possible win total. Ties
    count against clinching and for survival, so ambiguous cases get no mark.
    """
    rows: dict[int, dict[str, float]] = {}
    for team in teams:
        tid = safe_int(team.get("tid"))
        team_season = latest_team_season(team, season)
        rows[tid] = {
            "won": safe_float(team_season.get("won")),
            "lost": safe_float(team_season.get("lost")),
            "rem": 0.0,
        }
    if len(rows) < 5:
        return {}

    # Remaining games per team, counted from the exported schedule.
    scheduled = 0
    for item in raw_schedule_items(data, teams):
        if is_completed_game_item(item) or item.get("playoffs") or safe_int(item.get("season"), season) != season:
            continue
        home, away = safe_int(item.get("home_tid")), safe_int(item.get("away_tid"))
        if home in rows and away in rows:
            rows[home]["rem"] += 1
            rows[away]["rem"] += 1
            scheduled += 1
    if not scheduled:
        # No schedule export: fall back to the season length, or skip if unknown.
        season_len = regular_season_length(data, season)
        if season_len <= 0:
            return {}
        for row in rows.values():
            row["rem"] = max(0.0, season_len - row["won"] - row["lost"])

    out: dict[int, str] = {}
    for tid, row in rows.items():
        max_wins = row["won"] + row["rem"]
        can_catch = sum(1 for o_tid, o in rows.items() if o_tid != tid and o["won"] + o["rem"] >= row["won"])
        already_ahead = sum(1 for o_tid, o in rows.items() if o_tid != tid and o["won"] > max_wins)
        if can_catch <= 3:
            out[tid] = "x"
        elif already_ahead >= 4:
            out[tid] = "e"
    return out
