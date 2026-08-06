#!/usr/bin/env node
// Project every scheduled game by running Basketball GM's OWN game simulation.
//
// Run it by hand when the rosters or the schedule change; the OUTPUT IS COMMITTED, and
// the site build never imports this file. Same deal as scripts/faces/render.mjs and
// scripts/cutout_portraits.py, and for the same reason: the GitHub Action that builds
// the site has no zengm checkout and must never need one.
//
//     cd scripts/sim && npm install
//     node scripts/sim/project_box_scores.mjs                       # from the repo root
//     node scripts/sim/project_box_scores.mjs league-data/2004_preseason.json --sims 200
//
// Needs a Basketball GM checkout next to this repo (../zengm), or ZENGM_DIR pointing at
// one. Needs Node 22.18+, which strips TypeScript natively -- zengm's .ts sources are
// imported as-is, no build step and no bundler.
//
// Why zengm's sim and not a model of our own
// ------------------------------------------
// This league is calibrated to 2003-04: pace 90.1, three-point tendency 0.488, two-point
// accuracy 0.943, and nine more factors that live in the export's gameAttributes. A
// hand-rolled projection would drift from what the game actually does when the season is
// played, and the whole point of the feature is that it doesn't. So we shim `g` with the
// export's own gameAttributes, hand the rosters to zengm's processTeam(), and run the
// real GameSim -- the same code path core/game/play.ts uses -- N times per game.
//
// Two places we depart from zengm:
//
//  1. We never touch IndexedDB. processTeam is pure for a regular-season basketball game
//     (its only idb access is a playoffs/hockey branch), so a plain object stands in for
//     the database and nothing is persisted.
//  2. Only DRESSED players are handed to the sim. zengm dresses everyone on the roster;
//     this league dresses ten and holds the last two out, so the 11th and 12th men
//     project zero minutes rather than the ~6 and ~2 they were getting. See DRESSED.
//
// Determinism
// -----------
// The sim draws from Math.random. Math.random is replaced with a mulberry32 stream
// reseeded per gid from --seed, so the file is byte-identical across runs and a diff
// only churns when the rosters or the settings actually changed. Per-gid seeding also
// means a game's projection does not depend on which games ran before it.
//
// The shape of the output file, and why the dependencies live where they do, are in
// scripts/sim/README.md.

import { readFileSync, writeFileSync, existsSync } from "node:fs";
import { register } from "node:module";
import { basename, resolve as resolvePath } from "node:path";
import { pathToFileURL } from "node:url";
import { parseArgs } from "node:util";

const HERE = import.meta.dirname;
const REPO = resolvePath(HERE, "..", "..");

const { values, positionals } = parseArgs({
	allowPositionals: true,
	options: {
		sims: { type: "string", default: "200" },
		seed: { type: "string", default: "2004" },
		out: { type: "string" },
	},
});

const exportPath = resolvePath(
	positionals[0] ?? `${REPO}/league-data/2004_preseason.json`,
);
const outPath = resolvePath(
	values.out ?? `${REPO}/league-data/projected_box_scores.json`,
);
const numSims = Number.parseInt(values.sims, 10);
const seed = Number.parseInt(values.seed, 10);
if (!(numSims > 0) || !Number.isInteger(seed)) {
	console.error("--sims must be a positive integer and --seed an integer.");
	process.exit(1);
}

const zengmDir = resolvePath(
	process.env.ZENGM_DIR ?? resolvePath(REPO, "..", "zengm"),
);
if (!existsSync(`${zengmDir}/src/worker/core/GameSim.basketball/index.ts`)) {
	console.error(
		`No Basketball GM checkout at ${zengmDir}. Clone zengm-games/zengm next to this repo, or set ZENGM_DIR.`,
	);
	process.exit(1);
}

// ---------------------------------------------------------------------------
// Make Node look enough like a web worker for zengm's worker code to import.
// This is the same shim zengm's own node tests use (src/test/setup.ts): the
// worker/util barrel constructs a PWBWorker at module scope, which needs self
// and postMessage to exist. Nothing is ever posted anywhere.
// ---------------------------------------------------------------------------
globalThis.self = globalThis;
globalThis.window = globalThis;
globalThis.location = {};
globalThis.addEventListener = () => {};
globalThis.postMessage = () => {};

