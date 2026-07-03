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
    # sentence-boundary splits: chunks start at sentence starts (capital letter)
    for c in chunks:
        assert c.text[0].isupper()


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
