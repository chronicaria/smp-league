# SMP II — League Reboot Design

Working brainstorm for restarting the SMP league from scratch: 10 teams, new rosters,
full redraft, new settings.

Diagnoses marked **[verified]** were reproduced directly against `league-data/2031_day5.json`.
Claims about Basketball GM internals (formula shapes, engine behavior) come from source
reading during research and are marked **[source]** — worth spot-checking the one or two
that a decision actually hinges on before you commit.

---

## Part 1 — What the data says

### D1. You have never had any AI teams. [verified]

`userTids = [0,1,2,3,4,5,6,7,8,9]`. All ten. From BBGM's point of view there are zero AI
teams, so the engine never signs, re-signs, drafts, or proposes trades for the five
"passive" clubs — you do, by hand, or nobody does. All ten teams read
`strategy: "rebuilding"` in the export, permanently, because `updateStrategies` never had
anything to run on. [source]

The receipt, from the events array over six seasons:

| event | count |
|---|---|
| `freeAgent` | **115** |
| `reSigned` | 55 |
| `release` | 65 |
| `trade` | **11** |

11 trades in six seasons — 8 involving Waltham, 6 of those Gooners↔Waltham. The trade
market was one friendship. **This one setting is upstream of half the complaints.**

### D2. There is no dynasty. There is a floor problem. [verified]

`playoffRoundsWon = 2` in a 2-round bracket means *champion*, not "won two rounds."

| season | champion | record |
|---|---|---|
| 2026 | Gooning Gooners | 22-18 |
| 2027 | Rochester Dragons | 23-17 |
| 2028 | Cambridge Platypuses | 27-13 |
| 2029 | Waltham Bears | 33-12 |
| 2030 | Cambridge Platypuses | 38-7 |

Four different champions in five seasons; Cambridge won 40%. That is better balance than
the NBA over most five-year windows. What actually happened is one outlier *season* —
Cambridge 2030 at **+11.16 MOV against a next-best +2.80**.

The real injustice: **Durham `[-1,-1,-1,-1,-1,-1]`** — zero playoff berths in six seasons.

**Design against the floor, not the ceiling.** Test to hold yourself to: *no team goes
three straight seasons without either a playoff berth or a top-2 pick that becomes a real
player.*

What did persist for Cambridge was talent concentration: highest top-3 ovr sum in all six
seasons. Top-3 mean ovr is the best single predictor of win% across 47 team-seasons
(r = 0.500, vs 0.414 for team mean). Note the implication — **stretching the ratings
distribution multiplies exactly the thing Cambridge monopolized.**

### D3. Ratings compression is real, and partly self-inflicted. [verified]

149 rostered, ovr 31–77, **sd 7.70, 118 of 149 (79%) inside 55–69**.

```
30-34 ▏1     55-59 ████████████████████████████████████████████ 44
35-39 ▎3     60-64 █████████████████████████████████████████████████ 49
40-44 ▍5     65-69 █████████████████████████ 25
45-49 ▍4     70-74 ██████ 6
50-54 ▊8     75-79 ████ 4
```

Where it came from: the 2026 real-player class peaked at ovr 79, and across **five
fictional draft classes (115 players) BBGM never produced a single player who reached
70.** League max fell 79 → 78 → 77 across 2029–2031. The league is a star-depletion
machine — a real-era reseed fixes a large chunk of this before any display work.

Separately, **the site is hiding the players you say don't exist**: `scripts/smp/core.py:517`
and `scripts/smp/pages/league.py:445` both drop free agents with `ovr < 50 or pot < 50`,
concealing 57 of 135 free agents, 43 of them squarely in the 40–50 band.

### D4. Money does nothing, in both directions. [source]

Two facts kill most finance ideas:

- `genContract` computes `amount = ((value/100) − 0.47) × 3.4 × (maxContract − minContract) + minContract`.
  **There is no `salaryCap` term.** Highest rostered `value` is 67.4 → asks $34,986; you'd
  need value 76.4 to reach the $50,000 max. **The max contract has never bound a single
  organic deal.** Raising it to $90k doesn't create a star premium — it rescales *every*
  contract by 1.62× and puts a 15-man payroll at $471k against a $300k cap.
- Nothing in BBGM reads team cash. `updateOwnerMood` early-returns when `userTids.length > 1`.
  Nobody can be fired; cash gates no signing, trade, or pick. **The −$2,849,712 is a
  rendering problem.**

