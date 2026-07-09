"""Holdout and freeze gates for the M6 eval runners.

The chat_eval generator's refusal contract (test split needs --m6-holdout) is
extended here to run execution: a holdout run must provably execute from the
frozen state. `check_freeze_gate` requires HEAD to be exactly the `m6-freeze`
tag and the worktree to be clean EXCEPT under the declared artifact directory
(holdout commands themselves write artifacts there — a blanket clean check
would self-refuse the second command of the same session). Any dirty source /
corpus / rules path is a hard refusal.

`contract_hashes` records the sha256 of every frozen input (scoring rules,
generator, rubric, gold, KB, evaluator sources) into run artifacts, so the
report can bind results to exact file states.
"""

import hashlib
import subprocess
from pathlib import Path

FREEZE_TAG = "m6-freeze"

# frozen inputs, repo-root-relative
CONTRACT_FILES = (
    "eval/m6/regles_notation_pipeline.md",
    "scripts/chat_eval_generate.py",
    "corpus/gold/chat_eval_rubric.md",
    "corpus/gold/gold_labels.json",
    "corpus/kb/iso42001_kb.json",
)
EVALUATOR_SOURCES = (
    "backend/app/eval",
    "scripts/eval_pipeline.py",
    "scripts/eval_chat_run.py",
    "scripts/eval_chat_score.py",
)


class GateError(RuntimeError):
    """A holdout/freeze gate refusal (French message, exit code 2)."""


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def contract_hashes(repo_root: Path) -> dict[str, str]:
    hashes: dict[str, str] = {}
    for rel in CONTRACT_FILES:
        path = repo_root / rel
        if not path.exists():
            raise GateError(f"fichier de contrat introuvable : {rel}")
        hashes[rel] = _sha256(path)
    for rel in EVALUATOR_SOURCES:
        path = repo_root / rel
        if path.is_dir():
            for f in sorted(path.rglob("*.py")):
                hashes[f.relative_to(repo_root).as_posix()] = _sha256(f)
        elif path.exists():
            hashes[rel] = _sha256(path)
    return hashes


def check_generator_drift(question_set: dict, repo_root: Path) -> None:
    """The question set embeds generator/rubric sha256 at generation time —
    any drift against the current files invalidates the run (hard refusal)."""
    meta = question_set["meta"]
    current_generator = _sha256(repo_root / "scripts" / "chat_eval_generate.py")
    current_rubric = _sha256(repo_root / "corpus" / "gold" / "chat_eval_rubric.md")
    if meta["generator_sha256"] != current_generator:
        raise GateError(
            "dérive du générateur : le sha256 embarqué dans le jeu de questions "
            "ne correspond plus à scripts/chat_eval_generate.py."
        )
    if meta["rubric_sha256"] != current_rubric:
        raise GateError(
            "dérive de la rubrique : le sha256 embarqué dans le jeu de questions "
            "ne correspond plus à corpus/gold/chat_eval_rubric.md."
        )


def _git(repo_root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=repo_root, capture_output=True, text=True, check=True
    )
    return result.stdout.strip()


def check_freeze_gate(repo_root: Path, artifact_dir: Path, *, git=_git) -> str:
    """Enforce the frozen state for a holdout run; returns the freeze SHA.

    `git` is injectable for tests (no real repo manipulation needed).
    """
    head = git(repo_root, "rev-parse", "HEAD")
    try:
        tag_sha = git(repo_root, "rev-parse", f"{FREEZE_TAG}^{{commit}}")
    except subprocess.CalledProcessError as exc:
        raise GateError(
            f"tag {FREEZE_TAG} introuvable : créez-le sur le commit de gel avant "
            "tout run holdout."
        ) from exc
    if head != tag_sha:
        raise GateError(
            f"HEAD ({head[:12]}) n'est pas le commit gelé {FREEZE_TAG} "
            f"({tag_sha[:12]}) : le holdout doit s'exécuter depuis l'état gelé."
        )

    allowed_prefix = artifact_dir.resolve().relative_to(repo_root.resolve()).as_posix()
    status = git(repo_root, "status", "--porcelain")
    dirty = []
    for line in status.splitlines():
        # porcelain: XY <path> (renames: "old -> new")
        path = line[3:].split(" -> ")[-1].strip().strip('"')
        if not path.startswith(allowed_prefix.rstrip("/") + "/") and path != allowed_prefix:
            dirty.append(path)
    if dirty:
        raise GateError(
            "arbre de travail modifié hors du répertoire d'artefacts "
            f"({allowed_prefix}/) : {', '.join(sorted(dirty)[:5])} — refus du run "
            "holdout (état non gelé)."
        )
    return head
