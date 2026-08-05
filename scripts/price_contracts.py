#!/usr/bin/env python3
"""
Price every player in an SMP II league export at FAIR value.

The goal
--------
A price should already contain everything the league knows about a player, so that
drafting well means beating the model -- not collecting a bonus for taking the obvious
name. Under the old age-band pricing, rookie LeBron cost $7M against $50M of eventual
value: whoever held pick 1 banked ~$43M/yr of surplus for doing the obvious thing, and
the correct strategy collapsed into "hoard cheap young talent."

The model
---------
    salary = A * mean over contract years of 2^((E[ovr_t] - PIVOT) / WIDTH)
             * duration_premium(years)

E[ovr_t] is the player's EXPECTED overall in each year of the deal, from a Monte Carlo
projection of their actual 15 sub-ratings (scripts/projections.py, a port of zengm's
develop.ts), seeded fixed so a rebuild reprices identically.

  * doubling every WIDTH points of ovr is what creates the star premium
  * there is NO age_factor any more. Aging used to be a hand-tuned multiplier on age
    bands; the projection now carries it per player, which is both more accurate and
    strictly more expressive. An age band cannot say "this 28-year-old falls off a
    cliff and that one doesn't" -- and that gap was the largest mispricing in the old
    model (Kevin Garnett, 73/76, priced $31M against $18M of fair value).
  * A is SOLVED by bisection, not chosen, so league payroll hits TARGET_LEAGUE_PAYROLL.

What this leaves for managers: the projection is an EXPECTATION, and development is
stochastic (realPlayerDeterminism is 0, so nobody follows their real career). The edge
is in reading who beats their projection, in fit, and in trading -- not in knowing that
LeBron is good.

Contract length is assigned from age and upside so expirations stagger instead of all
landing in one summer. BBGM stores a contract as a single flat {amount, exp} -- there is
no native per-year structure -- so length is the only lever, and a duration premium is
applied because a short deal on a good player is worth more per year.

Requires numpy (for scripts/projections.py).

Usage
-----
    python3 scripts/price_contracts.py in.json out.json
    python3 scripts/price_contracts.py in.json out.json --report
"""

from __future__ import annotations

import argparse
import collections
import json
import sys

# ---- league constants (BBGM "thousands": 100000 == $100M) -------------------
# SMP II has NO salary cap and no luxury tax. TARGET_PAYROLL is not a ceiling, it is
# the average team payroll the curve is calibrated to produce -- the number that makes
# a 12-man roster cost about what an average team earns in a season (see smp/finance.py).
TARGET_PAYROLL = 100_000        # $100M per team
MIN_CONTRACT = 1_000
MAX_CONTRACT = 50_000
ROSTER_SIZE = 12
NUM_TEAMS = 10

TARGET_LEAGUE_PAYROLL = NUM_TEAMS * TARGET_PAYROLL

PIVOT = 60      # ovr at which the curve passes through A
WIDTH = 5       # salary doubles every WIDTH points of ovr


MC_SIMS = 400           # Monte Carlo paths per player
MC_SEED = 20040101      # fixed: prices must be identical on every rebuild


def contract_length(ovr: int, pot: int, age: int) -> int:
    """Years. Long deals for young upside, short deals for old production.

    SMP I had 53% of all contracts expiring in one summer, which made waiting strictly
    better than trading. The bands below are tuned so no single year holds more than
    about a third of the league -- verify with --report before committing a pool.
    """
    upside = pot - ovr
    if age <= 23:
        return 4 if upside >= 8 else 3
    if age <= 25:
        return 3 if upside >= 4 else 2
    if age <= 30:
        # good players get locked up longer; fringe veterans stay on short money
        if ovr >= 66:
            return 4          # lock up the genuinely good veterans
        if upside >= 6:
            return 3
        return 2 if ovr >= 58 else 1
    if age <= 33:
        return 2 if ovr >= 62 else 1
    return 1


# A short deal is worth more per year than a long one at the same talent: the team is
# buying flexibility. This is the only per-year structure BBGM can natively enforce.
DURATION_PREMIUM = {1: 1.25, 2: 1.10, 3: 1.00, 4: 0.95}


