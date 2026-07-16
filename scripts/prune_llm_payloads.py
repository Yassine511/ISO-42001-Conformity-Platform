"""Retention pruning of persisted LLM request prompts (explicit, opt-in).

Every provider call persists its full prompt body (`request_messages`) as
provenance; that column duplicates policy-page text stored durably elsewhere
and grows without bound. This script — and nothing else — replaces prompt
bodies older than a retention window with an explicit marker. Call metadata,
raw_response (the model's output) and every attempt/finding row are always
kept: the trust chain is untouched. Policy details:
backend/app/services/llm_retention.py.

    python scripts/prune_llm_payloads.py --older-than-days 90            # dry-run
    python scripts/prune_llm_payloads.py --older-than-days 90 --apply    # prune

Dry-run is the default and writes nothing.
"""

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "backend"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--older-than-days",
        type=int,
        required=True,
        help="prune request prompts of calls started more than N days ago (N >= 1)",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="actually write the markers (default: dry-run, nothing written)",
    )
    args = parser.parse_args()

    from app.db import SessionLocal
    from app.services.llm_retention import prune_request_messages

    db = SessionLocal()
    try:
        report = prune_request_messages(
            db, older_than_days=args.older_than_days, apply=args.apply
        )
    finally:
        db.close()

    mode = "APPLIQUÉ" if report["apply"] else "SIMULATION (--apply pour exécuter)"
    print(f"Rétention des invites LLM — {mode}")
    print(f"  politique : {report['policy']}")
    print(f"  seuil     : appels antérieurs au {report['cutoff']}")
    for table, counts in report["tables"].items():
        print(
            f"  {table}: {counts['candidates']} candidat(s), "
            f"{counts['pruned']} élagué(s)"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
