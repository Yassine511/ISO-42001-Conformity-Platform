import re

from app.services.chunking import (
    HARD_MAX_CHARS,
    ChunkSpan,
    chunk_page,
    make_chunk_id,
)


def _assert_invariants(text: str, chunks: list[ChunkSpan]):
    covered = set()
    for c in chunks:
        assert text[c.char_start : c.char_end] == c.text, "slice invariant broken"
        assert len(c.text) <= HARD_MAX_CHARS
        covered.update(range(c.char_start, c.char_end))
    for i, ch in enumerate(text):
        if not ch.isspace():
            assert i in covered, f"non-whitespace char at {i} ({ch!r}) not covered"


def test_multiple_short_paragraphs_packed():
    text = "Premier paragraphe.\n\nDeuxième paragraphe.\n\nTroisième paragraphe."
    chunks = chunk_page(text)
    _assert_invariants(text, chunks)
    assert len(chunks) == 1  # short paragraphs pack together


def test_packing_respects_target():
    para = "Phrase de remplissage pour le test. " * 12  # ~430 chars
    text = "\n\n".join(para.strip() for _ in range(5))
    chunks = chunk_page(text)
    _assert_invariants(text, chunks)
    assert len(chunks) > 1


def test_oversized_paragraph_sentence_split():
    text = "Ceci est une phrase complète du document de politique. " * 40  # ~2200, one paragraph
    chunks = chunk_page(text.strip())
    _assert_invariants(text.strip(), chunks)
    assert len(chunks) >= 2
    # cuts land at sentence ends; later chunks start mid-overlap by design
    for c in chunks[:-1]:
        assert c.text.rstrip().endswith(".")
    assert chunks[0].text[0].isupper()


def test_oversized_paragraph_without_sentences_whitespace_split():
    text = "mot " * 500  # ~2000 chars, no sentence punctuation
    chunks = chunk_page(text.strip())
    _assert_invariants(text.strip(), chunks)
    assert all(len(c.text) <= HARD_MAX_CHARS for c in chunks)


def test_no_whitespace_pathological():
    text = "x" * 3000
    chunks = chunk_page(text)
    _assert_invariants(text, chunks)


def test_leading_trailing_blank_lines():
    text = "\n\n\n  Contenu réel du document.  \n\n\n"
    chunks = chunk_page(text)
    _assert_invariants(text, chunks)
    assert chunks[0].text == "Contenu réel du document."


def test_unicode_punctuation_and_table_newlines():
    text = (
        "Politique « données d'entraînement » — version 2.1…\n"
        "Colonne A\tColonne B\tColonne C\n"
        "valeur 1\tvaleur 2\tvaleur 3\n\n"
        "Paragraphe suivant après le tableau."
    )
    chunks = chunk_page(text)
    _assert_invariants(text, chunks)


def test_empty_and_blank_pages():
    assert chunk_page("") == []
    assert chunk_page("   \n\n  \t ") == []


def test_deterministic():
    text = ("Un paragraphe stable. " * 30 + "\n\n") * 4
    assert chunk_page(text) == chunk_page(text)


def test_chunk_id_distinct_across_documents():
    a = make_chunk_id("doc-A", "2", 1, 0, 100)
    b = make_chunk_id("doc-B", "2", 1, 0, 100)
    assert a != b
    assert a == make_chunk_id("doc-A", "2", 1, 0, 100)  # deterministic


def test_forced_split_at_nonzero_offset_regression():
    """Audit P2: finditer offsets are absolute; adding p_start double-counted.

    A long paragraph AFTER an earlier paragraph must still split at sentence
    boundaries, with a real overlap on forced splits.
    """
    prefix = "Paragraphe d'introduction.\n\n"
    long_para = "Ceci est une phrase complète du document de politique interne. " * 40
    text = prefix + long_para.strip()
    chunks = chunk_page(text)
    _assert_invariants(text, chunks)

    split_chunks = [c for c in chunks if c.char_start >= len(prefix)]
    assert len(split_chunks) >= 2
    for c in split_chunks[:-1]:
        assert c.text.rstrip().endswith("."), f"cut not at sentence boundary: ...{c.text[-40:]!r}"
    for a, b in zip(split_chunks, split_chunks[1:]):
        overlap = a.char_end - b.char_start
        assert overlap >= 20, f"forced-split overlap too small: {overlap}"


def test_sentence_boundary_between_target_and_hard_max_preferred():
    """Audit P2: a sentence cut at ~1101 must beat a whitespace cut at ~1196."""
    s1 = "Première phrase du paragraphe qui est déjà assez longue pour compter. "  # ~71
    # one sentence ending between TARGET (1000) and HARD_MAX (1200)
    long_sentence = "x" * 1030 + ". "
    tail = "mot " * 200  # no sentence punctuation
    text = s1 + long_sentence + tail.strip()
    chunks = chunk_page(text)
    _assert_invariants(text, chunks)
    boundary = text.index(long_sentence) + len(long_sentence.rstrip())
    assert any(
        abs(c.char_end - boundary) <= 1 for c in chunks
    ), f"no cut at the sentence boundary {boundary}: {[(c.char_start, c.char_end) for c in chunks]}"


def test_no_degenerate_creeping_chunks():
    """Audit R3 P1: the overlap must not let the previous cut be reused —
    a 3300-char paragraph once produced 28 creeping duplicates."""
    # sentences longer than TARGET force the pathological window
    text = ("y" * 1050 + ". ") * 3 + "fin du paragraphe."
    chunks = chunk_page(text)
    _assert_invariants(text, chunks)
    assert len(chunks) <= 8, f"degenerate chunking: {len(chunks)} chunks"
    ends = [c.char_end for c in chunks]
    assert ends == sorted(set(ends)), "duplicate or non-advancing cut positions"
    for a, b in zip(chunks, chunks[1:]):
        assert b.char_end > a.char_end
