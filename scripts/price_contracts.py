#!/usr/bin/env python3
"""
Price every player in an SMP II league export for the $100M hard-cap era.

Why this exists
---------------
SMP I's contracts were flat: median $18M against a $300M cap, i.e. every player cost
about the same. Nothing bound, salary-matched trades were trivial, and free agency beat
trading because the marginal free agent was as good as the marginal roster player and
cost 0.33% of the cap. This script replaces that with an exponential curve so that stars
are genuinely expensive and depth is genuinely cheap.

The curve
---------
    salary = A * 2^((ovr - PIVOT) / WIDTH) * age_factor(age)

  * doubling every WIDTH points of ovr is what creates the star premium
  * age_factor makes YOUNG high-potential players CHEAP. That is deliberate: it is the
    rookie-scale analogue, and it is what makes drafting for potential produce surplus
    value. Rookie LeBron (20yo, 67 ovr / 81 pot) prices at ~$6M and becomes a star on
    that deal; 27-year-old Peja (75/75) costs ~$35M for production he already has.
  * A is SOLVED, not chosen, so that total league payroll hits TARGET_LEAGUE_PAYROLL.
    Re-solving each time is what keeps the curve calibrated as the talent pool drifts.

Contract length is assigned from age and upside so expirations stagger instead of all
landing in one summer. BBGM stores a contract as a single flat {amount, exp} -- there is
no native per-year structure -- so length is the only lever, and a duration premium is
applied to reflect that a short deal on a good player is worth more per year.

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


def age_factor(age: int) -> float:
    """Young = cheap (unproven upside is the drafter's surplus). Old = cheap (decline risk).

    Peak-age players pay full freight because you are buying production you can bank on.
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


def _raw(ovr: int, age: int) -> float:
    return (2.0 ** ((ovr - PIVOT) / WIDTH)) * age_factor(age)


def solve_scale(players: list[dict]) -> float:
    """Solve A so the ROSTER_SIZE * NUM_TEAMS most valuable players total the target payroll.

    Solved by BISECTION rather than algebra. Dividing the target by the raw sum ignores
    the [MIN_CONTRACT, MAX_CONTRACT] clamps: players whose raw price falls below the
    minimum get pushed UP to it, so the realised total overshoots. Measured on this pool
    it landed 0.69% high with 9 players clamped. Bisecting on the clamped price converges
    on the real total instead.
    """
    slots = ROSTER_SIZE * NUM_TEAMS
    ranked = sorted(players, key=draft_value, reverse=True)[:slots]
    if not ranked:
        raise ValueError("degenerate pool: cannot solve scale")
    # A pool smaller than the league's roster slots can't be worth a full league payroll.
    # Without this, a 30-player file would try to absorb the whole target and clip players
    # at the max contract -- wrong, and silently so.
    target = TARGET_LEAGUE_PAYROLL * len(ranked) / slots

    def total_at(scale: float) -> int:
        return sum(price(p["ovr"], p["pot"], p["age"], scale) for p in ranked)

    lo, hi = 1.0, 1_000_000.0
    if total_at(hi) < target:          # even the ceiling can't reach it
        return hi
    for _ in range(200):
        mid = (lo + hi) / 2
        if total_at(mid) < target:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def draft_value(p: dict) -> float:
    """Rough stand-in for BBGM's p.value: current ovr plus youth-weighted upside."""
    return p["ovr"] + max(0, p["pot"] - p["ovr"]) * max(0, 30 - p["age"]) / 12.0


SALARY_STEP = 1_000     # whole $1M increments -- no decimals anywhere on the site


def price(ovr: int, pot: int, age: int, scale: float) -> int:
    yrs = contract_length(ovr, pot, age)
    amount = scale * _raw(ovr, age) * DURATION_PREMIUM[yrs]
    # Round to the nearest whole $1M. Done INSIDE the priced value (not as a display
    # step) so solve_scale bisects on the number actually written to the export and the
    # league total still lands on target.
    amount = int(round(amount / SALARY_STEP)) * SALARY_STEP
    return min(max(amount, MIN_CONTRACT), MAX_CONTRACT)


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
                "name": f"{p['firstName']} {p['lastName']}".strip(),
            }
        )
    return out


def reprice(league: dict) -> tuple[float, list[dict]]:
    season = league["gameAttributes"]["season"]
    rows = extract(league)
    scale = solve_scale(rows)
    for row in rows:
        yrs = contract_length(row["ovr"], row["pot"], row["age"])
        amount = price(row["ovr"], row["pot"], row["age"], scale)
        row["p"]["contract"] = {"amount": amount, "exp": season + yrs}
        row["amount"] = amount
        row["years"] = yrs
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

    print("\n  best surplus (high pot, low price):")
    surplus = [r for r in ranked if r["pot"] - r["ovr"] >= 10]
    for r in sorted(surplus, key=lambda r: r["amount"])[:6]:
        print(f"    {r['name']:<22} age {r['age']:<3} ovr {r['ovr']:<3} pot {r['pot']:<3} "
              f"${r['amount'] / 1000:>5.1f}M  {r['years']}yr")

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
