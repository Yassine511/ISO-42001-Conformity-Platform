"""M6 chat evaluation runner — asks a generated question set headlessly.

Runs every question of a chat_eval question set (scripts/chat_eval_generate.py)
through the grounded chat service against the live stack and writes a run
artifact snapshotting the persisted ChatMessage rows.

    python scripts/eval_chat_run.py --org "Lumen AI" \
        --questions eval/m6/runs/dev1/chat_eval_dev.json --run-id dev1
    python scripts/eval_chat_run.py --org "Lumen AI" \
        --questions eval/m6/runs/holdout/chat_eval_holdout.json --m6-holdout --run-id holdout

Refusals (exit 2): a test-split question set without --m6-holdout; embedded
generator/rubric sha256 drift against the current files; for --m6-holdout,
HEAD not at m6-freeze or a dirty worktree outside eval/m6/runs/<run_id>/.

Failure policy (frozen): service failures that persist NO ChatMessage row
(e.g. Qdrant down) are recorded in the artifact's error ledger; infrastructure
abstentions are recorded as persisted. Exactly ONE recovery re-ask per failed
question; unresolved questions stay in the artifact (mechanical scoring keeps
them in N as infra_failed/missing).
"""

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "backend"))


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _message_dict(m, question: dict) -> dict:
    return {
        "question_id": question["question_id"],
        "requirement_id": question["requirement_id"],
        "question_fr": question["question_fr"],
        "message_id": m.id,
        "conversation_id": m.conversation_id,
        "status": m.status,
        "abstain_reason": m.abstain_reason,
        "evidence_scope": m.evidence_scope,
        "answer": m.answer,
        "claims": m.claims,
        "citations": m.citations,
        "stripped_citations": m.stripped_citations,
        "retrieval_notes": m.retrieval_notes,
        "retrieved_policy": m.retrieved_policy,
        "retrieved_kb": m.retrieved_kb,
        "draft_attempts": m.draft_attempts,
        "prompt_version": m.prompt_version,
        "corpus_version": m.corpus_version,
        "final_model": m.final_model,
        "final_provider": m.final_provider,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--org", required=True)
    parser.add_argument("--questions", required=True, help="generated question-set JSON")
    parser.add_argument("--m6-holdout", action="store_true")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--k-policy", type=int, default=8)
    parser.add_argument("--k-kb", type=int, default=4)
    args = parser.parse_args()

    question_set = json.loads(Path(args.questions).read_text(encoding="utf-8"))
    split = question_set["meta"]["split"]
    if split == "test" and not args.m6_holdout:
        print(
            "REFUS : jeu de questions du split test — réservé au rapport M6 ; "
            "utilisez --m6-holdout au moment du run holdout.",
            file=sys.stderr,
        )
        return 2

    run_dir = REPO_ROOT / "eval" / "m6" / "runs" / args.run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    from sqlalchemy import select

    from app.chat import service
    from app.db import SessionLocal
    from app.eval.gates import (
        GateError,
        check_freeze_gate,
        check_generator_drift,
        contract_hashes,
    )
    from app.models import Organization
    from app.pipeline.state import is_infrastructure_failure

    try:
        check_generator_drift(question_set, REPO_ROOT)
        hashes = contract_hashes(REPO_ROOT)
        freeze_sha = check_freeze_gate(REPO_ROOT, run_dir) if args.m6_holdout else None
    except GateError as exc:
        print(f"REFUS : {exc}", file=sys.stderr)
        return 2

    db = SessionLocal()
    org = db.scalars(select(Organization).where(Organization.name == args.org)).first()
    db.close()
    if org is None:
        print(f"organisation introuvable : {args.org}", file=sys.stderr)
        return 2

    def _ask(question: dict, conversation_id: str | None):
        """One exchange; returns (message_dict|None, ledger_entry|None, conv_id)."""
        db = SessionLocal()
        try:
            m = service.ask(
                db, org.id, question["question_fr"], conversation_id,
                k_policy=args.k_policy, k_kb=args.k_kb,
            )
            return _message_dict(m, question), None, m.conversation_id
        except Exception as exc:  # no-row failure: nothing persisted
            return (
                None,
                {
                    "question_id": question["question_id"],
                    "error": f"{type(exc).__name__}: {exc}",
                    "at": _now_iso(),
                },
                conversation_id,
            )
        finally:
            db.close()

    started_at = _now_iso()
    results: list[dict] = []
    ledger: list[dict] = []
    recovery_log: list[dict] = []
    conversation_id: str | None = None  # one conversation for the whole run

    items = question_set["items"]
    print(f"{len(items)} question(s) ({split}) — run {args.run_id}")
    for i, question in enumerate(items, start=1):
        result, error, conversation_id = _ask(question, conversation_id)
        if error is not None:
            ledger.append({**error, "pass": "first"})
        failed = error is not None or (
            result is not None
            and result["status"] == "ABSTAINED"
            and is_infrastructure_failure(result["abstain_reason"])
        )
        if failed:
            # frozen policy: exactly ONE recovery re-ask
            retry, retry_error, conversation_id = _ask(question, conversation_id)
            recovery_log.append(
                {
                    "question_id": question["question_id"],
                    "first_message_id": result["message_id"] if result else None,
                    "recovered": retry is not None
                    and not is_infrastructure_failure(retry.get("abstain_reason")),
                }
            )
            if retry_error is not None:
                ledger.append({**retry_error, "pass": "recovery"})
            if retry is not None and not is_infrastructure_failure(
                retry.get("abstain_reason")
            ):
                result = retry  # the recovered outcome is the scored one
        if result is not None:
            results.append(result)
        status = result["status"] if result else "AUCUNE LIGNE (ledger)"
        print(f"  [{i}/{len(items)}] {question['question_id']} -> {status}")

    from app.config import settings

    artifact = {
        "meta": {
            "kind": "m6_chat_eval_run",
            "run_id": args.run_id,
            "org": args.org,
            "split": split,
            "k_policy": args.k_policy,
            "k_kb": args.k_kb,
            "judge_429_retries": settings.judge_429_retries,
            "judge_429_base_delay": settings.judge_429_base_delay,
            "question_set_meta": question_set["meta"],
            "question_set_sha256": hashlib.sha256(
                Path(args.questions).read_bytes()
            ).hexdigest(),
            "contract_sha256": hashes,
            "freeze_sha": freeze_sha,
            "conversation_id": conversation_id,
            "started_at": started_at,
            "finished_at": _now_iso(),
        },
        "results": results,
        "error_ledger": ledger,
        "recovery_log": recovery_log,
    }
    out_path = run_dir / f"chat_run_{split}.json"
    out_path.write_text(json.dumps(artifact, ensure_ascii=False, indent=2), encoding="utf-8")

    infra = sum(
        1
        for r in results
        if r["status"] == "ABSTAINED" and is_infrastructure_failure(r["abstain_reason"])
    )
    print(
        f"\nartefact : {out_path}\n"
        f"{len(results)} réponse(s) persistée(s), {len(ledger)} échec(s) sans ligne, "
        f"{infra} abstention(s) infra restante(s)"
    )
    return 0 if not ledger and not infra else 1


if __name__ == "__main__":
    sys.exit(main())