The break-even diagnosis still holds and is worth fixing for the page's sake: at 2030
expense levels, non-salary expense ran **0.877 × cap** against revenue of **1.517 × cap**,
so break-even payroll was **0.640 × cap ≈ $192,000 — below the $200,000 minPayroll floor.**
Every team was guaranteed a loss before signing anybody.

The 2029 "revenue collapse" was self-inflicted: `nationalTv/game ÷ salaryCap = 0.00759259`
in every season to seven significant figures, which back-solves to a cap cut ~60% for 2029
and walked back to 300,000 by 2031. Two deliberate edits, one mid-season.

### D5. Free agency beat trades for four measurable reasons — none of them roster size. [verified]

1. **The marginal roster player and the marginal free agent are the same player.** Roster
   spots 11–15 (49 players) run median ovr 55; the FA pool tops out at 57. **121 of 135
   free agents ask exactly $1,000** — including Mikal Bridges, Jaren Jackson Jr., and Jalen
   Johnson at 57 ovr. Whatever you'd trade for, the other guy signs an equivalent for 0.33%
   of the cap.
2. **53% of contracts expire in one summer.** 2031: 79 · 2032: 18 · 2033: 27 · 2034: 24 ·
   2035: 1. When half the league becomes signable annually, trading is dominated by waiting.
3. **Zero AI counterparties** (D1).
4. **The scrap heap can't drain.** `numDraftRounds: 1` sends ~13 undrafted players to free
   agency yearly, and `minRetireAge: 26` forbids them from leaving. 93 of 135 free agents
   are under 26; **96 have never played a game**; 41 have been free agents for 4–5 years.

**And the 15-man roster has been a 10-man roster the whole time.** 2030 minutes share by
roster rank:

```
 1  13.8%   6   9.1%   11  2.7%
 2  12.5%   7   8.2%   12  1.6%
 3  11.5%   8   7.3%   13  0.5%
 4  10.9%   9   6.1%   14  0.3%
 5  10.3%  10   4.5%   15  0.3%
             └ cumulative 94.1%
```

BBGM's team-ovr formula weights the 10th player at 0.235 and players 11–15 at **exactly
zero**. [source] 30 player-seasons logged no games at all in 2030. [verified]

---

## Part 2 — The recommended package

### A. Settings to set once, at league creation

**League identity**
```
Real players, real rosters, startingSeason 2003 (the 2003-04 NBA)
randomDebuts: OFF          realDraftRatings: "draft"
realPlayerDeterminism: 0   rpdPot: true   forceRetireRealPlayers: false
userTids: [the 5 human tids ONLY]
difficulty: 0              godMode: true
```

**Schedule and playoffs**
```
numGames: 36                    (4 per opponent, 18 home / 18 away)
numGamesPlayoffSeries: [1,5,7]  numPlayoffByes: 2   playIn: false
playoffsReseed: false           neutralSite: "finals"
confs: 1   divs: 1              playoffsByConf: false
tradeDeadline: 0.60             groupScheduleSeries: true
allStarGame: 0.55               allStarType: "draft"   allStarNum: 12
```

**Roster and draft**
```
maxRosterSize: 13   minRosterSize: 10
numDraftRounds: 2   draftPickAutoContractRounds: 2   draftPickAutoContractPercent: 10
rookieContractLengths: [3,2]    rookiesCanRefuse: false
draftType: "custom"   draftLotteryCustomNumPicks: 3
draftLotteryCustomChances: [400, 300, 200, 100]
numSeasonsFutureDraftPicks: 3
forceRetireAge: 36   minRetireAge: 24   injuryRate: 0.00015
```

**Money and market**
```
salaryCap: 300000 (unchanged — it is a unit of account)   salaryCapType: soft
minPayroll: 120000 (40%)   luxuryPayroll: 336000 (112%)   luxuryTax: 1.5
minContract: 4500 (1.5%)   maxContract: SET FROM THE POOL — see B3
maxContractLength: 4   minContractLength: 1
softCapTradeSalaryMatch: 125
aiTradesFactor: 3          budget: false
playersRefuseToNegotiate: FALSE
inflationAvg: 3   inflationStd: 1   inflationMin: 0   inflationMax: 8
pop: a published ladder from 3.2 to 4.0   stadiumCapacity: 32000
hype: reset all ten to 0.50
```

### B. The four decisions that carry the reboot

#### B1. `userTids` = five humans

