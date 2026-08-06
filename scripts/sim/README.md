# scripts/sim — projected box scores

Runs Basketball GM's own game simulation over every scheduled game in the export and
writes per-player projected minutes and box-score lines to
`league-data/projected_box_scores.json`.

Local tool with committed output, like `scripts/faces/render.mjs` and
`scripts/cutout_portraits.py`. The GitHub Action that builds the site has no zengm
checkout and must never need one.

```
cd scripts/sim && npm install
node scripts/sim/project_box_scores.mjs                    # from the repo root
node scripts/sim/project_box_scores.mjs league-data/2004_preseason.json --sims 200
```

Flags: `--sims` (default 200), `--seed` (default 2004), `--out`. The committed file is
built at **1000** sims (~5 minutes); 200 is too noisy to print a tenth of a minute from —
at 200 eight of the 180 games swapped favourite between honest seeds.

Only the ten who dress are handed to the sim. zengm dresses the whole roster; this league
plays ten, and the two held out are the ones the depth chart's Reserve row names — the
site's own player-list order (overall desc, then name), not BBGM's `rosterOrder`, which
disagrees with it on ties for two of the ten teams.

Needs Node 22.18+ (native TypeScript stripping) and a Basketball GM checkout at
`../zengm`, or `ZENGM_DIR` pointing at one. ~85 s for 180 games × 200 sims; ~295 s at 1000.

## Why zengm's sim

The league carries its own 2003-04 calibration in `gameAttributes` — pace 90.1,
threePointTendencyFactor 0.488, twoPointAccuracyFactor 0.943, and nine more. Any model
we wrote ourselves would drift from what the game actually does when the season is
played, which is exactly what the projection is supposed to predict. So `g` is shimmed
with the export's own gameAttributes, the rosters go through zengm's `processTeam()`,
and the real `GameSim` runs — the same code path `core/game/play.ts` takes.

The factors reaching the sim is the thing worth checking, and it is easy to check: run
the same rosters with zengm's default tendencies instead and you get 38.1% of shots from
three and 112 points a game. With this league's factors you get 19.6% and 97.

## Getting zengm's dependencies without touching zengm

`/Users/.../zengm` is the user's separate checkout and stays read-only, so it has no
`node_modules` and must not get one. Instead the packages live here, pinned to the
versions in zengm's own `package.json`, and `zengm-resolver.mjs` registers a resolve
hook that re-points any bare specifier coming from a file under the zengm root at this
directory. Node resolves bare specifiers by walking up from the importing file, so
without the hook zengm's sources would never find them.

Seven direct dependencies, all pure JS, ~12 MB installed. What pulls each one in:

| package | reached from |
| --- | --- |
| `just-clone` | `common/helpers.ts` — `helpers` is used throughout the sim |
| `@dumbmatter/idb` | `worker/db/` — the module graph loads it; no database is ever opened |
| `promise-worker-bi` | `worker/util/promiseWorker.ts`, constructed at module scope by the `worker/util` barrel |
| `facesjs` | `worker/util/face.ts` |
| `zod` | `common/types.ts` |
| `ajv`, `json-web-streams` | `worker/api/leagueFileUpload.ts` |

The last three arrive because `loadTeams.ts` imports the `worker/core` barrel, which is
transitively the whole worker. That is the price of using zengm's real `processTeam`
rather than a copy of it, and it seemed the better trade.

One thing is stubbed: `worker/core/league/createStream.ts` takes a single constant from
`api/leagueFileUpload.ts`, which imports `build/files/league-schema.json` at module
scope. That file is a build artifact zengm generates and does not check in — it is
absent from a fresh clone, and generating it would mean writing into the zengm checkout.
`league-schema-stub.mjs` stands in for it. Nothing we call validates a league file, so
the schema is never read.

## Determinism

The output is committed, so a diff that churns on every run would be worthless.
`Math.random` is replaced with a mulberry32 stream reseeded per gid from `--seed`, which
makes the file byte-identical across runs and keeps a game's projection independent of
which games ran before it. Verified: two full runs, and a third after deleting and
reinstalling `node_modules`, all produced the same sha256.

## Output

`league-data/projected_box_scores.json`, keyed by the export's own gid:

```
{ "season": 2004, "sims": 1000, "generated_from": "2004_preseason.json",
  "games": { "180": {
    "home_tid": 5, "away_tid": 7,
    "home_pts": 105.0, "away_pts": 95.6,      // mean final score
    "home_win_pct": 0.755,                     // fraction of sims the home team won
    "players": [ { "pid": 4, "tid": 5, "min": 34.2, "pts": 18.6, "trb": 5.1,
                   "ast": 2.4, "stl": 0.9, "blk": 0.3, "fg": 6.8, "fga": 14.9,
                   "tp": 2.1, "tpa": 5.2, "ft": 2.9, "fta": 3.4, "orb": 1.2,
                   "tov": 1.8, "pf": 2.2, "gs": 0.87 } ] } } }
```

Player figures are means across sims, per game, one decimal (`gs` — the fraction of sims
he started — to two). Every DRESSED player gets a row even if he never appeared,
home team first, then minutes descending; the page decides what to show.

Minutes sum to `numPlayersOnCourt × quarterLength × numPeriods` per team per game, plus
`numPlayersOnCourt × overtimeLength` for each overtime the sims played. So the mean is a
little over 240 — 241.2 at present, which is 240 + 25 × 0.048 overtimes. The harness
asserts the identity holds every sim and prints the worst error (currently 2.8e-13).
