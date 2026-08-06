// Stands in for zengm's build/files/league-schema.json, which its build generates and
// does not check in. Reached only because worker/core/league/createStream.ts imports a
// constant from api/leagueFileUpload.ts, which imports the schema at module scope. The
// harness never validates a league file, so the schema is never read.
export default {};
