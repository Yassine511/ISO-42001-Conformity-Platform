/**
 * Dependency audit gate.
 *
 * Replaces a bare `npm audit --audit-level=high`, which has no way to say
 * "this advisory has no fix and does not apply to us". The two available
 * reactions to that situation are both bad: leave CI permanently red until
 * upstream ships a fix (so nobody reads it any more), or drop the gate
 * (so nothing is checked). This script adds the third: fail on every
 * high/critical advisory EXCEPT ones listed below with a reason and a review
 * date, and fail on a stale or unnecessary exception too — so an exception
 * cannot quietly become permanent.
 *
 * Usage: node scripts/audit-gate.mjs
 */

import { execSync } from "node:child_process";

const FAIL_LEVELS = new Set(["high", "critical"]);

/**
 * Each entry must name a specific advisory, say why it cannot be fixed, why it
 * does not apply here, and when to look again. Reviewing means checking
 * whether the fixed version now exists — not extending the date.
 */
const EXCEPTIONS = [
  {
    ghsa: "GHSA-qwww-vcr4-c8h2",
    package: "react-router",
    title: "RSC Mode CSRF Bypass Allows Action Execution Before 400 Response",
    // Vulnerable range is >=7.12.0 <8.3.0. react-router 8 DOES NOT EXIST yet
    // (npm dist-tag latest = 7.18.1), so there is no version that both fixes
    // this and fixes the 6.x/<7.18 open-redirect advisories. Verified, not
    // assumed: `npm view react-router-dom versions` stops at 7.18.1.
    reason:
      "No fixed version is published (fix lands in 8.3.0; react-router 8 does not exist). " +
      "Not reachable here: the advisory is specific to RSC mode — server components, " +
      "server actions and their CSRF handling. This app is a client-only SPA on " +
      "BrowserRouter with no SSR and no RSC, and its own writes are same-origin " +
      "cookie+SameSite=Lax. Downgrading to 7.11.0 (npm's suggested 'fix') would " +
      "reintroduce the two open-redirect advisories that DO apply to <Link>/useNavigate.",
    reviewAfter: "2026-10-01",
  },
];

const raw = (() => {
  try {
    // npm audit exits non-zero when it finds anything; capture output regardless
    return execSync("npm audit --json", { encoding: "utf8", stdio: ["ignore", "pipe", "ignore"] });
  } catch (err) {
    if (err.stdout) return err.stdout;
    throw err;
  }
})();

const report = JSON.parse(raw);
const today = new Date().toISOString().slice(0, 10);

const blocking = [];
const excused = [];

for (const [name, vuln] of Object.entries(report.vulnerabilities ?? {})) {
  if (!FAIL_LEVELS.has(vuln.severity)) continue;
  const advisories = (vuln.via ?? []).filter((v) => typeof v === "object");
  // A package entry with only string `via` values is transitively affected;
  // it is covered by whichever entry actually carries the advisory.
  if (advisories.length === 0) continue;
  for (const advisory of advisories) {
    const ghsa = (advisory.url ?? "").split("/").pop();
    const exception = EXCEPTIONS.find((e) => e.ghsa === ghsa);
    if (!exception) {
      blocking.push(`${name} [${vuln.severity}] ${advisory.title} (${advisory.url})`);
    } else if (exception.reviewAfter < today) {
      blocking.push(
        `${name} [${vuln.severity}] ${advisory.title} — EXCEPTION EXPIRED ` +
          `(${exception.reviewAfter}); re-check whether a fixed version now exists`,
      );
    } else {
      excused.push(`${ghsa} (${name}) — review after ${exception.reviewAfter}`);
    }
  }
}

// An exception that no longer matches anything is itself a failure: it means
// the advisory was fixed or the dependency dropped, and the note is now
// misleading documentation.
const seen = new Set(
  Object.values(report.vulnerabilities ?? {})
    .flatMap((v) => v.via ?? [])
    .filter((v) => typeof v === "object")
    .map((v) => (v.url ?? "").split("/").pop()),
);
for (const exception of EXCEPTIONS) {
  if (!seen.has(exception.ghsa)) {
    blocking.push(
      `stale exception ${exception.ghsa} (${exception.package}) no longer matches any ` +
        `advisory — remove it from scripts/audit-gate.mjs`,
    );
  }
}

for (const line of excused) console.log(`excused: ${line}`);
if (blocking.length > 0) {
  console.error("\nBlocking advisories:");
  for (const line of blocking) console.error(`  - ${line}`);
  process.exit(1);
}
console.log(`audit gate OK (${excused.length} documented exception(s), 0 blocking)`);