// bySport()/isSport() read this at runtime, so no build step is needed.
process.env.SPORT = "basketball";

// Redirect zengm's bare specifiers to scripts/sim/node_modules -- see zengm-resolver.mjs.
register("./zengm-resolver.mjs", import.meta.url, {
	data: {
		zengmURL: `${pathToFileURL(zengmDir).href}/`,
		selfURL: import.meta.url,
		schemaStubURL: new URL("./league-schema-stub.mjs", import.meta.url).href,
	},
});

const zengm = (path) => import(pathToFileURL(`${zengmDir}/src/${path}`).href);

const [
	{ default: GameSim },
	{ processTeam },
	{ default: g },
	{ defaultGameAttributes },
	{ unwrapGameAttribute },
] = await Promise.all([
	zengm("worker/core/GameSim.basketball/index.ts"),
	zengm("worker/core/game/loadTeams.ts"),
	zengm("worker/util/g.ts"),
	zengm("common/defaultGameAttributes.ts"),
	zengm("common/unwrapGameAttribute.ts"),
]);

// ---------------------------------------------------------------------------
// Seeded RNG. mulberry32 is 32 bits of state, which is plenty for this and keeps
// the reseed cheap -- we reseed once per game, 180 times.
// ---------------------------------------------------------------------------
const mulberry32 = (a) => () => {
	a = (a + 0x6d2b79f5) | 0;
	let t = Math.imul(a ^ (a >>> 15), 1 | a);
	t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
	return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
};

const seedForGame = (gid) =>
	(Math.imul(gid + 1, 0x9e3779b1) ^ Math.imul(seed + 1, 0x85ebca6b)) >>> 0;

// +0 so a rounded-away negative never serializes as "-0".
const round = (value, places) => Number.parseFloat(value.toFixed(places)) + 0;

// ---------------------------------------------------------------------------
// gameAttributes: zengm's defaults, then everything the export sets on top. g.get
// would unwrap the {start, value} history form itself, but unwrapping here means
// what we log below is literally what the sim will read.
// ---------------------------------------------------------------------------
const league = JSON.parse(readFileSync(exportPath, "utf8"));

for (const key of Object.keys(defaultGameAttributes)) {
	g.setWithoutSavingToDB(key, unwrapGameAttribute(defaultGameAttributes, key));
}
for (const key of Object.keys(league.gameAttributes)) {
	g.setWithoutSavingToDB(key, unwrapGameAttribute(league.gameAttributes, key));
}

// The numbers this league is calibrated with. A projection run against zengm's default
// tendencies would print a modern-NBA three-point rate onto a 2004 league (38% of shots
// from three instead of 20%), so echo them and let a human see they survived the shim.
const CALIBRATION = [
	"pace",
	"threePointTendencyFactor",
	"threePointAccuracyFactor",
	"twoPointAccuracyFactor",
	"blockFactor",
	"stealFactor",
	"turnoverFactor",
	"orbFactor",
	"assistFactor",
	"foulRateFactor",
	"ftAccuracyFactor",
	"quarterLength",
	"numPeriods",
	"numPlayersOnCourt",
];
console.log(`export: ${exportPath}`);
for (const key of CALIBRATION) {
	const fromSim = g.get(key);
	const fromExport = unwrapGameAttribute(league.gameAttributes, key);
	if (fromSim !== fromExport) {
		throw new Error(
			`${key} reached the sim as ${fromSim}, export says ${fromExport}`,
		);
	}
	console.log(`  ${key.padEnd(26)} ${fromSim}`);
}

// ---------------------------------------------------------------------------
// One processTeam() per team. It is deterministic given the same roster and the same
// g, and nothing about it varies game to game, so it runs ten times and each sim gets
// a structuredClone -- GameSim mutates the team object it is handed.
// ---------------------------------------------------------------------------
const season = g.get("season");
const playersByTid = Map.groupBy(league.players, (p) => p.tid);

