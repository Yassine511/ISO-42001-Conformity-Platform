"""Grading sheets for the M6 chat holdout (rubric §1/§4) — build and ingest.

Masking (rubric §4) is STRUCTURAL: the sheet contains only what the grader is
allowed to see — claim text and the rendered cited text (`source_quote` raw
slice for policy citations, hydrated `requirement_fr` for KB citations) —
plus empty label/comment fields. Everything else (status, abstain_reason,
evidence_scope, citations_verified, match method/score, file metadata, raw
model output) is absent from the file by construction.

Ingest is tamper-proof: the canonical empty sheet is REGENERATED from the
immutable run artifact and every field except `label`/`comment` must be
exactly equal — a modified claim_text/cited_text/question/answer_text is a
hard error, not a warning.
"""

import hashlib
import json
from pathlib import Path

PAIR_LABELS = ("SUPPORTS", "PARTIAL", "IRRELEVANT")
ANSWER_LABELS = ("FAITHFUL", "PARTIALLY_FAITHFUL", "UNFAITHFUL")

# rubric §4 masked fields — must never appear in a sheet row
FORBIDDEN_KEYS = frozenset(
    {
        "status", "abstain_reason", "evidence_scope", "citations_verified",
        "match_method", "match_score", "match_start", "match_end",
        "filename", "page_number", "document_id", "chunk_id", "quote",
        "rationale", "raw_draft", "retrieval_notes",
    }
)


class SheetError(ValueError):
    """Validation failure on a grading sheet (French message)."""


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def sha256_payload(payload) -> str:
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _cited_text(citation: dict) -> str:
    if citation["type"] == "policy":
        source_quote = citation.get("source_quote")
        if not source_quote:
            # fail closed: a policy citation without its server-derived slice
            # cannot be graded — surfacing it would show model text as source
            raise SheetError(
                f"citation {citation.get('id')} sans source_quote : "
                "tranche source indisponible, notation impossible."
            )
        return source_quote
    return citation.get("requirement_fr") or ""


def build_pair_sheet(run_results: list[dict]) -> list[dict]:
    """One row per (surviving claim, referenced citation), deterministic order
    (question order, claim order, citation order)."""
    rows: list[dict] = []
    for result in run_results:
        if result.get("status") != "ANSWERED":
            continue  # abstentions have no pairs (rubric §5)
        citations_by_id = {c["id"]: c for c in result.get("citations") or []}
        for claim_index, claim in enumerate(result.get("claims") or []):
            if not claim.get("citations_verified"):
                continue  # only surviving claims are graded
            for cid in claim["citation_ids"]:
                citation = citations_by_id.get(cid)
                if citation is None:
                    raise SheetError(
                        f"citation {cid} référencée mais absente des citations "
                        f"vérifiées ({result['question_id']})."
                    )
                rows.append(
                    {
                        "pair_id": f"{result['question_id']}#c{claim_index}#{cid}",
                        "question_id": result["question_id"],
                        "claim_index": claim_index,
                        "claim_text": claim["text"],
                        "citation_type": citation["type"],
                        "cited_text": _cited_text(citation),
                        "label": None,
                        "comment": None,
                    }
                )
    _assert_masked(rows)
    return rows


def build_answer_sheet(run_results: list[dict]) -> list[dict]:
    """One row per ANSWERED question: answer-level faithfulness (rubric §1)."""
    rows = [
        {
            "answer_id": f"{r['question_id']}#answer",
            "question_id": r["question_id"],
            "question_fr": r["question_fr"],
            "answer_text": r["answer"],
            "label": None,
            "comment": None,
        }
        for r in run_results
        if r.get("status") == "ANSWERED"
    ]
    _assert_masked(rows)
    return rows


def _assert_masked(rows: list[dict]) -> None:
    for row in rows:
        leaked = FORBIDDEN_KEYS.intersection(row)
        if leaked:
            raise SheetError(f"champ masqué présent dans la feuille : {sorted(leaked)}")


def ingest(
    filled_pairs: list[dict],
    filled_answers: list[dict],
    run_results: list[dict],
) -> tuple[list[dict], list[dict]]:
    """Validate filled sheets against sheets regenerated from the immutable
    run artifact. Only `label` and `comment` may differ from the canonical
    empty sheet; labels must be complete and in the frozen enums."""
    expected_pairs = build_pair_sheet(run_results)
    expected_answers = build_answer_sheet(run_results)
    _check_against_expected(filled_pairs, expected_pairs, "pair_id", PAIR_LABELS)
    _check_against_expected(filled_answers, expected_answers, "answer_id", ANSWER_LABELS)
    return filled_pairs, filled_answers


def _check_against_expected(
    filled: list[dict], expected: list[dict], id_key: str, labels: tuple[str, ...]
) -> None:
    expected_by_id = {row[id_key]: row for row in expected}
    seen: set[str] = set()
    for row in filled:
        row_id = row.get(id_key)
        if row_id not in expected_by_id:
            raise SheetError(f"ligne inattendue : {id_key}={row_id!r}")
        if row_id in seen:
            raise SheetError(f"ligne dupliquée : {id_key}={row_id!r}")
        seen.add(row_id)
        canonical = expected_by_id[row_id]
        for key, value in canonical.items():
            if key in ("label", "comment"):
                continue
            if row.get(key) != value:
                raise SheetError(
                    f"champ immuable modifié ({id_key}={row_id!r}, champ {key!r}) : "
                    "la feuille ne correspond plus à l'artefact de run."
                )
        extra = set(row) - set(canonical)
        if extra:
            raise SheetError(f"champs inconnus ({id_key}={row_id!r}) : {sorted(extra)}")
        if row.get("label") not in labels:
            raise SheetError(
                f"label invalide ou manquant ({id_key}={row_id!r}) : "
                f"{row.get('label')!r} — attendu parmi {list(labels)}."
            )
    missing = set(expected_by_id) - seen
    if missing:
        raise SheetError(f"lignes manquantes : {sorted(missing)}")
