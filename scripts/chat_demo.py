"""M4 exit-criterion demo: question -> retrieve -> cited draft -> verify -> answer/abstain.

Runs the grounded chat service against the live stack (postgres + qdrant + the
indexed "Lumen AI" corpus) with the real Mistral/Groq provider.

    # answerable question — expect ANSWERED with verified, exact citations
    python scripts/chat_demo.py --org "Lumen AI" \
        --question "Comment les risques liés aux fournisseurs d'IA tiers sont-ils gérés ?"

    # adversarial no-evidence question (spec §15) — expect an auditor-voice
    # abstention with a suggested clause, never an invented quote
    python scripts/chat_demo.py --org "Lumen AI" \
        --question "Comment l'empreinte carbone de nos systèmes d'IA est-elle mesurée ?"

Repeat --question to chain several exchanges in one conversation. Needs
MISTRAL_API_KEY (or GROQ_API_KEY) in backend/.env. Exit code 1 when any
exchange ended in an infrastructure abstention (llm_error/rate_limited).
"""

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "backend"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--org", required=True, help='organization name, e.g. "Lumen AI"')
    parser.add_argument(
        "--question", required=True, action="append", help="question (repeatable)"
    )
    parser.add_argument("--k-policy", type=int, default=8, help="policy retrieval depth")
    parser.add_argument("--k-kb", type=int, default=4, help="KB retrieval depth")
    parser.add_argument(
        "--conversation", help="append to an existing conversation id (default: new)"
    )
    args = parser.parse_args()

    from sqlalchemy import select

    from app.chat import service
    from app.db import SessionLocal
    from app.models import Organization
    from app.pipeline.state import is_infrastructure_failure

    db = SessionLocal()
    org = db.scalars(select(Organization).where(Organization.name == args.org)).first()
    db.close()
    if org is None:
        print(f"organisation introuvable : {args.org}", file=sys.stderr)
        return 2

    conversation_id = args.conversation
    infra_abstains = 0
    for question in args.question:
        db = SessionLocal()
        try:
            message = service.ask(
                db,
                org.id,
                question,
                conversation_id,
                k_policy=args.k_policy,
                k_kb=args.k_kb,
            )
            conversation_id = message.conversation_id
            if is_infrastructure_failure(message.abstain_reason):
                infra_abstains += 1
            _print_message(message)  # inside the session: llm_calls is lazy
        except service.ConversationNotFoundError:
            print(f"conversation introuvable : {conversation_id}", file=sys.stderr)
            return 2
        finally:
            db.close()

    print(f"conversation {conversation_id}")
    return 1 if infra_abstains else 0


def _print_message(m) -> None:
    print(f"=== {m.question} " + "=" * 30)
    print("-- extraits politiques récupérés :")
    for item in m.retrieved_policy:
        loc = f"{item.get('filename')} p.{item.get('page_number')} [{item.get('char_start')}:{item.get('char_end')}]"
        print(f"   rrf={item['rrf_score']:.4f}  {loc}")
    print("-- exigences KB récupérées :")
    for item in m.retrieved_kb:
        print(f"   rrf={item['rrf_score']:.4f}  {item['requirement_id']}")
    for attempt in m.attempts:
        print(f"-- tentative {attempt['attempt_number']} (parsed_ok={attempt['parsed_ok']})")
        for e in attempt.get("validation_errors", []):
            print(f"   ✗ {e}")
    for call in m.llm_calls:
        print(
            f"   appel {call.provider}/{call.requested_model} -> {call.status}"
            + (f" ({call.http_status})" if call.http_status else "")
        )

    if m.status == "ANSWERED":
        print(f">>> ANSWERED (evidence_scope={m.evidence_scope})")
        print(f"    {m.answer}\n")
        for c in m.citations:
            if c["type"] == "policy":
                print(
                    f'    [{c["id"]}] « {c["quote"]} »\n'
                    f'         — {c["filename"]} p.{c["page_number"]} '
                    f'[{c["match_start"]}:{c["match_end"]}] '
                    f'({c["match_method"]}, {c["match_score"]:.1f})'
                )
            else:
                print(f'    [{c["id"]}] clause {c["requirement_id"]} — {c["requirement_fr"]}')
    else:
        print(f">>> ABSTAINED ({m.abstain_reason})")
        print(f"    {m.answer}")
        if m.retrieval_notes:
            print("    passages examinés (commentaire modèle, non vérifié) :")
            for note in m.retrieval_notes:
                print(f"      - {note['result_id'][:12]}… : {note['reason']}")
    if m.stripped_citations:
        print("    citations retirées :")
        for s in m.stripped_citations:
            print(f"      ✗ {s['error']}")
    print(f"    message {m.id} — tentatives : {m.draft_attempts}\n")


if __name__ == "__main__":
    sys.exit(main())
