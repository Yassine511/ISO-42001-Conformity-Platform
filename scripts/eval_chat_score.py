"""M6 chat scoring — mechanical metrics, grading-sheet build, and rubric
aggregation over human-graded sheets. Fully offline (reads run artifacts).

    # machine-computable metrics (dev diagnostics AND holdout)
    python scripts/eval_chat_score.py mechanical --run eval/m6/runs/dev1/chat_run_dev.json

    # build the EMPTY grading sheets from a holdout run artifact (rubric §4 masking)
    python scripts/eval_chat_score.py sheets --run eval/m6/runs/holdout/chat_run_test.json

    # aggregate the FILLED sheets (tamper-proof ingest, rubric §2 formulas)
    python scripts/eval_chat_score.py aggregate --run eval/m6/runs/holdout/chat_run_test.json \
        --pairs .../sheets/pairs_test.json --answers .../sheets/answers_test.json

Sheets are JSON UTF-8; the grader fills ONLY `label` (and optionally
`comment`). Ingest regenerates the canonical sheet from the run artifact and
rejects any modification of an immutable field.
"""

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "backend"))


def _load(path: str) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _write(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"écrit : {path}")


def cmd_mechanical(args) -> int:
    from app.eval.chat_scoring import mechanical_metrics

    run = _load(args.run)
    # the generated question set carries the frozen `answerable` field
    question_set = _load(args.questions)
    if _sha(args.questions) != run["meta"]["question_set_sha256"]:
        print(
            "REFUS : le jeu de questions fourni ne correspond pas à celui du run "
            "(sha256 différent).",
            file=sys.stderr,
        )
        return 2

    metrics = mechanical_metrics(run["results"], question_set)
    out = Path(args.run).with_name(
        Path(args.run).stem.replace("chat_run", "chat_mechanical") + ".json"
    )
    _write(
        out,
        {
            "meta": {
                "kind": "m6_chat_mechanical",
                "run_sha256": _sha(args.run),
                "question_set_sha256": _sha(args.questions),
                "computed_at": datetime.now(timezone.utc).isoformat(),
                "split": run["meta"]["split"],
            },
            "metrics": metrics,
        },
    )
    loc = metrics["citation_location_validity"]
    print(
        f"N={metrics['n_total']}  n_scored={metrics['n_scored']}  "
        f"répondu={metrics['answered']}  abstentions={metrics['abstentions']}"
        + (
            f"\nvalidité de localisation : {loc['count']}/{loc['n']}"
            if loc
            else "\nvalidité de localisation : aucune citation"
        )
    )
    return 0


def cmd_sheets(args) -> int:
    from app.eval.sheets import build_answer_sheet, build_pair_sheet

    run = _load(args.run)
    split = run["meta"]["split"]
    sheets_dir = Path(args.run).parent / "sheets"
    pairs = build_pair_sheet(run["results"])
    answers = build_answer_sheet(run["results"])
    _write(sheets_dir / f"pairs_{split}.json", pairs)
    _write(sheets_dir / f"answers_{split}.json", answers)
    print(
        f"{len(pairs)} paire(s) claim–citation, {len(answers)} réponse(s) à noter — "
        "remplissez UNIQUEMENT label (et comment)."
    )
    return 0


def cmd_aggregate(args) -> int:
    from app.eval.chat_scoring import aggregate_rubric
    from app.eval.sheets import SheetError, build_answer_sheet, build_pair_sheet, ingest

    run = _load(args.run)
    filled_pairs = _load(args.pairs)
    filled_answers = _load(args.answers)
    try:
        ingest(filled_pairs, filled_answers, run["results"])
    except SheetError as exc:
        print(f"REFUS : {exc}", file=sys.stderr)
        return 2

    aggregates = aggregate_rubric(filled_pairs, filled_answers, run["results"])
    empty_pairs = build_pair_sheet(run["results"])
    empty_answers = build_answer_sheet(run["results"])
    from app.eval.sheets import sha256_payload

    out = Path(args.run).with_name(
        Path(args.run).stem.replace("chat_run", "chat_scores") + ".json"
    )
    _write(
        out,
        {
            "meta": {
                "kind": "m6_chat_rubric_scores",
                "split": run["meta"]["split"],
                "run_sha256": _sha(args.run),
                "question_set_sha256": run["meta"]["question_set_sha256"],
                "empty_pairs_sha256": sha256_payload(empty_pairs),
                "empty_answers_sha256": sha256_payload(empty_answers),
                "filled_pairs_sha256": _sha(args.pairs),
                "filled_answers_sha256": _sha(args.answers),
                "rubric_sha256": run["meta"]["question_set_meta"]["rubric_sha256"],
                "computed_at": datetime.now(timezone.utc).isoformat(),
            },
            "aggregates": aggregates,
        },
    )
    p = aggregates["pairs"]
    print(
        f"paires : {p['supports']}/{p['n']} SUPPORTS ({p['partial']} PARTIAL, "
        f"{p['irrelevant']} IRRELEVANT) ; claims tout-SUPPORTS : "
        f"{aggregates['claims']['all_supports']}/{aggregates['claims']['n']}"
    )
    return 0


def _sha(path: str) -> str:
    import hashlib

    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p_mech = sub.add_parser("mechanical", help="machine-computable metrics")
    p_mech.add_argument("--run", required=True)
    p_mech.add_argument("--questions", required=True, help="generated question-set JSON")

    p_sheets = sub.add_parser("sheets", help="build empty grading sheets")
    p_sheets.add_argument("--run", required=True)

    p_agg = sub.add_parser("aggregate", help="aggregate filled sheets (rubric §2)")
    p_agg.add_argument("--run", required=True)
    p_agg.add_argument("--pairs", required=True)
    p_agg.add_argument("--answers", required=True)

    args = parser.parse_args()
    return {"mechanical": cmd_mechanical, "sheets": cmd_sheets, "aggregate": cmd_aggregate}[
        args.command
    ](args)


if __name__ == "__main__":
    sys.exit(main())