Everything else is downstream. This alone buys 9 responsive trade partners instead of 4,
AI free-agent signing, auto-drafting, and engine-assigned team strategies (2–3 genuine
sellers every season, maintained for free).

Two operational gotchas: [source]
- The five AI teams take a permanent **−3 mood penalty** on every negotiation once they
  leave `userTids` — budget a light god-mode roster-repair pass each offseason.
- `autoSign` fires on every day you advance during the FA phase. **Collect all five human
  offers first, execute them, then advance days** — otherwise the robots take the pool
  overnight.

`aiTradesFactor: 3` — `betweenAiTeams` scales it by `numActiveTeams / 30`, so 3 in a
10-team league reproduces the 30-team default of 1. [source]

#### B2. Attack the free-agency magnet in the mood system, not with `maxContract`

This is where Wembanyama actually walked from Durham to Cambridge. `moodComponents` gives
hype a −2..+2 range and marketSize a −2..+2 range driven purely by population **rank** —
your ten pops span 0.9821–1.0109, a **2.9% spread**, and it hands out a full 4-point swing
nobody knew existed. `probWilling = 1/(1 + exp(−0.7x))`, so the ~8-point Cambridge-vs-Rochester
gap is an **e^5.6 ≈ 270× odds ratio**. [source]

All fixes are one-time:
- Reset every `hype` to 0.50.
- Publish a deliberate `pop` ladder — give the top ranks to the AI teams and the
  least-engaged managers.
- Set **`playersRefuseToNegotiate: false`**. This removes the hard refusal gate while
  leaving the mood *price* premium (up to 1.5×) fully intact. A losing team can always get
  to the table and pays 1.5× where the champion pays 1.0×. You keep the flavor, delete the
  monopoly.

> ⚠️ **If you god-mode-edit the existing file instead of creating a new league, `hype` and
> `pop` carry over and Cambridge starts SMP II with a +4 recruiting head start. Create new.**

#### B3. Price contracts by formula; calibrate `maxContract` to the pool

Don't pick a max as a % of cap — invert `genContract` against the *observed* top `value`
in the 2003-04 pool. Solve for M:

```
((v_max/100) − 0.47) × 3.4 × (M − 4500) + 4500 = target
```

Then write the contracts yourself at creation:

```
salary = A × 2^((ovr − 60)/7) × age_factor × duration_premium

age_factor:  ≤23 ×0.75 | 24–30 ×1.00 | 31–33 ×0.90 | 34+ ×0.75
             (×1.15 if pot − ovr ≥ 8 and age ≤ 25)
duration:    1yr ×1.25 | 2yr ×1.10 | 3yr ×1.00 | 4yr ×0.95

clamp to [minContract, maxContract]; round to $500
calibrate A so Σ over the drafted pool = 0.92 × 10 × salaryCap
```

Doubling every 7 points of ovr gives an **8× star premium** against today's 2.14×. On
today's roster a flat 4% anchor produces payrolls of 62–101% of cap and nothing binds —
hence the calibration step. One line of Python, run once.

**The duration premium is the honest answer to "contracts that differ per year."** BBGM's
contract is `{amount, exp}` — one flat number. `getPayroll`, the cap check, salary matching
and every AI valuation read `amount` and nothing else, so a per-year escalator written into
the JSON is a number the game never sees. [source] A duration premium is enforced natively
and immediately: a contender renting a star for one year genuinely eats 25% more cap than a
rebuilder signing him for three.

#### B4. Fix the finances on the revenue side, then stop

`baseAttendance = 10000 + (0.1 + 0.9 × hype²) × pop × 10000`. At `pop: 1.0` — BBGM's floor,
where all ten of your teams sit — baseAttendance can never exceed 20,000 even for a 38-7
champion, and `localTv`, `sponsor` and `merch` are all **linear** in it. [source]

Raising pop to ~3.5 and capacity to 32,000 moves break-even payroll from **0.640 × cap to
roughly 1.05 × cap** — a team spending to the cap breaks even. With `minPayroll` at 40% and
`budget: false`, the ledger stops being all red.

**`budget: false` is a competitive fix, not cleanup.** `getLevelLastThree` returns
`DEFAULT_LEVEL (34)` for every team when budget is off, zeroing coaching (±9% on progs),
health (±12% on injuries), facilities (mood + attendance) and scouting **league-wide**.
[source] These are absolute buffs purchasable only by whoever opens the page. Your 2030
expense levels ran **Queens 16.5 to Rochester 74**; 2031 ran **Durham 34 to Cambridge
82–87**. That is a talent gap the five humans bought and the five AI teams never contested.
One boolean.

