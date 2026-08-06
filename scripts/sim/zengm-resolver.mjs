// Module resolver hook: let zengm's sources find OUR node_modules.
//
// Node resolves a bare specifier by walking up from the importing file, so
// zengm/src/**/*.ts asking for "just-clone" searches the zengm checkout and its
// parents -- never this directory. The zengm checkout has no node_modules and must
// not get one, so instead we intercept every bare specifier coming from a file under
// the zengm root and re-resolve it as if scripts/sim/ had asked for it.
//
// Registered by loader.mjs, which is what `node --import` points at.

import { isBuiltin } from "node:module";

let zengmURL; // file:// URL of the zengm checkout, with trailing slash
let selfURL; // file:// URL of a file in scripts/sim/, used as the stand-in importer
let schemaStubURL;

// worker/core/league/createStream.ts pulls one constant out of api/leagueFileUpload.ts,
// which imports build/files/league-schema.json -- a build artifact zengm generates and
// does not check in, so it is absent from a fresh clone. We never validate a league
// file, so point that import at an empty object rather than running zengm's build.
const SCHEMA_SUFFIX = "/build/files/league-schema.json";

export const initialize = (data) => {
	zengmURL = data.zengmURL;
	selfURL = data.selfURL;
	schemaStubURL = data.schemaStubURL;
};

export const resolve = (specifier, context, nextResolve) => {
	if (
		specifier.endsWith(SCHEMA_SUFFIX.slice(1)) &&
		context.parentURL?.startsWith(zengmURL)
	) {
		return { url: schemaStubURL, format: "module", shortCircuit: true };
	}

	if (
		context.parentURL?.startsWith(zengmURL) &&
		!specifier.startsWith(".") &&
		!specifier.startsWith("/") &&
		!specifier.startsWith("#") &&
		!/^[a-z][a-z0-9+.-]*:/i.test(specifier) &&
		!isBuiltin(specifier)
	) {
		return nextResolve(specifier, { ...context, parentURL: selfURL });
	}

	return nextResolve(specifier, context);
};
