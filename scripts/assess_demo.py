"""M3 exit-criterion demo: requirement -> retrieve -> judge -> verify -> abstain.

Runs the LangGraph pipeline against the live stack (postgres + qdrant + the
indexed "Lumen AI" corpus) with the real Mistral/Groq judge.

    python scripts/assess_demo.py --org "Lumen AI" --requirement A.9.2   # expect VERIFIED
    python scripts/assess_demo.py --org "Lumen AI" --requirement A.4.5   # expect ABSTAINED
    python scripts/assess_demo.py --org "Lumen AI" --all-dev

Needs MISTRAL_API_KEY (or GROQ_API_KEY) in backend/.env. Checkpointing uses
the LangGraph PostgresSaver; export LANGGRAPH_STRICT_MSGPACK=true (set below
if absent) or pass --no-checkpointer.

Gold labels are read ONLY to select dev-split requirement ids for --all-dev —
the test split is reserved for the M6 report and is never touched here.
"""

import argparse
import json
import os
import sys
from contextlib import nullcontext
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "backend"))

# strict checkpoint deserialization (LangGraph advisory) — before any import
os.environ.setdefault("LANGGRAPH_STRICT_MSGPACK", "true")


def dev_requirement_ids() -> list[str]:
    """Dev-split requirement ids, in gold order. NEVER returns test-split ids."""
    gold = json.loads(
        (REPO_ROOT / "corpus" / "gold" / "gold_labels.json").read_text(encoding="utf-8")
    )
    return [item["requirement_id"] for item in gold["items"] if item["split"] == "dev"]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--org", required=True, help='organization name, e.g. "Lumen AI"')
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--requirement", help="single KB requirement id, e.g. A.9.2")
    group.add_argument("--all-dev", action="store_true", help="run every dev-split requirement")
    parser.add_argument("--k", type=int, default=6, help="retrieval depth (default 6)")
    parser.add_argument(
        "--no-checkpointer", action="store_true", help="skip the PostgresSaver checkpointer"
    )
    args = parser.parse_args()

    from sqlalchemy import select

    from app.db import SessionLocal
    from app.models import Organization
    from app.pipeline.graph import (
        build_graph,
        checkpointer_lifespan,
        create_assessment,
        finalize_assessment,
        run_requirement,
    )
    from app.pipeline.state import AssessmentStatus

    db = SessionLocal()
    org = db.scalars(select(Organization).where(Organization.name == args.org)).first()
    db.close()
    if org is None:
        print(f"organisation introuvable : {args.org}", file=sys.stderr)
        return 2

    requirement_ids = dev_requirement_ids() if args.all_dev else [args.requirement]

    lifespan = nullcontext(None) if args.no_checkpointer else checkpointer_lifespan()
    assessment_id = create_assessment(SessionLocal, org.id)
    print(f"assessment {assessment_id} — org « {args.org} » — {len(requirement_ids)} exigence(s)\n")

    failures = 0
    try:
        with lifespan as checkpointer:
            graph = build_graph(SessionLocal, checkpointer=checkpointer)
            for req_id in requirement_ids:
                try:
                    result = run_requirement(
                        SessionLocal, assessment_id, req_id, k=args.k, compiled_graph=graph
                    )
                except Exception as exc:  # operational failure, not a finding
                    failures += 1
                    print(f"[{req_id}] ERREUR OPÉRATIONNELLE : {exc}", file=sys.stderr)
                    continue
                _print_result(result)
    except Exception as exc:
        finalize_assessment(
            SessionLocal, assessment_id, AssessmentStatus.FAILED, error=str(exc)
        )
        raise
    finalize_assessment(
        SessionLocal,
        assessment_id,
        AssessmentStatus.FAILED if failures == len(requirement_ids) else AssessmentStatus.COMPLETED,
        error=f"{failures} exigence(s) en erreur opérationnelle" if failures else None,
    )
    print(f"\nassessment {assessment_id} finalisé ({failures} erreur(s) opérationnelle(s))")
    return 1 if failures else 0


def _print_result(result) -> None:
    print(f"=== {result.requirement_id} " + "=" * 50)
    print("-- extraits récupérés :")
    for item in result.retrieved:
        loc = f"{item.get('filename')} p.{item.get('page_number')} [{item.get('char_start')}:{item.get('char_end')}]"
        print(f"   rrf={item['rrf_score']:.4f}  {loc}")
    for attempt in result.attempt_history:
        print(f"-- tentative {attempt.get('attempt')} (parsed_ok={attempt.get('parsed_ok')})")
        for call in attempt.get("calls", []):
            print(
                f"   appel {call['provider']}/{call['requested_model']} -> {call['status']}"
                + (f" ({call['http_status']})" if call.get("http_status") else "")
            )
        raw = attempt.get("raw_response")
        if raw:
            print(f"   brut : {raw[:300]}")
        errors = attempt.get("verifier_errors")
        if errors:
            for e in errors:
                print(f"   verif ✗ {e}")
    for event in result.audit_log:
        print(f"-- audit : {event['node']}/{event['event']}")
    if result.status == "VERIFIED":
        print(f">>> VERIFIED ({result.verdict}, confiance {result.confidence})")
        print(f'    citation : « {result.policy_quote} »')
        if result.match:
            print(
                f"    source : chunk {result.match.chunk_id[:12]}… "
                f"[{result.match.match_start}:{result.match.match_end}] "
                f"({result.match.method}, score {result.match.score:.1f})"
            )
    else:
        print(f">>> ABSTAINED ({result.abstain_reason})")
        if result.rationale:
            print(f"    rationale : {result.rationale}")
    print(f"    finding {result.finding_id} — tentatives : {result.attempts}\n")


if __name__ == "__main__":
    sys.exit(main())
