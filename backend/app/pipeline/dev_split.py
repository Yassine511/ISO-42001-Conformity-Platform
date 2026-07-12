"""Frozen dev-split requirement manifest (M6 holdout protection).

The 14 test-split requirements are reserved for the M6 report and must never
be run, reviewed or tuned against during M2-M5. Runtime code therefore never
reads corpus/gold/gold_labels.json (which would couple the API to gold-label
membership); this literal list is the only manifest M5 runs can draw from.

Provenance: extracted from corpus/gold/gold_labels.json (originally at
corpus_version 1.2.0, split == "dev"), in gold order. The 1.3.0 bump (M8) added
per-requirement control weights only — the split membership is unchanged.
tests/test_pipeline.py cross-checks this list against the gold file so it
cannot silently drift.

create_assessment() rejects any id outside this list unless called with
allow_holdout=True — a keyword no HTTP route exposes; the M6 evaluation script
is its only intended caller, after the implementation freeze.
"""

DEV_SPLIT_CORPUS_VERSION = "1.3.0"

DEV_REQUIREMENT_IDS: list[str] = [
    "A.2.2",
    "A.2.3",
    "A.3.2",
    "A.3.3",
    "4.3",
    "A.9.2",
    "A.9.4",
    "A.9.3",
    "7.3",
    "A.7.2",
    "A.7.3",
    "A.7.4",
    "A.7.5",
    "A.7.6",
    "6.1.2",
    "6.1.3",
    "A.5.2",
    "A.5.4",
    "A.5.3",
    "A.6.1.2",
    "A.6.2.2",
    "A.6.2.4",
    "A.6.2.6",
    "A.6.2.8",
    "A.10.2",
    "A.10.3",
    "A.10.4",
    "A.4.5",
    "A.4.6",
    "A.6.2.7",
    "9.2",
    "10.2",
    "4.4",
    "5.1",
    "5.3",
    "6.1.1",
    "6.1.4",
    "6.2",
    "6.3",
    "7.5",
    "8.1",
    "8.2",
    "8.3",
    "8.4",
    "9.1",
    "9.3",
    "10.1",
    "A.4.2",
    "A.6.1.3",
    "A.8.2",
    "A.8.5",
]

_DEV_SET = frozenset(DEV_REQUIREMENT_IDS)


def is_dev_requirement(requirement_id: str) -> bool:
    return requirement_id in _DEV_SET