### C. Free agency and the scrap heap

- **`minContract` 1000 → 4500 (1.5% of cap).** Filling a 13-man roster off the wire now
  costs ~19% of the cap instead of 4%. Does more against FA mining than any rule, applies
  symmetrically to the AI teams, needs no enforcement.
- **One-time pool prune at creation.** Cut the seed pool so the living non-retired universe
  is ~1.12 × roster spots (**~148 players for 130 spots**), giving an FA pool of ~18 instead
  of 135. Mark the rest `tid: -3` with `retiredYear` — never delete, so awards and box
  scores survive.
- **Formalize the fill draft you already run.** `scripts/materialize_2031_offseason.py`
  already runs free agency as a hand-priced multi-round fill draft with per-team entries
  from $1k to $42k. Stop pretending in-app FA is the process. Make it: **2 rounds, strict
  reverse standings order, snake the second round, priced by the curve, at most 2 FA
  additions per team per year** (20 league-wide against 130 spots), auto-pick best-available
  for AI teams. Tooling cost is zero — it's what you're already doing, with a cap and a
  published order.
- **Reverse-standings priority as the universal tiebreak.** FA draft order, waiver claims,
  two offers for the same player — always strict reverse order of last season's record,
  defending champion always last. One line in the constitution, no code, and the only
  anti-dynasty mechanic that costs nothing.
- `minRetireAge: 24` is what lets the 96 never-played 20-year-olds actually leave.

---

## Part 3 — Verdicts on the ten starting ideas

### 1. Seed with the 2000 NBA season → **modify: 2003-04**

Seeding a real era is unambiguously right — your one real class produced a peak-79 player
while five fictional classes produced nothing above 68. But the "27 years of real draft
classes" argument is over-weighted ~3×: this league ran six seasons in ~13 months, and
2003-04 still gives you 23 real classes.

What actually differs: (a) under-30 name recognition, and (b) fit with BBGM's modern `ovr`
formula, which weights `tp` at 0.0726 against `ins` at 0.0126 and `hgt` at 0.159 [source] —
a 2000 pool puts Shaq/Duncan/Mourning/Mutombo atop your leaderboard while Reggie Miller
outranks guys your friends remember as better.

2003-04 wins both, and hands you LeBron/Melo/Wade/Bosh as rookies already on rosters, the
Shaq-Kobe-Malone-Payton Lakers, KG's MVP year, and the Pistons.

**Set `realDraftRatings: "draft"`, not `"rookie"`** — with rookie ratings, anyone who knows
the 2003 class can see on draft night that LeBron is elite and Darko isn't, which is the
exact lookup-ability `realPlayerDeterminism: 0` exists to prevent.

### 2. 27-game season → **modify: 36 games**

The menu isn't 27/36/45 — the league was 9 teams through 2028, so 40 and 45 were both "5
meetings per opponent." The real menu is 3× / 4× / 5×, and 36 is *drop from five meetings
to four*. It's also the only length in range with an integral home/away split (18/18;
27 gives 14/13).

Measured true-talent sd is 4.0–4.3, making 27 games ~60% signal, 36 ~67%, 45 ~72%. The
27→36 gain (+7pp) is bigger than 36→45 (+4.6pp). At twice-weekly sim blocks, a full 36-game
cycle plus playoffs plus offseason is ~6 weeks.

### 3. Redraft order → **randomize with BBGM's own button, live, then open a slot-trading window**

Randomize publicly, then let humans trade draft slots for future picks before the draft.

No credit auction: the proposed one had fake currency (cash does nothing), wrong snake math
(in a snake, seat 2 picks ahead of seat 1 in every even round), and it priced a 9-point
spread on a 1,130-point sum.

Slot-for-pick trading is zero code, needs no AI participation, and does something better
than fairness: it **establishes a public price for a future first-round pick on day one**,
before anyone relearns that picks are worthless.

### 4. Contract pricing → **the exponential curve in B3, calibrated, written by script**

For "contracts that differ per year," use the **duration premium** (1yr costs 25% more per
year than 3yr). Do not build a per-year escalator — BBGM reads only `contract.amount`, so
an escalator in the JSON is invisible to the cap check, salary matching, and every AI
valuation.

