"""M8 PDF report (WeasyPrint HTML→PDF).

One ReportingScope snapshot feeds every section (conformity, trust panel,
risk register, SoA) — the same isolated transaction the reporting endpoints
use, so the PDF can never mix corpus states or review generations.

Environment contract: WeasyPrint needs native Pango/Cairo libraries. The
Docker image installs them (backend/Dockerfile); a bare Windows host venv
typically cannot load them, so the import is LAZY and only recognized
import/native-load failures (ImportError, OSError) map to "unavailable"
(HTTP 503 at the API layer). A template or rendering defect stays an
ordinary exception (HTTP 500) — never disguised as environment
unavailability. The mandatory native-lib validation is the CI Docker smoke
test, not the host suite.
"""

from __future__ import annotations

from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape
from sqlalchemy.orm import Session

from app.services import scoring, soa

_TEMPLATES = Path(__file__).resolve().parent.parent / "templates"

_env = Environment(
    loader=FileSystemLoader(_TEMPLATES),
    autoescape=select_autoescape(["html", "j2"]),
)


class PdfUnavailableError(RuntimeError):
    """WeasyPrint (or its native libraries) cannot load on this host."""


def build_report_context(db: Session, scope: scoring.ReportingScope) -> dict:
    """Everything the template renders, from the ONE scope snapshot. Pure
    data assembly — testable without WeasyPrint."""
    return {
        "scope": scope.meta(),
        "conformity": scoring.conformity_summary(scope),
        "register": scoring.risk_register(scope),
        "trust": scoring.trust_panel(db, scope),
        "soa": soa.soa_table(db, scope),
    }


def render_report_html(context: dict) -> str:
    return _env.get_template("report.html.j2").render(**context)


def render_report_pdf(context: dict) -> bytes:
    try:
        from weasyprint import HTML  # lazy: native Pango/Cairo load happens here
    except (ImportError, OSError) as exc:
        raise PdfUnavailableError(str(exc)) from exc
    html = render_report_html(context)
    return HTML(string=html).write_pdf()
