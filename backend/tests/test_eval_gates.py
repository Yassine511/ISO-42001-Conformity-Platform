"""Holdout and freeze gates (M6 harness).

The git interaction is injectable (`check_freeze_gate(git=...)`) so these
tests never touch the real repository state. The script-level refusal of the
test split without --m6-holdout is covered by calling the scripts' main()
with argv — no DB/LLM is reached because the refusal happens first.
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

from app.eval.gates import (
    FREEZE_TAG,
    GateError,
    check_document_baseline,
    check_freeze_gate,
    check_generator_drift,
    contract_hashes,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = REPO_ROOT / "scripts"


# ---------------------------------------------------------------- freeze gate


def _fake_git(head: str, tag_sha: str | None, status: str):
    def git(repo_root, *args):
        if args[:2] == ("rev-parse", "HEAD"):
            return head
        if args[0] == "rev-parse" and FREEZE_TAG in args[1]:
            if tag_sha is None:
                raise subprocess.CalledProcessError(128, "git")
            return tag_sha
        if args[0] == "status":
            return status
        raise AssertionError(f"appel git inattendu : {args}")

    return git


def _run_dir(tmp_path: Path) -> Path:
    d = REPO_ROOT / "eval" / "m6" / "runs" / "test-run"
    return d


def test_freeze_gate_accepts_frozen_head_and_clean_tree():
    git = _fake_git("abc123", "abc123", "")
    sha = check_freeze_gate(REPO_ROOT, _run_dir(REPO_ROOT), git=git)
    assert sha == "abc123"


def test_freeze_gate_refuses_missing_tag():
    git = _fake_git("abc123", None, "")
    with pytest.raises(GateError, match=FREEZE_TAG):
        check_freeze_gate(REPO_ROOT, _run_dir(REPO_ROOT), git=git)


def test_freeze_gate_refuses_head_not_at_tag():
    git = _fake_git("abc123", "def456", "")
    with pytest.raises(GateError, match="état gelé"):
        check_freeze_gate(REPO_ROOT, _run_dir(REPO_ROOT), git=git)


def test_freeze_gate_refuses_dirty_source_path():
    git = _fake_git("abc123", "abc123", " M backend/app/pipeline/verifier.py")
    with pytest.raises(GateError, match="hors du répertoire d'artefacts"):
        check_freeze_gate(REPO_ROOT, _run_dir(REPO_ROOT), git=git)


def test_freeze_gate_refuses_dirty_corpus_path():
    git = _fake_git("abc123", "abc123", " M corpus/gold/gold_labels.json")
    with pytest.raises(GateError):
        check_freeze_gate(REPO_ROOT, _run_dir(REPO_ROOT), git=git)


def test_freeze_gate_allows_dirty_artifact_dir_only():
    # holdout commands write artifacts under the declared run dir — a blanket
    # clean-worktree check would self-refuse the session's second command
    status = "?? eval/m6/runs/test-run/pipeline_test.json\n?? eval/m6/runs/test-run/sheets/pairs_test.json"
    git = _fake_git("abc123", "abc123", status)
    assert check_freeze_gate(REPO_ROOT, _run_dir(REPO_ROOT), git=git) == "abc123"


def test_freeze_gate_mixed_dirty_still_refuses():
    status = "?? eval/m6/runs/test-run/pipeline_test.json\n M scripts/eval_pipeline.py"
    git = _fake_git("abc123", "abc123", status)
    with pytest.raises(GateError):
        check_freeze_gate(REPO_ROOT, _run_dir(REPO_ROOT), git=git)


# ---------------------------------------------------------------- doc baseline


def _corpus_docs() -> list[tuple[str, str]]:
    import hashlib

    return [
        (p.name, hashlib.sha256(p.read_bytes()).hexdigest())
        for p in sorted((REPO_ROOT / "corpus" / "documents").glob("*.md"))
    ]


def test_document_baseline_accepts_exact_corpus():
    check_document_baseline(_corpus_docs(), REPO_ROOT)


def test_document_baseline_refuses_extra_document():
    docs = _corpus_docs() + [("ISO 24001 synthese.pdf", "0" * 64)]
    with pytest.raises(GateError, match="hors corpus"):
        check_document_baseline(docs, REPO_ROOT)


def test_document_baseline_refuses_missing_document():
    with pytest.raises(GateError, match="absent"):
        check_document_baseline(_corpus_docs()[:-1], REPO_ROOT)


def test_document_baseline_refuses_checksum_drift():
    docs = _corpus_docs()
    docs[0] = (docs[0][0], "0" * 64)
    with pytest.raises(GateError, match="checksum"):
        check_document_baseline(docs, REPO_ROOT)


# ---------------------------------------------------------------- sha drift


def _question_set_meta() -> dict:
    import hashlib

    return {
        "meta": {
            "split": "dev",
            "generator_sha256": hashlib.sha256(
                (REPO_ROOT / "scripts" / "chat_eval_generate.py").read_bytes()
            ).hexdigest(),
            "rubric_sha256": hashlib.sha256(
                (REPO_ROOT / "corpus" / "gold" / "chat_eval_rubric.md").read_bytes()
            ).hexdigest(),
        }
    }


def test_generator_drift_accepts_current_hashes():
    check_generator_drift(_question_set_meta(), REPO_ROOT)


def test_generator_drift_refuses_stale_generator():
    qs = _question_set_meta()
    qs["meta"]["generator_sha256"] = "0" * 64
    with pytest.raises(GateError, match="dérive du générateur"):
        check_generator_drift(qs, REPO_ROOT)


def test_generator_drift_refuses_stale_rubric():
    qs = _question_set_meta()
    qs["meta"]["rubric_sha256"] = "0" * 64
    with pytest.raises(GateError, match="dérive de la rubrique"):
        check_generator_drift(qs, REPO_ROOT)


# ---------------------------------------------------------------- script gates


def test_eval_pipeline_refuses_test_split_without_flag(monkeypatch, capsys):
    sys.path.insert(0, str(SCRIPTS))
    try:
        import eval_pipeline

        monkeypatch.setattr(
            sys, "argv",
            ["eval_pipeline.py", "--org", "Lumen AI", "--split", "test", "--run-id", "x"],
        )
        assert eval_pipeline.main() == 2
        assert "REFUS" in capsys.readouterr().err
    finally:
        sys.path.remove(str(SCRIPTS))


def test_eval_chat_run_refuses_test_split_without_flag(monkeypatch, tmp_path, capsys):
    question_set = {
        "meta": {"split": "test", "generator_sha256": "x", "rubric_sha256": "y"},
        "items": [],
    }
    qpath = tmp_path / "chat_eval_holdout.json"
    qpath.write_text(json.dumps(question_set), encoding="utf-8")
    sys.path.insert(0, str(SCRIPTS))
    try:
        import eval_chat_run

        monkeypatch.setattr(
            sys, "argv",
            [
                "eval_chat_run.py", "--org", "Lumen AI",
                "--questions", str(qpath), "--run-id", "x",
            ],
        )
        assert eval_chat_run.main() == 2
        assert "réservé au rapport M6" in capsys.readouterr().err
    finally:
        sys.path.remove(str(SCRIPTS))


def test_contract_hashes_cover_all_frozen_inputs(tmp_path):
    # the rules doc does not exist yet in a fresh checkout of this test?
    # -> it must exist in the repo before any holdout run; here we assert the
    # function demands it rather than silently skipping
    if (REPO_ROOT / "eval" / "m6" / "regles_notation_pipeline.md").exists():
        hashes = contract_hashes(REPO_ROOT)
        assert "corpus/gold/gold_labels.json" in hashes
        assert "scripts/chat_eval_generate.py" in hashes
        assert any(k.startswith("backend/app/eval/") for k in hashes)
    else:
        with pytest.raises(GateError, match="contrat introuvable"):
            contract_hashes(REPO_ROOT)