### 5. Salary cap / finances → **leave `salaryCap` at 300,000 and fix revenue instead**

Every revenue line, every expense line, and `maxContract`'s effect are all proportional to
the cap, so changing it is a pure unit change with zero effect on solvency.

`pop` 1.0 → ~3.5, `stadiumCapacity` 25,000 → 32,000, `minPayroll` → 120,000,
`luxuryPayroll` → 336,000, `luxuryTax` → 1.5, `budget: false`.

Turn on **inflation** (`inflationAvg: 3`) — the cap drifts up on its own, yesterday's max
becomes tomorrow's bargain, and bad long contracts shrink in real terms with no edits.

And know that none of this gates a decision: `updateOwnerMood` early-returns with 5 human
teams. This is a fix for a page, not for the league.

### 6. Five of ten human-managed → **agree, and it's the best thing about the setup — once you turn the AI on**

Publish a short charter: the engine runs the AI teams; the commissioner does not accept or
reject trades on their behalf; AI trades are auto-published to the site from the events
array after the fact; if an AI roster drops below `minRosterSize`, sign the highest-ovr
available free agent at the minimum, no discretion.

**Do not build a 24-hour pre-commit veto window.** BBGM has no trade rollback, so "two flags
voids it" means hand-reconstructing two rosters, two payrolls, two pick sets and two sets of
expirations in god mode. Post-hoc transparency is free; a pre-commit hold dies in season 2.

Say out loud before the redraft that **an AI team is allowed to win.**

### 7. Anti-dynasty → **modify: you're solving the wrong end**

Four champions in five seasons. You don't have a repeat-title problem, you have a Durham
problem. Levers that actually move the floor:

