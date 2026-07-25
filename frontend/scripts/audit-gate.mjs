/**
 * Dependency audit gate.
 *
 * Replaces a bare `npm audit --audit-level=high`, which has no way to say
 * "this advisory has no fix and does not apply to us". The two available
 * reactions to that situation are both bad: leave CI permanently red until
 * upstream ships a fix (so nobody reads it any more), or drop the gate
 * (so nothing is checked). This script adds the third: fail on every
 * high/critical advisory EXCEPT ones documented below, and make sure an
 * exception cannot quietly become permanent.
 *
 * How an exception stays honest — two mechanisms, by what is knowable:
 *
 * - `fixedIn` (preferred): the advisory names the version that will fix it.
 *   The gate asks the npm registry on EVERY run whether that version has been
 *   published. The day it exists, the gate fails with "upgrade and remove the
 *   exception" — CI turns red exactly when action is possible, never on an
 *   arbitrary calendar date that fires regardless of whether anything changed.
 *   (This is not hypothetical: the mechanism's first live run caught that
 *   react-router 8.3.0 HAD been published — the original exception had
 *   checked the wrong package, react-router-dom, which v8 retired — and the
 *   upgrade removed the exception the same day.)
 *
 * - `reviewAfter` (fallback, for advisories whose fix version is unknown):
 *   a review date, after which the gate fails until a human re-checks.
 *   Reviewing means checking whether a fix now exists — not extending the
 *   date.
 *
 * Either way, an exception that no longer matches any advisory is itself a
 * failure (the note has become misleading documentation).
 *
 * Usage: node scripts/audit-gate.mjs
 */

import { execSync } from "node:child_process";

const FAIL_LEVELS = new Set(["high", "critical"]);

/**
 * Each entry must name a specific advisory (ghsa + package + title), say why
 * it does not apply here (reason), and carry either `fixedIn` (the version
 * that will fix it — auto-checked against the registry on every run) or
 * `reviewAfter` (a YYYY-MM-DD date, only when no fix version is known).
 * Currently empty — react-router's RSC-mode CSRF exception was removed when
 * the 8.3.0 upgrade landed.
 */
const EXCEPTIONS = [];

/** True once `pkg@version` is published on the registry. A registry/network
 * error counts as "not yet published" (fail open): the gate runs right after
 * `npm ci`, so a dead registry has already failed the job for a clearer
 * reason, and a transient error must not flip this gate red on its own. */
function fixPublished(pkg, version) {
  try {
    const out = execSync(`npm view ${pkg}@${version} version --json`, {
      encoding: "utf8",
      stdio: ["ignore", "pipe", "ignore"],
    });
    return out.trim().length > 0;
  } catch {
    return false;
  }
}

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

// Fail CLOSED on an unrecognized report shape. `report.vulnerabilities ?? {}`
// alone means a future npm that renames the key (npm 6 called it `advisories`)
// makes the loop below iterate nothing and the gate print "OK" — a gate that
// cannot tell "no advisories" from "I did not understand the report" is worse
// than no gate, because it looks green. `metadata.vulnerabilities` is the
// independent tally npm emits alongside; requiring both to exist, and their
// totals to agree, means a shape change is a loud failure instead of a pass.
if (typeof report.vulnerabilities !== "object" || report.vulnerabilities === null) {
  console.error(
    "npm audit --json did not return a `vulnerabilities` object — the report " +
      "format changed. Update scripts/audit-gate.mjs; do NOT assume the absence " +
      "of findings.",
  );
  process.exit(1);
}
const counts = report.metadata?.vulnerabilities;
if (typeof counts !== "object" || counts === null) {
  console.error(
    "npm audit --json returned no `metadata.vulnerabilities` tally — cannot " +
      "cross-check that the parsed entries are the complete set.",
  );
  process.exit(1);
}
const declaredTotal = Object.entries(counts)
  .filter(([level]) => level !== "total")
  .reduce((sum, [, n]) => sum + (typeof n === "number" ? n : 0), 0);
const parsedTotal = Object.keys(report.vulnerabilities).length;
if (declaredTotal !== parsedTotal) {
  console.error(
    `npm audit reports ${declaredTotal} vulnerable package(s) in metadata but ` +
      `${parsedTotal} entry/entries were parsed — the report shape changed. ` +
      "Update scripts/audit-gate.mjs.",
  );
  process.exit(1);
}

const today = new Date().toISOString().slice(0, 10);

const blocking = [];
const excused = [];

for (const [name, vuln] of Object.entries(report.vulnerabilities)) {
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
    } else if (exception.fixedIn) {
      if (fixPublished(exception.package, exception.fixedIn)) {
        blocking.push(
          `${name} [${vuln.severity}] ${advisory.title} — THE FIX IS NOW PUBLISHED ` +
            `(${exception.package}@${exception.fixedIn}): upgrade and remove the ` +
            `exception from scripts/audit-gate.mjs`,
        );
      } else {
        excused.push(
          `${ghsa} (${name}) — fix ${exception.package}@${exception.fixedIn} not yet published; ` +
            `the gate re-checks the registry on every run`,
        );
      }
    } else if (!exception.reviewAfter) {
      blocking.push(
        `exception ${ghsa} (${name}) declares neither fixedIn nor reviewAfter — ` +
          `it would be permanent; add one in scripts/audit-gate.mjs`,
      );
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
  Object.values(report.vulnerabilities)
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