// The league dresses ten; the 11th and 12th men are reserve and do not play.
const DRESSED = 10;

// Which ten dress is decided the same way the site orders a roster everywhere else --
// overall descending, then name (team.py::_sorted_team_roster). NOT by BBGM's own
// rosterOrder: the two disagree on ties, and on two of the ten rosters they name a
// different reserve pair than the depth chart's Reserve row does. The site says out loud
// who sits, so the projection has to bench those exact two.
const dressedFor = (tid) => {
	const roster = [...(playersByTid.get(tid) ?? [])];
	roster.sort((a, b) => {
		const ovrA = a.ratings.at(-1).ovr;
		const ovrB = b.ratings.at(-1).ovr;
		if (ovrA !== ovrB) {
			return ovrB - ovrA;
		}
		return `${a.firstName} ${a.lastName}`.localeCompare(`${b.firstName} ${b.lastName}`);
	});
	// processTeam re-sorts by rosterOrder, which is what picks the starting five out of
	// the ten; slicing only decides who is available to it.
	return roster.slice(0, DRESSED);
};

const teamTemplates = new Map();
for (const t of league.teams) {
	if (t.disabled) {
		continue;
	}
	const teamSeason = t.seasons.findLast((row) => row.season === season) ?? {
		won: 0,
		lost: 0,
		tied: 0,
		otl: 0,
	};
	teamTemplates.set(
		t.tid,
		await processTeam(
			{
				tid: t.tid,
				playThroughInjuries: t.playThroughInjuries,
			},
			{
				won: teamSeason.won,
				lost: teamSeason.lost,
				tied: teamSeason.tied,
				otl: teamSeason.otl,
				cid: t.cid,
				did: t.did,
			},
			dressedFor(t.tid),
		),
	);
}

// ---------------------------------------------------------------------------
// Sim.
// ---------------------------------------------------------------------------
const STATS = [
	"min",
	"pts",
	"trb",
	"ast",
	"stl",
	"blk",
	"fg",
	"fga",
	"tp",
	"tpa",
	"ft",
	"fta",
	"orb",
	"tov",
	"pf",
	"gs",
];

const injuryRate = g.get("injuryRate");
const minutesPerTeam =
	g.get("numPlayersOnCourt") * g.get("quarterLength") * g.get("numPeriods");
const minutesPerOvertime = g.get("numPlayersOnCourt") * g.get("overtimeLength");

const games = {};
const leagueTotals = {};
let teamGames = 0;
let overtimeTotal = 0;
let worstMinutesError = 0;