- Reverse-standings priority everywhere
- A custom lottery with real weight (worst team 40% at #1)
- `rookieContract`'s flat **+8** mood component — four years in which a losing team
  literally cannot be out-recruited for its own draft pick [source]
- `playersRefuseToNegotiate: false`
- `budget: false`
- `neutralSite: "finals"`

**Cut the repeater tax, escalating luxury tax, and revenue sharing.** Payroll and winning
are uncorrelated in this league (**r = 0.023 across 47 team-seasons**), and the 2030 luxury
tax cost champion Cambridge **$9,000** while costing the 20-25 Gooners **$120,000**. Every
money-based penalty targets a variable with no relationship to success and hits the wrong
team by a factor of thirteen.

### 8. Roster size → **`maxRosterSize: 13`, `minRosterSize: 10`**

15-with-10-active is a no-op — the sim already gives the top 10 players 94.1% of minutes and
weights 11–15 at exactly zero. You'd spend your one big rules change on something the engine
does for free.

A flat 10 is worse: `minRosterSize` is a hard block (`checkRosterSizes` refuses to advance
the sim), so one injury or waive forces a signing — which is *more* free agency. [source]

Don't raise the floor to 11 either: with five part-time managers that converts one
inattentive friend into a league-wide stall.

13/10 leaves three spots of genuine slack: injury absorption plus salary filler for a
125%-matched trade. (Injured players count toward the floor, so injuries can never make a
roster illegal.)

### 9. Draft rounds → **2, and it's free**

Class size is `max(round(rounds × teams × 7/6), 23)`, which evaluates to **23 at either 1 or
2 rounds** for fictional classes [source] — two rounds costs nothing in quality and doubles
pick supply. Don't go to 3: that sets the target to 35 and BBGM explicitly degrades the
extras via `player.bonus(p, −ovrDiff/2)`.

But 2 rounds is not why picks were worthless. Two things were:

- `draftPickAutoContractPercent: 25` at a $50,000 max meant the **#1 pick signed for $12,500
  — to the dollar, the league median salary.** Zero surplus.
- With `forceRetireAge: 0`, no top-10 roster slot ever opened for a rookie to occupy.

Fix both: **`draftPickAutoContractPercent` 25 → 10** and **`rookiesCanRefuse` → false**. The
second is real restricted free agency, verified end to end (`selectPlayer` sets `rookie: true`
under soft cap → `newPhaseResignPlayers` sets `rookieResign` → `moodComponents.rookieContract = 8`
→ `moodInfo` forces `willing = true`) [source], and it suppresses the up-to-50% bad-mood
markup. On a 3-year deal a #1 pick goes from ~$22,000 of lifetime surplus to roughly
**$109,000**.

Keep `rookieContractLengths` at `[3,2]` — `[5,3]` would lock 50 of 130 roster spots on
untouchable paper.

### 10. Rescale displayed ratings → **agree; the website is the only surface where you can**

`ovr` is a hardcoded weighted sum of 15 sub-ratings plus a hardcoded five-branch fudge
factor; there is no gameAttribute for it. [source]

Ship a **fixed piecewise-linear display transform** with anchors:

```
(0,0) (14,3) (55,40) (75,90) (85,99) (100,100)
```

applied to both `ovr` and `pot`, in every season. On the real 2031 roster that takes
**sd 7.70 → 14.87 (1.93×)**, turning 149 players in a mush into 4 at 90+, 4 at 80–89, 18 at
70–79, and 21 at or below 29.

Four non-negotiable conditions:

1. **Derive the anchors once from the NEW league's first post-redraft roster and freeze them
   forever.** The ones above are fit to a league you're deleting.
2. **Fixed anchors only, never percentile or z-score.** A league-relative transform silently
   rewrites `history.html` (139KB), `records.html` (92KB) and every career chart on each
   rebuild.
3. `simmodel.py` (`fa_salary_score`, `_player_current_ovr`, `current_team_ovr`, line 189
   `impact=(ovr−50)*0.12`) and `projections.py` **must keep reading raw `ovr`** — they're
   calibrated on it.
4. Render season-over-season **deltas in raw points** — the 55–75 band has slope 2.5, so an
   ordinary ±4 prog would otherwise render as ±10.

Layer **tier badges** on top (Superstar / All-League / Starter / Rotation / Bench / Fringe),
with cutoffs defined on **raw** ovr so they survive the one anchor recalibration.

And add **BPM and VORP** columns next to it — 2030 qualified players (n=104) ran **−6.3 to
+10.4 with sd 3.72**, a fully NBA-shaped distribution that needs no invented scale and stays
reconcilable with the app.

---

## Part 4 — Open calls (your decision)

1. **Era: 2003-04 vs 2015-16.** Recommendation is 2003-04. If under-30 name recognition
   dominates everything else for your group, 2015-16 wins outright and fits BBGM's modern
   `ovr` weighting best. Cost: 11 real draft classes instead of 23 — still nearly double
   this league's demonstrated lifespan.
2. **`difficulty: 0.25`.** Mood modulation applies **only** to teams in `userTids`, so once
   you cut to five humans this becomes a precise in-engine handicap on human free-agency
   power that leaves the AI alone. Cost: it also shaves ~2.5% off AI trade willingness,
   which cuts against goal #1.
3. **Playoff field: 6 teams with 2 byes vs 8 teams with none.** Recommendation is 6 + byes +
   `[1,5,7]` — the bye is what pays the regular season back for widening the field, and a
   one-game round for seeds 3–6 is the highest-variance format BBGM offers. The counter is
   real: a bye protects exactly the team you least want protected. To punish the top seed
   instead: 8 teams, 0 byes, `[3,5,7]`.
4. **Declared 5-season era, or open-ended?** Your last league didn't end, it stalled — 2031
   day 5, dark for 12 days, abandoned. A declared 5-season era with a pre-announced renewal
   decision costs nothing and turns the next reboot into a scheduled event. 10 seasons is
   not credible from a group that has never finished three.
5. **Is the site's ledger a hard constraint or a scoreboard?** `finance.py` already computes
   `surplus_next`. The only question is whether a negative number is a commissioner veto on
   signings. Leaning veto — but it means saying no to a friend once or twice a year, and
   since nothing in BBGM reads cash, it's the *only* thing that would make the finance pages
   matter.

---

## Part 5 — Cut list (do not re-propose)

| Idea | Why it's dead |
|---|---|
| Re-denominate the cap by schedule length | `writeTeamStats` multiplies revenue by `82/numGames` and divides expenses by `numGames` — season totals are invariant to schedule length. |
| `maxContract` as a % of cap | `genContract` has no `salaryCap` term. Raising the max inflates every contract 1.62×; it does not create a star premium. |
| Widen the real ratings distribution (k=1.35 stretch) | Top-3 mean ovr is the best win% predictor (r=0.500). Stretching multiplies exactly what Cambridge monopolized. |
| Percentile / z-score / min-max rescaling | Season-relative; silently rewrites 230KB of history pages on every rebuild. |
| `hofFactor: 3` | It multiplies the *threshold* (`total + df > 120 × scaleFactor × hofFactor`) — 3 makes the Hall three times harder. `gameAndSeasonLengthScaleFactor` already corrects for short seasons. Leave at 1. |
| `challengeNoFreeAgents: true` | Works as advertised, but you run FA as a Python fill draft, so it gates a UI you bypass — and stacked on the AI teams' −3 mood penalty it leaves five teams with no self-repair path. |
| Per-year contract escalator in the JSON | BBGM reads only `contract.amount`. Invisible to the cap check, salary matching, and every AI valuation. |
| Stretch provision in `finance.py` | `getPayroll` includes `releasedPlayers`, so display-only relief doesn't relieve. `maxContractLength: 4` is the same escape valve for free. |
| Repeater tax / repeat-offender luxury tax / revenue sharing | Payroll↔winning r = 0.023. Money penalties target a variable unrelated to success. |
| Reverse-order **waiver** priority | BBGM has no waiver system; released players go straight to FA. Buildable as a manual claim window, but there's nothing worth claiming. |
| Full-league lottery (`draftLotteryCustomNumPicks: 10`) / `randomLottery` | Compresses expected draft slot to a 3.92–7.06 band, deleting the redistribution Durham needs. |
| Positional scarcity cards at the redraft | `pos` is a derived cosmetic label; the sim has no positional logic. Also forces you to hand-draft for the AI teams you just automated. |
| A 10-man *active* list | The sim already does it — top 10 take 94.1% of minutes, 11–15 weight exactly 0. 450 playing-time edits per season for zero simulated effect. |
| Auction draft (full or hybrid) | Five real bidders and five sock puppets isn't price discovery. The hybrid also hands the humans all 20 of the league's best players in year 1. |
| Commissioner trade windows / brokering ritual | Self-described as "most likely to quietly stop happening in season 3." Keep only the standing rule that three-team trades are legal, executed as two chained god-mode legs in the same sim day. |
| Divisions / 40-game rivalry schedule | You already have 1 conf / 1 div. Divisions with `numGamesDiv: null` change a standings header. `playoffsNumTeamsDiv: 1` risks handing a berth to an unmanaged team. |
| The SMP Cup group-stage overlay | 200–300 lines of generator code, self-described as decorative — prescribed by the same document diagnosing generator work as what killed the league. |
| Custom draft-class uploads | 23 seasons away. A mechanic arriving after your demonstrated lifespan has ended four times over. |
| Forced manager rotation / hand-balanced AI rosters | Six seasons is the only reason "Cambridge" means anything. The reboot *is* the reset. |
| Tuned aging curve | Genuinely impossible — hardcoded per rating in `developSeason.basketball.ts`. `forceRetireAge` and `minRetireAge` are the only two dials. |

---

## Part 6 — Custom code, scoped

Everything below lives in this repo. **Items 1–2 are the cheapest wins on the whole list.**

| # | What | Where | Size | Upkeep |
|---|---|---|---|---|
| 1 | Delete the `ovr < 50` free-agent filter (keep a `pot` floor if the page needs trimming) | `scripts/smp/core.py:517`, `scripts/smp/pages/league.py:445` | **2 lines** | none |
| 2 | Cap-sheet table: payroll, room vs cap, expiring salary, dead money, contracts with 2+ yrs, roster count | `scripts/smp/pages/trade.py` | ~60 lines | none |
| 3 | Contract pricing script (curve + calibration + age/duration factors) | new `scripts/price_contracts.py` | ~40 lines | at creation + new signings each offseason |
| 4 | SMP rating transform + tier badges | new fn in `scripts/smp/derived.py`, pre-pass in `build.py`, ~14 display swaps (`core.py:1208`, `league.py:358/502/1047/1193`, `player.py:461/937`, `home.py:748/1117/1186`, `trade.py:69`, `appdata.py:143`, `charts.py:28/527/701`) | ~25 lines + swaps | none |
| 5 | BPM / VORP columns next to ovr; BPM as default sort on leaders | display layer | small | none |
| 6 | One-time pool prune to ~148 living players (`tid: -3` + `retiredYear`) | new `scripts/prune_pool.py` | ~40 lines | one-time |
| 7 | Flatten the revenue curve: `BASE = 0.70 × cap`, `PER_WIN = 0.02 × cap × (27/G)` | `scripts/smp/finance.py` (`FIN_PER_WIN = 12800` today) | 2 constants | none |
| 8 | Auto-generated trade block: every player outside his team's top 8, plus every expiring on a sub-.500 team | new page | ~40 lines | none |
| 9 | Fits engine: enumerate 1-for-1 and 2-for-1 swaps, score with `simmodel.current_team_ovr`, publish top 5 per team above a ≥1.0 projected-win threshold, validate 125% matching and `gamesUntilTradable` | new `scripts/smp/pages/fits.py` | 250–400 lines | none |
| 10 | Daily digest to the group chat (biggest upset under 35% pregame, biggest odds mover, best line, sharpest standings change) | CI step; deltas from `league-data/odds_history.json` | ~10 lines *if Discord webhook* | none |

Two audits while you're in there: the `ovr < 50` thresholds need restating in whichever
scale you keep (raw 50 is SMP 34); and `finance.py`'s `FIN_RETENTION` / `FIN_ADJUSTMENTS`
hand-maintained dicts already carry three paragraphs of comments about stale entries — do
not add a third dict of that shape.

---

## Part 7 — Order of operations

**Phase 0 — before touching anything (30 min).** Snapshot `league-data/`. Ship custom-code
items **1 and 2** against the *old* league so you can see the FA band and the cap spread
before you delete it. Confirm with the group: era, season length, roster size, and that an
AI team is allowed to win.

**Phase 1 — create the league (one evening).** Create New League → real players → 2003-04 →
real rosters. Set every setting in §A **at creation** — `randomDebuts`, `realDraftRatings`,
and the conference/division structure are creation-time only and cannot be rescued later.
Then, before anything else: `userTids` = the five human tids, reset all ten `hype` to 0.50,
set the `pop` ladder, set `stadiumCapacity`.

**Phase 2 — shape the pool (script, 1 hour).** Export. Run the prune to ~148 living players.
Measure the pool's top `value` and set `maxContract` by inverting `genContract`. Re-import.

**Phase 3 — the redraft (one evening, ~75 human picks).** Set `minRosterSize: 15` first —
`genOrderFantasy` hardcodes `numRounds = minRosterSize` [source], and forgetting this gives
you a 10-round draft and hands the best leftovers to whoever is most online. Randomize the
order publicly; open the slot-for-future-picks trading window; run 13 rounds; AI teams
auto-draft. Reset `minRosterSize: 10` after.

**Phase 4 — write the contracts (script, 30 min).** Run the pricing script. Assign lengths
by draft slot (slots 1–3 → 4yr, 4–7 → 4, 8–10 → 3, round 2 → 3, round 3+ → 2, minimums → 1)
so the top-10 players' expiries land across three different summers with zero per-player
judgment. Verify the expiry histogram is ≤ ~33% in any year:

```python
Counter(p['contract']['exp'] for p in players if p['tid'] >= 0)
```

Diff the JSON, keep the pre-edit export, re-import.

**Phase 5 — publish, then play (1 day).** Post the constitution: the pop ladder, the AI
charter, reverse-standings priority, the FA draft format, `forceRetireAge: 36` (set it
before the redraft and never move it — moving it later to save someone's favorite is the
fastest way to lose commissioner credibility), the era length, and the sim-block calendar
for the whole first season. Then sim.

**Phase 6 — the standing discipline.**

- Two fixed sim blocks per week (5 sim days each, rosters lock 12h prior). **The block runs
  on schedule regardless of who's ready** — a rule gated on all humans being ready is a veto
  handed to the least engaged person.
- A **hard 72-hour offseason** on a fixed clock covering re-signings, the draft and the FA
  draft.
- A **feature freeze on `scripts/smp` between the first and last sim block of a season.**

That last one is the actual lesson from the git log: the 2031 offseason burned four days on
generator mega-commits ("P3+P4 ten-feature-cluster overhaul," "finance revamp," "P7 final
revisions," "P8 final polish"), the league ran five more game days, and it stopped. **It did
not die of in-season grind. It died of the offseason.**

---

## One technique that removes most of the remaining upkeep

BBGM's import schema accepts a top-level `scheduledEvents` array of
`{type, season, phase, info}`, and `processScheduledEvents` handles `type: "gameAttributes"`.
[source] Write the whole era's settings changes into the export **once, at reboot** — cap
growth, playoff format changes, payroll steps — and BBGM applies each at the specified season
and phase automatically, forever.

Every "once per season" item in this document becomes twenty lines of JSON, once.
