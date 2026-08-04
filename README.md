# chronicaria.github.io

Static site for the SMP Basketball League.

The site is generated from Basketball GM-style JSON exports in `league-data/`.
The generated league pages live at the repository root so GitHub Pages serves
the league homepage at `/`.

SMP II is the current league: it tips off in 2026 with real 2003-04 NBA players,
a 36-game season, 12-man rosters, a $100M hard cap, and a four-team best-of-five
playoff. Pages that are made of league history — Rivalries above all — are
skipped until games have actually been played, so the year-one nav is shorter
than it will be in year two.

## Structure

```
index.html          League homepage
schedule.html       Schedule and scores
players/            Player index and player pages
teams/              Team pages
games/              Box score pages (none until games are played)
assets/             League CSS, JS, and search index
league-data/        Current league's JSON exports + odds_history.json
league-data/smp1/   Archived league: SMP I, 2026-2031
scripts/            League site generator
```

Only the current league's exports belong at the top level of `league-data/`; a
finished league is archived to `league-data/<league>/` along with its
`odds_history.json` ledger. This matters, because a reboot resets the season
counter (SMP I ran 2026-2031, SMP II restarts at 2026), so "which export is
newest" cannot be decided from the files themselves — it is decided by which
directory they sit in.

## Regenerate

```sh
python3 scripts/league_generator.py league-data/2026_day1.json --out .
```

The `Build SMP league site` GitHub Action regenerates the root site on pushes to
`main`, from whichever `league-data/*.json` export is furthest along by
(season, phase, games played).
