"""M3 exit-criterion demo: requirement -> retrieve -> judge -> verify -> abstain.

Runs the LangGraph pipeline against the live stack (postgres + qdrant + the
indexed "Lumen AI" corpus) with the real Mistral/Groq judge.

    python scripts/assess_demo.py --org "Lumen AI" --requirement A.9.2   # expect VERIFIED
    python scripts/assess_demo.py --org "Lumen AI" --requirement A.4.5   # expect ABSTAINED
    python scripts/assess_demo.py --org "Lumen AI" --all-dev

Needs MISTRAL_API_KEY (or GROQ_API_KEY) in backend/.env. Checkpointing uses
the LangGraph PostgresSaver; export LANGGRAPH_STRICT_MSGPACK=true (set below
if absent) or pass --no-checkpointer.

Requirement selection is restricted to the frozen dev split
(app.pipeline.dev_split) — the 14 test-split requirements are reserved for
the M6 report and are never runnable here.
"""

import argparse
import os
import sys
from contextlib import nullcontext
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "backend"))

# strict checkpoint deserialization (LangGraph advisory) — before any import
os.environ.setdefault("LANGGRAPH_STRICT_MSGPACK", "true")


def dev_requirement_ids() -> list[str]:
    """Dev-split requirement ids, in gold order. NEVER returns test-split ids.
    Delegates to the frozen manifest (runtime code never reads gold labels);
    tests cross-check the frozen list against the gold file."""
    from app.pipeline.dev_split import DEV_REQUIREMENT_IDS

    return list(DEV_REQUIREMENT_IDS)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--org", required=True, help='organization name, e.g. "Lumen AI"')
    group = parser.add_mutually_exclusive_group(required=False)
    group.add_argument("--requirement", help="single KB requirement id, e.g. A.9.2")
    group.add_argument("--all-dev", action="store_true", help="run every dev-split requirement")
    parser.add_argument("--k", type=int, default=6, help="retrieval depth (default 6)")
    parser.add_argument(
        "--no-checkpointer", action="store_true", help="skip the PostgresSaver checkpointer"
    )
    parser.add_argument(
        "--assessment",
        help="resume an existing RUNNING assessment id after a crash: its stored "
        "requirement manifest is authoritative (checkpointed requirements resume, "
        "terminal ones are returned idempotently)",
    )
    args = parser.parse_args()
    if not args.assessment and not (args.requirement or args.all_dev):
        parser.error("--requirement ou --all-dev requis (sauf en reprise --assessment)")

    from sqlalchemy import select

    from app.db import SessionLocal
    from app.models import Assessment, Organization
    from app.pipeline.graph import (
        adopt_manifest,
        build_graph,
        checkpointer_lifespan,
        create_assessment,
        note_assessment_error,
        resume_manifest,
    )
    from app.pipeline.runner import run_assessment
    from app.pipeline.state import AssessmentStatus

    db = SessionLocal()
    org = db.scalars(select(Organization).where(Organization.name == args.org)).first()
    db.close()
    if org is None:
        print(f"organisation introuvable : {args.org}", file=sys.stderr)
        return 2

    selected: list[str] | None = None
    if args.all_dev:
        selected = dev_requirement_ids()
    elif args.requirement:
        selected = [args.requirement]

    lifespan = nullcontext(None) if args.no_checkpointer else checkpointer_lifespan()
    if args.assessment:
        db = SessionLocal()
        existing = db.get(Assessment, args.assessment)
        db.close()
        if existing is None or existing.organization_id != org.id:
            print(f"assessment introuvable pour cette organisation : {args.assessment}", file=sys.stderr)
            return 2
        if existing.status != AssessmentStatus.RUNNING.value:
            print(f"assessment non repris : statut {existing.status} (RUNNING requis)", file=sys.stderr)
            return 2
        assessment_id = existing.id
        try:
            # the stored manifest is authoritative — a different selection
            # would finalize COMPLETED with planned requirements unfinished
            requirement_ids = resume_manifest(SessionLocal, assessment_id, selected)
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 2
        # legacy pre-manifest row: persist the validated selection so the
        # shared runner (which reads the row) can execute it
        adopt_manifest(SessionLocal, assessment_id, requirement_ids)
        if args.k != 6 and args.k != existing.retrieval_k:
            print(
                f"note : --k {args.k} ignoré en reprise — la profondeur du run "
                f"est figée à k={existing.retrieval_k}",
                file=sys.stderr,
            )
        print(f"reprise de l'assessment {assessment_id}")
    else:
        try:
            assessment_id = create_assessment(
                SessionLocal, org.id, requirement_ids=selected, k=args.k
            )
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 2
        requirement_ids = selected
    print(f"assessment {assessment_id} — org « {args.org} » — {len(requirement_ids)} exigence(s)\n")

    # The run loop (operational failures continue, corpus mismatch -> FAILED,
    # full coverage before finalization, resolve_run_status decision) lives in
    # the shared runner — one implementation for the CLI and the M5 API.
    try:
        with lifespan as checkpointer:
            graph = build_graph(SessionLocal, checkpointer=checkpointer)
            run = run_assessment(
                SessionLocal, assessment_id, compiled_graph=graph, on_result=_print_result
            )
    except Exception as exc:
        # keep the assessment RUNNING (resumable) — FAILED would block resume
        note_assessment_error(SessionLocal, assessment_id, str(exc))
        print(
            f"\nassessment {assessment_id} interrompu — reprenez avec "
            f"--assessment {assessment_id}",
            file=sys.stderr,
        )
        raise

    if run.status == AssessmentStatus.RUNNING.value:
        print(
            f"\nassessment {assessment_id} INCOMPLET ({run.total - run.done} exigence(s) "
            f"sans constat) — resté RUNNING ; reprenez avec --assessment {assessment_id}",
            file=sys.stderr,
        )
        return 1
    if run.status == AssessmentStatus.FAILED.value:
        print(f"\nassessment {assessment_id} FAILED : {run.error}", file=sys.stderr)
        return 1
    print(f"\nassessment {assessment_id} finalisé"
          + (f" — {run.error}" if run.error else ""))
    return 1 if run.operational_failures or run.infra_abstains else 0


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
