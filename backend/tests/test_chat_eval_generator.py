"""The frozen chat_eval generator must stay deterministic and split-guarded.

These tests exercise the DEV split only: generating the test-split holdout is
reserved for the M6 run (the CLI guard below is what enforces that)."""

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "chat_eval_generate.py"

spec = importlib.util.spec_from_file_location("chat_eval_generate", SCRIPT)
generator = importlib.util.module_from_spec(spec)
spec.loader.exec_module(generator)


def test_dev_generation_is_deterministic_and_schema_complete():
    a = generator.generate("dev")
    b = generator.generate("dev")
    assert a == b  # fully deterministic — no randomness, no per-run state

    meta = a["meta"]
    assert meta["split"] == "dev"
    assert meta["question_count"] == 51
    assert meta["unanswerable_count"] == 8
    assert meta["generator_sha256"] and meta["rubric_sha256"]
    assert meta["generator_version"] == generator.GENERATOR_VERSION
    assert meta["template_version"] == generator.TEMPLATE_VERSION

    for item in a["items"]:
        assert item["question_id"] == f"chat_eval:dev:{item['requirement_id']}"
        assert item["question_fr"].startswith("Comment notre organisation couvre-t-elle")
        assert item["expected_requirement_id"] == item["requirement_id"]
        if item["answerable"]:
            anchor = item["gold_evidence_anchor"]
            assert anchor["document"] and anchor["evidence_quote_fr"]
        else:
            assert item["gold_evidence_anchor"] is None


def test_test_split_requires_m6_holdout_flag(tmp_path):
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--split", "test", "-o", str(tmp_path / "x.json")],
        capture_output=True,
        # Pin BOTH sides of the pipe to UTF-8: the script prints French to
        # stderr, and on Windows the child's stdio encoding and the parent's
        # text=True decode each default to the console locale independently —
        # a mismatch turns « réservé » into mojibake and fails the assert
        # below depending on which shell launched pytest.
        encoding="utf-8",
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
    )
    assert result.returncode == 2
    assert "réservé au rapport M6" in result.stderr
    assert not (tmp_path / "x.json").exists()