SALARY_STEP = 1_000     # whole $1M increments -- no decimals anywhere on the site


def value_at(ovr_value: float, scale: float) -> float:
    """The league's value curve at a given OVR. Age-neutral on purpose.

    Aging used to be a hand-tuned age_factor multiplier. It isn't any more: the Monte
    Carlo projection below carries aging per player, from their actual sub-ratings,
    which is both more accurate and impossible to express as an age band.
    """
    return scale * (2.0 ** ((ovr_value - PIVOT) / WIDTH))


def project_paths(players: list[dict], n_sims: int = MC_SIMS) -> None:
    """Attach each player's EXPECTED ovr for every year of their contract.

    Uses the repo's own Monte Carlo development engine (scripts/projections.py, a port
    of zengm's develop.ts), seeded deterministically so prices are identical on every
    rebuild. Sets p["path"] = [ovr_now, ovr_yr1, ... ovr_yrN].
    """
    from projections import RATINGS, develop_paths      # needs numpy

    for i, p in enumerate(players):
        yrs = contract_length(p["ovr"], p["pot"], p["age"])
        ratings = p.get("ratings")
        if not ratings:
            # No sub-ratings to develop from: hold the current ovr flat.
            p["years"], p["path"] = yrs, [float(p["ovr"])] * (yrs + 1)
            continue
        paths = develop_paths({k: ratings[k] for k in RATINGS}, p["age"], yrs,
                              n_sims, seed=MC_SEED + i)
        p["years"] = yrs
        p["path"] = [float(v) for v in paths["ovr"].mean(axis=0)]


def fair_raw(p: dict, scale: float) -> float:
    """Mean annual value over the contract, on the player's expected ovr path.

    This is what makes the price FAIR: a 20-year-old who will improve is charged for
    the player he becomes, and a 28-year-old about to decline is charged for the
    decline. Measured on the 2003-04 pool, that moves Kevin Garnett (73/76, age 28)
    from $31M to $18M and LeBron (67/81, age 20) from $7M to $35M.
    """
    yrs = p["years"]
    return sum(value_at(p["path"][t], scale) for t in range(1, yrs + 1)) / yrs


def price_from_raw(raw: float, years: int) -> int:
    amount = raw * DURATION_PREMIUM[years]
    amount = int(round(amount / SALARY_STEP)) * SALARY_STEP
    return min(max(amount, MIN_CONTRACT), MAX_CONTRACT)


def solve_scale(players: list[dict]) -> float:
    """Solve A so the ROSTER_SIZE * NUM_TEAMS most valuable players total the target.

    Bisection, not algebra: dividing the target by the raw sum ignores the
    [MIN_CONTRACT, MAX_CONTRACT] clamps, so players pushed UP to the minimum make the
    realised total overshoot (measured 0.69% high with 9 clamped). Bisecting on the
    clamped, rounded price converges on the number actually written to the export.

    "Most valuable" is itself scale-invariant here -- the curve is monotonic in the
    projected path -- so the top-120 set is stable across the search.
    """
    slots = ROSTER_SIZE * NUM_TEAMS
    if not players:
        raise ValueError("degenerate pool: cannot solve scale")

    def priced(scale: float) -> list[int]:
        vals = sorted((fair_raw(p, scale), p["years"]) for p in players)
        vals.reverse()
        return [price_from_raw(r, y) for r, y in vals[:slots]]

    # A pool smaller than the league's roster slots can't be worth a full league
    # payroll; without this a 30-player file would absorb the whole target.
    target = TARGET_LEAGUE_PAYROLL * min(len(players), slots) / slots

    lo, hi = 1.0, 1_000_000.0
    if sum(priced(hi)) < target:
        return hi
    for _ in range(200):
        mid = (lo + hi) / 2
        if sum(priced(mid)) < target:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def draft_value(p: dict) -> float:
    """Ranking key for 'who would be drafted': the fair value of the whole contract."""
    return p.get("fair", 0.0)


