"""Deterministic chat_eval question-set generator — FROZEN BEFORE M5.

This file, together with corpus/gold/chat_eval_rubric.md, is the frozen
evaluation contract for the M6 chat measurement (plan §10). It is committed
BEFORE the M5 UI feedback loop so that no post-M5 freedom remains in how the
holdout is derived: the question template, the transformation of KB
paraphrases, the output schema and the answerability rule are all fixed here.
Any change to this file or the rubric before the M6 run must be reported in
the M6 results (the sha256 of both files is embedded in every generated set).

Rules (frozen):
- One question per gold requirement of the chosen split, in gold file order.
- Question = QUESTION_TEMPLATE filled with the KB paraphrase — a mechanical
  transformation; no hand-written questions, no per-item adjustment.
- answerable := gold verdict != "missing".
- The gold evidence span is included as a REFERENCE ANCHOR only: at grading
  time, any passage that genuinely supports a claim counts (rubric §3), the
  anchor is not the only acceptable support.
- The --split test run is reserved for M6: it requires --m6-holdout, and dev
  runs are development diagnostics only (corpus/README.md split contract).

    python scripts/chat_eval_generate.py --split dev  -o chat_eval_dev.json
    python scripts/chat_eval_generate.py --split test --m6-holdout -o chat_eval_holdout.json   # M6 only
"""

import argparse
import hashlib
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

GENERATOR_VERSION = "1"
TEMPLATE_VERSION = "1"
# Frozen French question template. The requirement id is deliberately NOT in
# the question text (an auditor asks about a topic, not a clause number, and
# including the id would trivialize KB retrieval).
QUESTION_TEMPLATE = (
    "Comment notre organisation couvre-t-elle l'exigence ISO/IEC 42001 "
    "suivante : « {requirement_fr} » ?"
)

RUBRIC_PATH = REPO_ROOT / "corpus" / "gold" / "chat_eval_rubric.md"
GOLD_PATH = REPO_ROOT / "corpus" / "gold" / "gold_labels.json"
KB_PATH = REPO_ROOT / "corpus" / "kb" / "iso42001_kb.json"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def generate(split: str) -> dict:
    gold = json.loads(GOLD_PATH.read_text(encoding="utf-8"))
    kb = json.loads(KB_PATH.read_text(encoding="utf-8"))
    kb_by_id = {e["id"]: e for e in kb["requirements"]}

    gold_version = gold["meta"]["corpus_version"]
    kb_version = kb["meta"]["corpus_version"]
    if gold_version != kb_version:
        raise SystemExit(
            f"corpus_version mismatch: gold {gold_version} != kb {kb_version}"
        )

    items = []
    for g in gold["items"]:
        if g["split"] != split:
            continue
        req = kb_by_id[g["requirement_id"]]
        items.append(
            {
                "question_id": f"chat_eval:{split}:{g['requirement_id']}",
                "requirement_id": g["requirement_id"],
                "split": split,
                "question_fr": QUESTION_TEMPLATE.format(
                    requirement_fr=req["requirement_fr"]
                ),
                # frozen rule: answerable iff the gold verdict is not `missing`
                "answerable": g["verdict"] != "missing",
                "expected_requirement_id": g["requirement_id"],
                # reference anchor, NOT the only acceptable support (rubric §3)
                "gold_evidence_anchor": (
                    {"document": g["document"], "evidence_quote_fr": g["evidence_quote_fr"]}
                    if g["verdict"] != "missing"
                    else None
                ),
            }
        )

    return {
        "meta": {
            "corpus_version": gold_version,
            "split": split,
            "generator_version": GENERATOR_VERSION,
            "template_version": TEMPLATE_VERSION,
            "generator_sha256": _sha256(Path(__file__)),
            "rubric_sha256": _sha256(RUBRIC_PATH),
            "question_count": len(items),
            "unanswerable_count": sum(1 for i in items if not i["answerable"]),
        },
        "items": items,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--split", required=True, choices=["dev", "test"])
    parser.add_argument("-o", "--output", required=True)
    parser.add_argument(
        "--m6-holdout",
        action="store_true",
        help="required to generate from the test split — M6 report run only",
    )
    args = parser.parse_args()

    if args.split == "test" and not args.m6_holdout:
        print(
            "REFUS : le split test est réservé au rapport M6. Générez le holdout "
            "uniquement au moment de M6, avec --m6-holdout.",
            file=sys.stderr,
        )
        return 2

    payload = generate(args.split)
    Path(args.output).write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(
        f"{payload['meta']['question_count']} questions ({args.split}, "
        f"{payload['meta']['unanswerable_count']} sans réponse attendue) -> {args.output}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
