"""Chat mechanical metrics and rubric §2 aggregation (M6 harness)."""

import pytest

from app.eval.chat_scoring import aggregate_rubric, location_validity, mechanical_metrics
from app.eval.sheets import build_answer_sheet, build_pair_sheet

SOURCE = "Les collaborateurs doivent signaler tout incident dans un délai de 48 heures."


def _question_set():
    return {
        "meta": {"split": "dev", "question_count": 4, "unanswerable_count": 2},
        "items": [
            {"question_id": "q1", "answerable": True},
            {"question_id": "q2", "answerable": False},
            {"question_id": "q3", "answerable": False},
            {"question_id": "q4", "answerable": True},
        ],
    }


def _answered(qid: str, scope="policy") -> dict:
    return {
        "question_id": qid,
        "question_fr": "Q ?",
        "status": "ANSWERED",
        "abstain_reason": None,
        "evidence_scope": scope,
        "answer": "Claim.",
        "draft_attempts": 1,
        "claims": [
            {
                "text": "Claim.",
                "kind": "organization",
                "citation_ids": ["c1"],
                "citations_verified": True,
                "failed_citation_ids": [],
            }
        ],
        "citations": [
            {
                "id": "c1",
                "type": "policy",
                "quote": SOURCE,
                "source_quote": SOURCE,
            }
        ],
        "stripped_citations": [],
        "retrieved_policy": [
            {"result_id": "chunk-1", "source_type": "policy", "text": SOURCE, "char_start": 0}
        ],
        "retrieved_kb": [{"requirement_id": "A.9.2"}],
    }


def _abstained(qid: str, reason="verification_failed") -> dict:
    return {
        "question_id": qid,
        "question_fr": "Q ?",
        "status": "ABSTAINED",
        "abstain_reason": reason,
        "evidence_scope": None,
        "answer": "Aucune preuve vérifiable…",
        "draft_attempts": 2,
        "claims": [],
        "citations": [],
        "stripped_citations": [],
        "retrieved_policy": [],
        "retrieved_kb": [],
    }


def test_location_validity_uses_persisted_snapshot():
    result = _answered("q1")
    assert location_validity(result) == (1, 1)
    # a citation outside the snapshot does not locate
    result["citations"].append(
        {"id": "c2", "type": "kb", "requirement_id": "7.1"}
    )
    assert location_validity(result) == (1, 2)


def test_mechanical_metrics_full_run():
    results = [
        _answered("q1"),
        _abstained("q2"),                      # correct abstention (unanswerable)
        _abstained("q3", reason="llm_error"),  # infra -> categorized, not scored
        # q4 missing entirely (error ledger case)
    ]
    m = mechanical_metrics(results, _question_set())
    assert m["n_total"] == 4
    assert m["infra_failed_ids"] == ["q3"]
    assert m["missing_ids"] == ["q4"]
    assert m["n_scored"] == 2
    assert m["answered"] == 1
    assert m["abstentions"] == 1
    assert m["abstention_precision"]["count"] == 1
    assert m["abstention_precision"]["n"] == 1
    # q3 is unanswerable but infra-failed: recall denominator counts only q2
    assert m["abstention_recall"]["count"] == 1
    assert m["abstention_recall"]["n"] == 1
    assert m["citation_location_validity"]["count"] == 1
    assert m["citation_location_validity"]["n"] == 1
    assert m["evidence_scopes"] == {"policy": 1}
    assert m["abstain_reasons"] == {"verification_failed": 1, "llm_error": 1}


def _graded_results():
    r1 = _answered("q1")
    r1["claims"][0]["citation_ids"] = ["c1"]
    r2 = _answered("q4", scope="kb_only")
    r2["citations"] = [
        {"id": "c1", "type": "kb", "requirement_id": "A.9.2", "requirement_fr": "Paraphrase."}
    ]
    return [r1, r2]


def test_aggregate_rubric_partial_counts_as_non_support():
    results = _graded_results()
    pairs = build_pair_sheet(results)
    answers = build_answer_sheet(results)
    pairs[0]["label"] = "SUPPORTS"
    pairs[1]["label"] = "PARTIAL"
    answers[0]["label"] = "FAITHFUL"
    answers[1]["label"] = "PARTIALLY_FAITHFUL"

    agg = aggregate_rubric(pairs, answers, results)
    assert agg["pairs"]["n"] == 2
    assert agg["pairs"]["supports"] == 1
    assert agg["pairs"]["partial"] == 1
    assert agg["pairs"]["support_precision"]["count"] == 1  # PARTIAL = non-support
    # claim-level: q1 claim all-SUPPORTS, q4 claim has a PARTIAL pair
    assert agg["claims"]["n"] == 2
    assert agg["claims"]["all_supports"] == 1
    # question-level macro: (1.0 + 0.0) / 2
    assert agg["questions_macro_support"] == pytest.approx(0.5)
    # kb_only dedicated row joined by the scorer from evidence_scope
    assert agg["kb_only"]["n_pairs"] == 1
    assert agg["kb_only"]["supports"] == 0
    assert agg["answer_faithfulness"]["FAITHFUL"] == 1
    assert agg["answer_faithfulness"]["PARTIALLY_FAITHFUL"] == 1
    assert agg["answer_faithfulness"]["n"] == 2


def test_aggregate_rubric_multi_citation_claim_needs_all_supports():
    results = _graded_results()
    results[0]["claims"][0]["citation_ids"] = ["c1", "c2"]
    results[0]["citations"].append(
        {"id": "c2", "type": "kb", "requirement_id": "A.9.2", "requirement_fr": "Paraphrase."}
    )
    pairs = build_pair_sheet(results)
    answers = build_answer_sheet(results)
    for p in pairs:
        p["label"] = "SUPPORTS"
    # one pair of the q1 claim flips to IRRELEVANT -> the claim no longer counts
    pairs[0]["label"] = "IRRELEVANT"
    for a in answers:
        a["label"] = "FAITHFUL"

    agg = aggregate_rubric(pairs, answers, results)
    assert agg["claims"]["n"] == 2
    assert agg["claims"]["all_supports"] == 1  # only the q4 claim survives
