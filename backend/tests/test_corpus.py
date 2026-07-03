"""M1b corpus consistency: runs the same checks as scripts/validate_corpus.py."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

import validate_corpus


def test_corpus_is_consistent():
    errors = validate_corpus.run()
    assert not errors, "\n".join(errors)
