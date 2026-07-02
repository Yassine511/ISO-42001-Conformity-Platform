import pytest

from app.services.parsing import UnsupportedFileType, parse_document


def test_parse_txt():
    pages = parse_document("politique.txt", "Politique d'usage de l'IA — accès contrôlé.".encode())
    assert pages == ["Politique d'usage de l'IA — accès contrôlé."]


def test_parse_md():
    pages = parse_document("charte.md", b"# Charte\nGouvernance de l'IA")
    assert len(pages) == 1
    assert "Gouvernance" in pages[0]


def test_parse_pdf_per_page():
    import fitz

    doc = fitz.open()
    for text in ["Page une : gouvernance des données.", "Page deux : cycle de vie du modèle."]:
        page = doc.new_page()
        page.insert_text((72, 72), text)
    data = doc.tobytes()

    pages = parse_document("politique.pdf", data)
    assert len(pages) == 2
    assert "gouvernance" in pages[0]
    assert "cycle de vie" in pages[1]


def test_parse_docx():
    import io

    from docx import Document as DocxDocument

    d = DocxDocument()
    d.add_paragraph("Politique de gestion des risques IA.")
    buf = io.BytesIO()
    d.save(buf)

    pages = parse_document("risques.docx", buf.getvalue())
    assert len(pages) == 1
    assert "risques IA" in pages[0]


def test_unsupported_type():
    with pytest.raises(UnsupportedFileType):
        parse_document("image.png", b"\x89PNG")
