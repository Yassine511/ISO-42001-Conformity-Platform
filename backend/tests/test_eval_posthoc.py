"""Verification-gate diagnostic: attempt-1 classification and the final
VERIFIED invariant re-check (M6 harness). Pure functions over canned data.
"""

import json
from types import SimpleNamespace

import pytest

from app.eval.posthoc import (
    FAIL_BAD_LENGTH,
    FAIL_FUZZY_ONLY,
    FAIL_NOT_FOUND,
    FAIL_NULL_QUOTE,
    KIND_ASSERTED,
    KIND_MISSING_DRAFT,
    KIND_NO_SUCCESS_CALL,
    KIND_UNPARSEABLE,
    classify_attempt1,
    reverify_final,
)

SOURCE = (
    "Le Comité IA de Lumen AI se réunit chaque trimestre pour examiner les risques. "
    "Les collaborateurs doivent signaler tout incident dans un délai de 48 heures."
)

RETRIEVED = [
    {
        "result_id": "chunk-1",
        "source_type": "policy",
        "text": SOURCE,
        "char_start": 0,
        "page_number": 1,
    }
]


def _content(verdict="compliant", quote=SOURCE[:60], clause="4.1", confidence=0.8):
    return json.dumps(
        {
            "verdict": verdict,
            "policy_quote": quote,
            "clause_ref": clause,
            "confidence": confidence,
            "rationale": "évaluation test",
        },
        ensure_ascii=False,
    )


def test_verbatim_quote_is_supported():
    outcome = classify_attempt1("4.1", _content(), RETRIEVED)
    assert outcome.kind == KIND_ASSERTED
    assert outcome.unsupported is False
    assert outcome.match_method == "exact"


def test_fabricated_quote_is_unsupported():
    outcome = classify_attempt1(
        "4.1", _content(quote="Une citation totalement inventée par le modèle ici."), RETRIEVED
    )
    assert outcome.kind == KIND_ASSERTED
    assert outcome.unsupported is True
    assert outcome.failure_mode == FAIL_NOT_FOUND


def test_fuzzy_only_near_match_is_unsupported_but_distinct():
    # one narrow typo form: adjacent transposition inside a long quote
    quote = SOURCE[:60].replace("dans", "dnas") if "dans" in SOURCE[:60] else SOURCE[:60]
    quote = "Les collaborateurs doivent signaler tout incident dnas un délai de 48 heures."
    outcome = classify_attempt1("4.1", _content(quote=quote), RETRIEVED)
    assert outcome.kind == KIND_ASSERTED
    assert outcome.unsupported is True
    assert outcome.failure_mode == FAIL_FUZZY_ONLY


def test_null_quote_with_asserted_verdict_is_unsupported():
    outcome = classify_attempt1("4.1", _content(quote=None), RETRIEVED)
    assert outcome.kind == KIND_ASSERTED
    assert outcome.unsupported is True
    assert outcome.failure_mode == FAIL_NULL_QUOTE


def test_too_short_quote_is_bad_length():
    outcome = classify_attempt1("4.1", _content(quote="Comité IA"), RETRIEVED)
    assert outcome.unsupported is True
    assert outcome.failure_mode == FAIL_BAD_LENGTH


def test_missing_draft_has_no_citation_denominator():
    outcome = classify_attempt1("4.1", _content(verdict="missing", quote=None), RETRIEVED)
    assert outcome.kind == KIND_MISSING_DRAFT
    assert outcome.unsupported is None


def test_unparseable_content_is_excluded_bucket():
    outcome = classify_attempt1("4.1", "pas du JSON {", RETRIEVED)
    assert outcome.kind == KIND_UNPARSEABLE
    assert outcome.unsupported is None


def test_schema_invalid_content_is_unparseable():
    outcome = classify_attempt1("4.1", json.dumps({"verdict": "compliant"}), RETRIEVED)
    assert outcome.kind == KIND_UNPARSEABLE


def test_no_success_call():
    outcome = classify_attempt1("4.1", None, RETRIEVED)
    assert outcome.kind == KIND_NO_SUCCESS_CALL


# ---------------------------------------------------------------- gate_diagnostic


def test_gate_diagnostic_aggregation():
    from app.eval.posthoc import gate_diagnostic

    outcomes = [
        classify_attempt1("A", _content(), RETRIEVED),                       # supported
        classify_attempt1("B", _content(quote="Quote inventée de toutes pièces ici."), RETRIEVED),
        classify_attempt1("C", _content(verdict="missing", quote=None), RETRIEVED),
        classify_attempt1("D", "pas du JSON", RETRIEVED),                    # unparseable
    ]
    findings = {
        "A": {"status": "VERIFIED", "attempts": 1},
        "B": {"status": "VERIFIED", "attempts": 2},   # repaired at attempt 2
        "C": {"status": "ABSTAINED", "attempts": 1},
        "D": {"status": "ABSTAINED", "attempts": 2},
    }
    diag = gate_diagnostic(outcomes, findings)
    assert diag["n"] == 4
    assert diag["attempt1_kinds"][KIND_ASSERTED] == 2
    assert diag["attempt1_kinds"][KIND_MISSING_DRAFT] == 1
    assert diag["attempt1_kinds"][KIND_UNPARSEABLE] == 1
    assert diag["attempt1_unsupported_over_asserted"]["count"] == 1
    assert diag["attempt1_unsupported_over_asserted"]["n"] == 2
    assert diag["attempt1_unsupported_over_all"]["n"] == 4
    assert diag["attempt1_failure_modes"] == {FAIL_NOT_FOUND: 1}
    assert diag["gate_outcomes"] == {"verified": 2, "repaired": 1, "abstained": 2}


# ---------------------------------------------------------------- reverify_final


def _finding_row(status="VERIFIED", verdict="compliant", quote=SOURCE[:60], retrieved=RETRIEVED):
    return SimpleNamespace(
        status=status, verdict=verdict, policy_quote=quote, retrieved=retrieved
    )


def test_reverify_final_holds_for_authentic_quote():
    assert reverify_final(_finding_row()) is True


def test_reverify_final_flags_corrupted_quote():
    assert reverify_final(_finding_row(quote="citation corrompue après coup, introuvable")) is False


def test_reverify_final_rejects_non_verified():
    with pytest.raises(ValueError):
        reverify_final(_finding_row(status="ABSTAINED"))
