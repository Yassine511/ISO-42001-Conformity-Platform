"""M7b anchor-primitive contract evaluation.

Runs the deterministic corpus (eval/m7b/anchor_cases.json) against
services.anchors.find_all_exact_anchors + the patch-layer MIN_ANCHOR_LEN gate,
and reports the write-gate decision per case. The primitive is deterministic,
so this is a CONTRACT SUITE, not a metric with sampling error: it must be
100% correct or the write path is unsafe. Exit code is non-zero on any
mismatch (usable as a CI gate).

    backend/.venv/Scripts/python scripts/eval_patch.py

No live model, no services — pure text. (The live drafter's anchor-copy /
abstention behaviour is measured separately with the real judge; this suite
fixes the deterministic floor everything else builds on.)
"""

import json
import sys
import unicodedata
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "backend"))

from app.remediation.patcher import MIN_ANCHOR_LEN  # noqa: E402
from app.services.anchors import find_all_exact_anchors  # noqa: E402

CASES_PATH = REPO_ROOT / "eval" / "m7b" / "anchor_cases.json"


def gate_decision(document: str, anchor: str) -> str:
    """Reproduce the write gate: empty -> error; under MIN_ANCHOR_LEN ->
    reject_too_short; then exactly-one-span -> accept, else the count-based
    rejection."""
    try:
        spans = find_all_exact_anchors(document, anchor)
    except ValueError:
        return "error"
    if len(anchor) < MIN_ANCHOR_LEN:
        return "reject_too_short"
    if len(spans) == 0:
        return "reject_not_found"
    if len(spans) > 1:
        return "reject_ambiguous"
    return "accept"


def main() -> int:
    data = json.loads(CASES_PATH.read_text(encoding="utf-8"))
    base_doc = data["document"]
    rows = []
    failures = 0
    for case in data["cases"]:
        document = case.get("document_override", base_doc)
        if "anchor_nfd_of" in case:
            anchor = unicodedata.normalize("NFD", case["anchor_nfd_of"])
        else:
            anchor = case["anchor"]
        got = gate_decision(document, anchor)
        want = case["expect"]
        ok = got == want
        failures += 0 if ok else 1
        rows.append((case["id"], want, got, ok))

    width = max(len(r[0]) for r in rows)
    print(f"M7b anchor-primitive contract — {CASES_PATH.relative_to(REPO_ROOT)}")
    print(f"(MIN_ANCHOR_LEN = {MIN_ANCHOR_LEN})\n")
    print(f"{'case'.ljust(width)}  {'expected'.ljust(18)}  {'got'.ljust(18)}  ok")
    print("-" * (width + 44))
    for cid, want, got, ok in rows:
        print(f"{cid.ljust(width)}  {want.ljust(18)}  {got.ljust(18)}  {'OK' if ok else 'XX'}")
    total = len(rows)
    print(f"\n{total - failures}/{total} cases correct.")
    if failures:
        print(f"FAILED: {failures} contract violation(s) — the write gate is unsafe.")
        return 1
    print("All contract cases pass.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