# ---- applying it to a league export ----------------------------------------
def extract(league: dict) -> list[dict]:
    season = league["gameAttributes"]["season"]
    out = []
    for p in league["players"]:
        r = p["ratings"][-1]
        out.append(
            {
                "p": p,
                "ovr": r["ovr"],
                "pot": r["pot"],
                "age": season - p["born"]["year"],
                "ratings": r,
                "name": f"{p['firstName']} {p['lastName']}".strip(),
            }
        )
    return out


def reprice(league: dict) -> tuple[float, list[dict]]:
    season = league["gameAttributes"]["season"]
    rows = extract(league)
    project_paths(rows)                     # attaches ["years"] and ["path"]
    scale = solve_scale(rows)
    for row in rows:
        row["fair"] = fair_raw(row, scale)
        amount = price_from_raw(row["fair"], row["years"])
        row["p"]["contract"] = {"amount": amount, "exp": season + row["years"]}
        row["amount"] = amount
    return scale, rows


def report(league: dict, scale: float, rows: list[dict]) -> None:
    ranked = sorted(rows, key=draft_value, reverse=True)[: ROSTER_SIZE * NUM_TEAMS]
    sal = sorted(r["amount"] for r in ranked)
    print(f"scale A = {scale:.1f}   (pivot {PIVOT} ovr, doubling every {WIDTH})")
    print(f"top-{len(ranked)} payroll  ${sum(sal) / 1000:,.0f}M "
          f"vs ${TARGET_LEAGUE_PAYROLL / 1000:,.0f}M target "
          f"({100 * sum(sal) / TARGET_LEAGUE_PAYROLL:.1f}%)   "
          f"avg team ${sum(sal) / NUM_TEAMS / 1000:,.1f}M")
    print(f"  max ${sal[-1] / 1000:.1f}M   median ${sal[len(sal) // 2] / 1000:.1f}M   "
          f"min ${sal[0] / 1000:.1f}M   at-minimum {sum(1 for s in sal if s == MIN_CONTRACT)}")

    print("\n  most expensive:")
    for r in sorted(ranked, key=lambda r: -r["amount"])[:8]:
        print(f"    {r['name']:<22} age {r['age']:<3} ovr {r['ovr']:<3} pot {r['pot']:<3} "
              f"${r['amount'] / 1000:>5.1f}M  {r['years']}yr")

    print("\n  projected paths (price follows the path, not today's ovr):")
    for r in sorted(ranked, key=lambda r: -r["amount"])[:4] + sorted(ranked, key=lambda r: r["age"])[:3]:
        path = " -> ".join(f"{v:.0f}" for v in r["path"])
        print(f"    {r['name']:<22} age {r['age']:<3} ${r['amount'] / 1000:>5.1f}M  {path}")

    exp = collections.Counter(r["p"]["contract"]["exp"] for r in ranked)
    print("\n  expiration stagger:",
          "  ".join(f"{k}:{v}" for k, v in sorted(exp.items())))

    rostered = [r for r in rows if r["p"]["tid"] >= 0]
    if rostered:
        by_team: dict[int, int] = collections.defaultdict(int)
        for r in rostered:
            by_team[r["p"]["tid"]] += r["amount"]
        abbrev = {t["tid"]: t["abbrev"] for t in league["teams"]}
        print("\n  per-team payroll (no cap -- these are spend levels, not limits):")
        for t in sorted(by_team):
            print(f"    {abbrev.get(t, t):<5} ${by_team[t] / 1000:>6.1f}M")
        vals = sorted(by_team.values())
        print(f"  spread ${vals[0] / 1000:.1f}M - ${vals[-1] / 1000:.1f}M "
              f"(target average ${TARGET_PAYROLL / 1000:.0f}M)")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("infile")
    ap.add_argument("outfile")
    ap.add_argument("--report", action="store_true", help="print a calibration report")
    args = ap.parse_args()

    with open(args.infile) as fh:
        league = json.load(fh)

    scale, rows = reprice(league)

    with open(args.outfile, "w") as fh:
        json.dump(league, fh)

    if args.report:
        report(league, scale, rows)
    print(f"\nrepriced {len(rows)} players -> {args.outfile}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
