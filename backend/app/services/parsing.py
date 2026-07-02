"""Document parsing: bytes -> list of page texts.

PDF via PyMuPDF (one entry per page), DOCX via python-docx (single entry),
plain text / markdown as-is. Page numbers are 1-based and serve as the
provenance anchor for chunks and citations downstream.
"""

import io

import fitz  # PyMuPDF
from docx import Document as DocxDocument


class UnsupportedFileType(Exception):
    pass


SUPPORTED_EXTENSIONS = {".pdf", ".docx", ".txt", ".md"}


def parse_document(filename: str, data: bytes) -> list[str]:
    """Return the extracted text of each page. Raises UnsupportedFileType."""
    name = filename.lower()
    if name.endswith(".pdf"):
        return _parse_pdf(data)
    if name.endswith(".docx"):
        return _parse_docx(data)
    if name.endswith((".txt", ".md")):
        return [data.decode("utf-8", errors="replace")]
    raise UnsupportedFileType(f"Type de fichier non supporté : {filename}")


def _parse_pdf(data: bytes) -> list[str]:
    with fitz.open(stream=data, filetype="pdf") as doc:
        return [page.get_text("text") for page in doc]


def _parse_docx(data: bytes) -> list[str]:
    doc = DocxDocument(io.BytesIO(data))
    parts: list[str] = [p.text for p in doc.paragraphs]
    for table in doc.tables:
        for row in table.rows:
            parts.append("\t".join(cell.text for cell in row.cells))
    return ["\n".join(parts)]
