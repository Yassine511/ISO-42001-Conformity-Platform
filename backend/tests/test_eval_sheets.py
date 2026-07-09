"""Grading sheets (M6 harness): §4 masking is structural, ingest is
tamper-proof — immutable fields must equal the sheet regenerated from the run
artifact; only label/comment may differ.
"""

import copy

import pytest

from app.eval.sheets import (
    FORBIDDEN_KEYS,
    SheetError,
    build_answer_sheet,
    build_pair_sheet,
    ingest,
)


def _run_results():
    return [
        {
            "question_id": "chat_eval:test:A.9.2",
            "question_fr": "Comment notre organisation couvre-t-elle … ?",
            "status": "ANSWERED",
            "abstain_reason": None,
            "evidence_scope": "mixed",
            "answer": "Claim un.\n\nClaim deux.",
            "claims": [
                {
                    "text": "Claim un.",
                    "kind": "organization",
                    "citation_ids": ["c1", "c2"],
                    "citations_verified": True,
                    "failed_citation_ids": [],
                },
                {
                    "text": "Claim stripped.",
                    "kind": "organization",
                    "citation_ids": ["c9"],
                    "citations_verified": False,
                    "failed_citation_ids": ["c9"],
                },
            ],
            "citations": [
                {
                    "id": "c1",
                    "type": "policy",
                    "quote": "citation modèle",
                    "source_quote": "tranche source authentique rendue",
                    "chunk_id": "chunk-1",
                    "filename": "doc.md",
                    "page_number": 1,
                    "match_method": "exact",
                    "match_score": 100.0,
                },
                {
                    "id": "c2",
                    "type": "kb",
                    "requirement_id": "A.9.2",
                    "requirement_fr": "Paraphrase de l'exigence.",
                    "domain": "A.9",
                },
            ],
        },
        {
            "question_id": "chat_eval:test:7.1",
            "question_fr": "Question sans réponse attendue ?",
            "status": "ABSTAINED",
            "abstain_reason": "verification_failed",
            "evidence_scope": None,
            "answer": "Aucune preuve vérifiable…",
            "claims": [],
            "citations": [],
        },
    ]


def test_pair_sheet_enumerates_surviving_claims_only():
    rows = build_pair_sheet(_run_results())
    # one surviving claim with two citations; the stripped claim is excluded,
    # the abstained question has no pairs
    assert [r["pair_id"] for r in rows] == [
        "chat_eval:test:A.9.2#c0#c1",
        "chat_eval:test:A.9.2#c0#c2",
    ]
    assert rows[0]["cited_text"] == "tranche source authentique rendue"
    assert rows[1]["cited_text"] == "Paraphrase de l'exigence."


def test_pair_sheet_masks_forbidden_fields():
    for row in build_pair_sheet(_run_results()):
        assert not FORBIDDEN_KEYS.intersection(row)


def test_pair_sheet_fails_closed_without_source_quote():
    results = _run_results()
    results[0]["citations"][0]["source_quote"] = None
    with pytest.raises(SheetError, match="source_quote"):
        build_pair_sheet(results)


def test_answer_sheet_covers_exactly_answered_messages():
    rows = build_answer_sheet(_run_results())
    assert len(rows) == 1
    assert rows[0]["answer_id"] == "chat_eval:test:A.9.2#answer"
    assert not FORBIDDEN_KEYS.intersection(rows[0])


def _filled():
    results = _run_results()
    pairs = build_pair_sheet(results)
    answers = build_answer_sheet(results)
    for p in pairs:
        p["label"] = "SUPPORTS"
    for a in answers:
        a["label"] = "FAITHFUL"
    return pairs, answers, results


def test_ingest_round_trip():
    pairs, answers, results = _filled()
    ingest(pairs, answers, results)  # no exception


def test_ingest_rejects_missing_row():
    pairs, answers, results = _filled()
    with pytest.raises(SheetError, match="manquantes"):
        ingest(pairs[:1], answers, results)


def test_ingest_rejects_extra_row():
    pairs, answers, results = _filled()
    extra = copy.deepcopy(pairs[0])
    extra["pair_id"] = "chat_eval:test:A.9.2#c0#c99"
    with pytest.raises(SheetError, match="inattendue"):
        ingest(pairs + [extra], answers, results)


def test_ingest_rejects_bad_label():
    pairs, answers, results = _filled()
    pairs[0]["label"] = "SUPPORTED"  # not in the frozen enum
    with pytest.raises(SheetError, match="label invalide"):
        ingest(pairs, answers, results)


def test_ingest_rejects_missing_label():
    pairs, answers, results = _filled()
    pairs[0]["label"] = None
    with pytest.raises(SheetError, match="label invalide"):
        ingest(pairs, answers, results)


def test_ingest_rejects_tampered_claim_text():
    pairs, answers, results = _filled()
    pairs[0]["claim_text"] = "Claim un modifié."
    with pytest.raises(SheetError, match="immuable"):
        ingest(pairs, answers, results)


def test_ingest_rejects_tampered_cited_text():
    pairs, answers, results = _filled()
    pairs[1]["cited_text"] = "Paraphrase falsifiée."
    with pytest.raises(SheetError, match="immuable"):
        ingest(pairs, answers, results)


def test_ingest_rejects_tampered_answer_text():
    pairs, answers, results = _filled()
    answers[0]["answer_text"] = "Réponse réécrite."
    with pytest.raises(SheetError, match="immuable"):
        ingest(pairs, answers, results)


def test_ingest_rejects_unknown_extra_field():
    pairs, answers, results = _filled()
    pairs[0]["evidence_scope"] = "mixed"  # masked field smuggled back in
    with pytest.raises(SheetError, match="inconnus"):
        ingest(pairs, answers, results)
