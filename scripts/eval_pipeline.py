"""M6 pipeline evaluation runner — dev diagnostics or the one-shot holdout.

Runs the assessment pipeline over one gold split against the live stack
(postgres + qdrant + indexed "Lumen AI" corpus + Mistral/Groq), then scores
it under the FROZEN rules (eval/m6/regles_notation_pipeline.md) and writes a
self-contained artifact JSON.

    python scripts/eval_pipeline.py --org "Lumen AI" --split dev  --run-id dev1
    python scripts/eval_pipeline.py --org "Lumen AI" --split test --m6-holdout --run-id holdout  # M6 only

Refusals (exit 2): test split without --m6-holdout; for --m6-holdout, HEAD
not at the m6-freeze tag or a dirty worktree outside eval/m6/runs/<run_id>/.

Recovery policy (frozen): the first pass is sealed in full; then exactly ONE
recovery pass — resume if the assessment stayed RUNNING, plus one new
lineage-linked recovery assessment over the requirement ids whose only
outcome is a terminal infrastructure abstention. Items still failed remain in
the artifact as infra_failed; quality metrics use n_scored = N - infra_failed.
"""

import argparse
import json
import os
import sys
from contextlib import nullcontext
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "backend"))

os.environ.setdefault("LANGGRAPH_STRICT_MSGPACK", "true")


def _finding_dict(row) -> dict:
    return {
        "requirement_id": row.requirement_id,
        "status": row.status,
        "verdict": row.verdict,
        "abstain_reason": row.abstain_reason,
        "policy_quote": row.policy_quote,
        "clause_ref": row.clause_ref,
        "confidence": row.confidence,
        "match_method": row.match_method,
        "attempts": row.attempts,
        "final_model": row.final_model,
        "final_provider": row.final_provider,
        "finding_id": row.id,
    }


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _run_pass(SessionLocal, assessment_id: str, lifespan_factory) -> dict:
    """Execute one runner pass; returns {status, error, done, total}."""
    from app.pipeline.graph import build_graph, note_assessment_error
    from app.pipeline.runner import run_assessment

    try:
        with lifespan_factory() as checkpointer:
            graph = build_graph(SessionLocal, checkpointer=checkpointer)
            run = run_assessment(SessionLocal, assessment_id, compiled_graph=graph)
    except Exception as exc:  # keep resumable, seal the error
        note_assessment_error(SessionLocal, assessment_id, str(exc))
        return {"status": "RUNNING", "error": str(exc), "done": None, "total": None}
    return {"status": run.status, "error": run.error, "done": run.done, "total": run.total}


def _collect(SessionLocal, assessment_ids: list[str]) -> dict[str, dict]:
    """requirement_id -> finding dict, later assessments (recovery) winning."""
    from sqlalchemy import select

    from app.models import Finding

    db = SessionLocal()
    try:
        findings: dict[str, dict] = {}
        for aid in assessment_ids:
            rows = db.scalars(select(Finding).where(Finding.assessment_id == aid)).all()
            for row in rows:
                findings[row.requirement_id] = {**_finding_dict(row), "assessment_id": aid}
        return findings
    finally:
        db.close()


