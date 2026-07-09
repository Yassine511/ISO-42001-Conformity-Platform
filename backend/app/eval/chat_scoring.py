"""Chat evaluation metrics — mechanical (machine-computable) and rubric §2
aggregation over human-graded sheets.

Mechanical metrics need no human labels: abstention precision/recall against
the generator's frozen `answerable` field, and citation-location validity
re-checked against each message's PERSISTED retrieval snapshot (never live
retrieval — documents may have been re-indexed since the run).

Rubric aggregation implements §2 exactly: pair-level support precision with
PARTIAL counted as non-support (reported separately), claim-level precision
(a claim counts only if ALL its pairs are SUPPORTS), answer faithfulness
counts, dedicated kb_only row. Pair-level Wilson intervals are DESCRIPTIVE
(pairs from one question are correlated): raw counts and a question-level
macro-average are always published alongside.
"""

from collections import defaultdict

from app.pipeline.state import is_infrastructure_failure
from app.pipeline.verifier import find_quote_in_retrieved

from .stats import Metric

INFRA_FAILED = "infra_failed"


def location_validity(result: dict) -> tuple[int, int]:
    """(located, total) over the message's returned citations, re-checked
    against its persisted retrieval snapshot. Expected ≈100% by construction —
    a regression signals a verifier bug, never citation quality."""
    located = 0
    total = 0
    retrieved_policy = result.get("retrieved_policy") or []
    kb_ids = {i.get("requirement_id") for i in (result.get("retrieved_kb") or [])}
    for citation in result.get("citations") or []:
        total += 1
        if citation["type"] == "policy":
            match = find_quote_in_retrieved(citation.get("quote") or "", retrieved_policy)
            if match is not None and match.method == "exact":
                located += 1
        else:
            if citation.get("requirement_id") in kb_ids:
                located += 1
    return located, total


def mechanical_metrics(run_results: list[dict], question_set: dict) -> dict:
    """Machine-computable metrics for one run (dev diagnostics or holdout)."""
    answerable_by_id = {q["question_id"]: q["answerable"] for q in question_set["items"]}
    n_total = len(question_set["items"])

    infra_ids: list[str] = []
    missing_ids: list[str] = []   # questions with no persisted result (error ledger)
    abstentions = 0
    abst_on_unanswerable = 0
    unanswerable_scored = 0
    answered = 0
    located_sum = 0
    citations_sum = 0
    stripped_sum = 0
    repair_used = 0
    scope_counts: dict[str, int] = defaultdict(int)
    abstain_reasons: dict[str, int] = defaultdict(int)

    results_by_id = {r["question_id"]: r for r in run_results}
    for qid, answerable in answerable_by_id.items():
        result = results_by_id.get(qid)
        if result is None:
            missing_ids.append(qid)
            continue
        if result["status"] == "ABSTAINED" and is_infrastructure_failure(
            result.get("abstain_reason")
        ):
            infra_ids.append(qid)
            abstain_reasons[result.get("abstain_reason") or "?"] += 1
            continue

        if not answerable:
            unanswerable_scored += 1
        if (result.get("draft_attempts") or 1) >= 2:
            repair_used += 1

        if result["status"] == "ABSTAINED":
            abstentions += 1
            abstain_reasons[result.get("abstain_reason") or "?"] += 1
            if not answerable:
                abst_on_unanswerable += 1
        else:
            answered += 1
            scope_counts[result.get("evidence_scope") or "?"] += 1
            located, total = location_validity(result)
            located_sum += located
            citations_sum += total
            stripped_sum += len(result.get("stripped_citations") or [])

    n_scored = n_total - len(infra_ids) - len(missing_ids)
    return {
        "n_total": n_total,
        "n_scored": n_scored,
        "infra_failed_ids": sorted(infra_ids),
        "missing_ids": sorted(missing_ids),
        "answered": answered,
        "abstentions": abstentions,
        "abstention_precision": (
            Metric.of(abst_on_unanswerable, abstentions).to_dict() if abstentions else None
        ),
        "abstention_recall": (
            Metric.of(abst_on_unanswerable, unanswerable_scored).to_dict()
            if unanswerable_scored
            else None
        ),
        "citation_location_validity": (
            Metric.of(located_sum, citations_sum).to_dict() if citations_sum else None
        ),
        "stripped_citations_total": stripped_sum,
        "repair_used": Metric.of(repair_used, n_scored).to_dict() if n_scored else None,
        "evidence_scopes": dict(scope_counts),
        "abstain_reasons": dict(abstain_reasons),
    }


def aggregate_rubric(
    filled_pairs: list[dict],
    filled_answers: list[dict],
    run_results: list[dict],
) -> dict:
    """Rubric §2 aggregation over validated (ingested) sheets.

    evidence_scope is joined back from run_results BY THE SCORER — it is a
    masked field and never appears in the sheets themselves.
    """
    scope_by_qid = {r["question_id"]: r.get("evidence_scope") for r in run_results}

    supports = sum(1 for p in filled_pairs if p["label"] == "SUPPORTS")
    partial = sum(1 for p in filled_pairs if p["label"] == "PARTIAL")
    irrelevant = sum(1 for p in filled_pairs if p["label"] == "IRRELEVANT")
    n_pairs = len(filled_pairs)

    # claim-level: a claim counts only if ALL its pairs are SUPPORTS
    pairs_by_claim: dict[tuple[str, int], list[str]] = defaultdict(list)
    for p in filled_pairs:
        pairs_by_claim[(p["question_id"], p["claim_index"])].append(p["label"])
    claims_all_supports = sum(
        1 for labels in pairs_by_claim.values() if all(l == "SUPPORTS" for l in labels)
    )
    n_claims = len(pairs_by_claim)

    # question-level macro-average of pair support (correlated-pairs caveat)
    pairs_by_question: dict[str, list[str]] = defaultdict(list)
    for p in filled_pairs:
        pairs_by_question[p["question_id"]].append(p["label"])
    per_question = [
        sum(1 for l in labels if l == "SUPPORTS") / len(labels)
        for labels in pairs_by_question.values()
    ]
    macro_support = sum(per_question) / len(per_question) if per_question else None

    # dedicated kb_only row (rubric §5)
    kb_only_pairs = [p for p in filled_pairs if scope_by_qid.get(p["question_id"]) == "kb_only"]
    kb_only_supports = sum(1 for p in kb_only_pairs if p["label"] == "SUPPORTS")

    faithfulness = {
        label: sum(1 for a in filled_answers if a["label"] == label)
        for label in ("FAITHFUL", "PARTIALLY_FAITHFUL", "UNFAITHFUL")
    }

    return {
        "pairs": {
            "n": n_pairs,
            "supports": supports,
            "partial": partial,
            "irrelevant": irrelevant,
            # Wilson here is a rough DESCRIPTIVE interval: pairs within a
            # question are correlated (rules §6 caveat)
            "support_precision": Metric.of(supports, n_pairs).to_dict() if n_pairs else None,
            "partial_rate": Metric.of(partial, n_pairs).to_dict() if n_pairs else None,
        },
        "claims": {
            "n": n_claims,
            "all_supports": claims_all_supports,
            "support_precision": (
                Metric.of(claims_all_supports, n_claims).to_dict() if n_claims else None
            ),
        },
        "questions_macro_support": macro_support,
        "questions_with_pairs": len(pairs_by_question),
        "kb_only": {
            "n_pairs": len(kb_only_pairs),
            "supports": kb_only_supports,
        },
        "answer_faithfulness": {**faithfulness, "n": len(filled_answers)},
    }