const startedAt = Date.now();
for (const scheduled of league.schedule) {
	const { gid, homeTid, awayTid } = scheduled;
	Math.random = mulberry32(seedForGame(gid));

	const totals = new Map(); // pid -> {tid, stat sums}
	for (const tid of [homeTid, awayTid]) {
		for (const p of teamTemplates.get(tid).player) {
			totals.set(p.id, {
				tid,
				sums: Object.fromEntries(STATS.map((stat) => [stat, 0])),
			});
		}
	}
	let homePts = 0;
	let awayPts = 0;
	let homeWins = 0;

	for (let i = 0; i < numSims; i++) {
		const result = new GameSim({
			gid,
			day: scheduled.day,
			// teams[0] is the home team -- see the teamsInput in core/game/play.ts.
			teams: [
				structuredClone(teamTemplates.get(homeTid)),
				structuredClone(teamTemplates.get(awayTid)),
			],
			doPlayByPlay: false,
			homeCourtFactor: 1,
			neutralSite: false,
			allStarGame: false,
			baseInjuryRate: injuryRate,
		}).run();

		homePts += result.team[0].stat.pts;
		awayPts += result.team[1].stat.pts;
		if (result.team[0].stat.pts > result.team[1].stat.pts) {
			homeWins += 1;
		}
		overtimeTotal += 2 * result.overtimes;

		const expectedMinutes =
			minutesPerTeam + minutesPerOvertime * result.overtimes;
		for (const t of result.team) {
			let teamMinutes = 0;
			for (const p of t.player) {
				const sums = totals.get(p.id).sums;
				sums.min += p.stat.min;
				sums.pts += p.stat.pts;
				sums.trb += p.stat.orb + p.stat.drb;
				sums.ast += p.stat.ast;
				sums.stl += p.stat.stl;
				sums.blk += p.stat.blk;
				sums.fg += p.stat.fg;
				sums.fga += p.stat.fga;
				sums.tp += p.stat.tp;
				sums.tpa += p.stat.tpa;
				sums.ft += p.stat.ft;
				sums.fta += p.stat.fta;
				sums.orb += p.stat.orb;
				sums.tov += p.stat.tov;
				sums.pf += p.stat.pf;
				sums.gs += p.stat.gs;
				teamMinutes += p.stat.min;
			}
			// Every second of the game is charged to exactly numPlayersOnCourt players,
			// so this is an identity, not an approximation -- if it ever drifts, the
			// team handed to the sim was not the team we think it was.
			const error = Math.abs(teamMinutes - expectedMinutes);
			if (error > 1e-6) {
				throw new Error(
					`gid ${gid} team ${t.id}: ${teamMinutes} minutes, expected ${expectedMinutes}`,
				);
			}
			worstMinutesError = Math.max(worstMinutesError, error);
			for (const [stat, value] of Object.entries(t.stat)) {
				if (typeof value === "number") {
					leagueTotals[stat] = (leagueTotals[stat] ?? 0) + value;
				}
			}
			teamGames += 1;
		}
	}

	const players = [...totals]
		.map(([pid, { tid, sums }]) => ({
			pid,
			tid,
			...Object.fromEntries(
				STATS.map((stat) => [
					stat,
					round(sums[stat] / numSims, stat === "gs" ? 2 : 1),
				]),
			),
		}))
		.sort(
			(a, b) =>
				(a.tid === homeTid ? 0 : 1) - (b.tid === homeTid ? 0 : 1) ||
				b.min - a.min ||
				a.pid - b.pid,
		);

	games[gid] = {
		home_tid: homeTid,
		away_tid: awayTid,
		home_pts: round(homePts / numSims, 1),
		away_pts: round(awayPts / numSims, 1),
		home_win_pct: round(homeWins / numSims, 3),
		players,
	};
}

writeFileSync(
	outPath,
	`${JSON.stringify(
		{
			season,
			sims: numSims,
			generated_from: basename(exportPath),
			games,
		},
		undefined,
		1,
	)}\n`,
);

// ---------------------------------------------------------------------------
// Summary, so a re-run shows at a glance whether the league still looks like 2003-04.
// ---------------------------------------------------------------------------
const per = (stat) => leagueTotals[stat] / teamGames;
const pct = (made, att) => (leagueTotals[made] / leagueTotals[att]).toFixed(3);
console.log(
	`\n${league.schedule.length} games x ${numSims} sims in ${((Date.now() - startedAt) / 1000).toFixed(0)}s -> ${outPath}`,
);
console.log("per team per game:");
console.log(
	`  ${per("pts").toFixed(1)} pts  ${per("fga").toFixed(1)} fga  ${per("tpa").toFixed(1)} tpa (${((100 * leagueTotals.tpa) / leagueTotals.fga).toFixed(1)}% of fga)`,
);
console.log(
	`  ${(per("orb") + per("drb")).toFixed(1)} trb  ${per("ast").toFixed(1)} ast  ${per("tov").toFixed(1)} tov  ${per("stl").toFixed(1)} stl  ${per("blk").toFixed(1)} blk  ${per("pf").toFixed(1)} pf`,
);
console.log(
	`  ${pct("fg", "fga")} fg%  ${pct("tp", "tpa")} 3p%  ${pct("ft", "fta")} ft%`,
);
console.log(
	`  ${per("min").toFixed(3)} min (${minutesPerTeam} + ${minutesPerOvertime} x ${(overtimeTotal / teamGames).toFixed(4)} ot), worst single-game error ${worstMinutesError.toExponential(1)}`,
);