def _attempt1_outcomes(SessionLocal, findings: dict[str, dict]) -> list:
    """Attempt-1 classification per requirement, from ITS OWN assessment."""
    from sqlalchemy import select

    from app.eval.posthoc import classify_attempt1, recover_attempt1_content
    from app.models import Finding

    db = SessionLocal()
    try:
        outcomes = []
        for rid, f in findings.items():
            row = db.get(Finding, f["finding_id"])
            content, provider, model = recover_attempt1_content(
                db, f["assessment_id"], rid
            )
            outcomes.append(
                classify_attempt1(
                    rid, content, row.retrieved or [], provider=provider, model=model
                )
            )
        return outcomes
    finally:
        db.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--org", required=True)
    parser.add_argument("--split", required=True, choices=["dev", "test"])
    parser.add_argument("--m6-holdout", action="store_true",
                        help="required for --split test — M6 report run only")
    parser.add_argument("--k", type=int, default=6)
    parser.add_argument("--run-id", required=True,
                        help="artifact directory name under eval/m6/runs/")
    parser.add_argument("--no-checkpointer", action="store_true")
    args = parser.parse_args()

    if args.split == "test" and not args.m6_holdout:
        print(
            "REFUS : le split test est réservé au rapport M6 ; utilisez --m6-holdout "
            "au moment du run holdout (état gelé requis).",
            file=sys.stderr,
        )
        return 2

    run_dir = REPO_ROOT / "eval" / "m6" / "runs" / args.run_id
    out_path = run_dir / f"pipeline_{args.split}.json"
    if out_path.exists():
        print(
            f"REFUS : l'artefact {out_path} existe déjà — un run est unique ; "
            "choisissez un autre --run-id.",
            file=sys.stderr,
        )
        return 2
    run_dir.mkdir(parents=True, exist_ok=True)

    from sqlalchemy import select

    from app.db import SessionLocal
    from app.eval.gates import (
        GateError,
        check_document_baseline,
        check_freeze_gate,
        contract_hashes,
    )
    from app.eval.pipeline_scoring import load_gold, score_findings, system_label
    from app.eval.posthoc import gate_diagnostic, reverify_final
    from app.models import Finding, FindingReview, Organization
    from app.pipeline.graph import checkpointer_lifespan, create_assessment
    from app.pipeline.state import AssessmentStatus

    try:
        hashes = contract_hashes(REPO_ROOT)
        freeze_sha = None
        if args.m6_holdout:
            freeze_sha = check_freeze_gate(REPO_ROOT, run_dir)
    except GateError as exc:
        print(f"REFUS : {exc}", file=sys.stderr)
        return 2

    corpus_version, gold = load_gold(args.split)
    from app.services.retrieval import load_kb

    kb = load_kb()
    if kb["corpus_version"] != corpus_version:
        print(
            f"REFUS : corpus_version incohérente (gold {corpus_version} != KB "
            f"{kb['corpus_version']}).",
            file=sys.stderr,
        )
        return 2

    from app.models import Document

    db = SessionLocal()
    org = db.scalars(select(Organization).where(Organization.name == args.org)).first()
    org_docs = (
        [
            (d.filename, d.checksum)
            for d in db.scalars(
                select(Document).where(Document.organization_id == org.id)
            ).all()
        ]
        if org
        else []
    )
    db.close()
    if org is None:
        print(f"organisation introuvable : {args.org}", file=sys.stderr)
        return 2
    try:
        # strict six-document corpus baseline, enforced at run time (the
        # assessment's frozen document_manifest captures the same fact)
        check_document_baseline(org_docs, REPO_ROOT)
    except GateError as exc:
        print(f"REFUS : {exc}", file=sys.stderr)
        return 2

    requirement_ids = list(gold.keys())
    lifespan_factory = (
        (lambda: nullcontext(None)) if args.no_checkpointer else checkpointer_lifespan
    )

    from app.config import settings

    meta = {
        "kind": "m6_pipeline_eval",
        "split": args.split,
        "org": args.org,
        "k": args.k,
        "judge_429_retries": settings.judge_429_retries,
        "judge_429_base_delay": settings.judge_429_base_delay,
        "corpus_version": corpus_version,
        "contract_sha256": hashes,
        "freeze_sha": freeze_sha,
        "started_at": _now_iso(),
        "n_total": len(requirement_ids),
    }

    # ---------------- first pass (sealed in full, whatever happens) ----------
    print(f"première passe : {len(requirement_ids)} exigence(s) ({args.split})")
    assessment_id = create_assessment(
        SessionLocal, org.id, requirement_ids=requirement_ids, k=args.k,
        allow_holdout=(args.split == "test"),
    )
    first = _run_pass(SessionLocal, assessment_id, lifespan_factory)
    first_findings = _collect(SessionLocal, [assessment_id])
    first_pass = {
        "assessment_id": assessment_id,
        "runner": first,
        "findings": {rid: f for rid, f in first_findings.items()},
    }
    print(f"  première passe : {first['status']} ({len(first_findings)}/{len(requirement_ids)} constats)")

    # ---------------- ONE recovery pass (frozen policy) ----------------------
    recovery: dict = {"resumed": False, "recovery_assessment_id": None, "runner": None}
    if first["status"] == AssessmentStatus.RUNNING.value:
        print("  reprise (une seule) de l'assessment RUNNING…")
        recovery["resumed"] = True
        recovery["runner"] = _run_pass(SessionLocal, assessment_id, lifespan_factory)

    findings = _collect(SessionLocal, [assessment_id])
    infra_ids = [
        rid for rid, f in findings.items() if system_label(f) == "infra_failed"
    ]
    if infra_ids:
        print(f"  reprise infra : nouvel assessment de recouvrement sur {infra_ids}")
        recovery_id = create_assessment(
            SessionLocal, org.id, requirement_ids=infra_ids, k=args.k,
            allow_holdout=(args.split == "test"),
        )
        recovery["recovery_assessment_id"] = recovery_id
        recovery["parent_assessment_id"] = assessment_id
        recovery["runner"] = _run_pass(SessionLocal, recovery_id, lifespan_factory)
        findings = _collect(SessionLocal, [assessment_id, recovery_id])

    assessment_ids = [assessment_id] + (
        [recovery["recovery_assessment_id"]] if recovery["recovery_assessment_id"] else []
    )

    # ---------------- scoring under the frozen rules -------------------------
    scores = score_findings(findings, gold)
    outcomes = _attempt1_outcomes(SessionLocal, findings)
    diagnostic = gate_diagnostic(outcomes, findings)

    # invariant check: every final VERIFIED quote still locates exactly
    db = SessionLocal()
    try:
        invariant_failures = []
        for rid, f in findings.items():
            if f["status"] == "VERIFIED":
                row = db.get(Finding, f["finding_id"])
                if not reverify_final(row):
                    invariant_failures.append(rid)
    finally:
        db.close()
    if invariant_failures:
        print(
            f"ERREUR BLOQUANTE : invariant du vérificateur violé sur {invariant_failures} "
            "— bug du vérificateur, rapport impossible.",
            file=sys.stderr,
        )

    # operational indicator: overrides scoped STRICTLY to this run's assessments
    db = SessionLocal()
    try:
        finding_ids = [f["finding_id"] for f in findings.values()]
        reviews = (
            db.scalars(select(FindingReview).where(FindingReview.finding_id.in_(finding_ids))).all()
            if finding_ids
            else []
        )
        override_log = [
            {"finding_id": r.finding_id, "action": r.action, "created_at": r.created_at.isoformat()}
            for r in reviews
        ]
    finally:
        db.close()

    artifact = {
        "meta": {**meta, "finished_at": _now_iso(), "assessment_ids": assessment_ids},
        "first_pass": first_pass,
        "recovery": recovery,
        "findings": findings,
        "attempt1_outcomes": [o.to_dict() for o in outcomes],
        "scores": scores.to_dict(),
        "gate_diagnostic": diagnostic,
        "verified_invariant_failures": invariant_failures,
        "review_overrides_scoped": override_log,
    }
    out_path.write_text(
        json.dumps(artifact, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    acc = scores.accuracy
    print(
        f"\nartefact : {out_path}\n"
        f"N={scores.n_total}  n_scored={scores.n_scored}  "
        f"infra_failed={len(scores.infra_failed_ids)}  sans_constat={len(scores.missing_ids)}\n"
        + (
            f"exactitude verdict : {acc.count}/{acc.n} = {acc.ratio:.2%} "
            f"[{acc.ci_low:.2%}, {acc.ci_high:.2%}]"
            if acc
            else "exactitude : n_scored = 0"
        )
    )
    if invariant_failures:
        return 1
    return 0 if not scores.infra_failed_ids and not scores.missing_ids else 1


if __name__ == "__main__":
    sys.exit(main())
