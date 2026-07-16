"""M8 PDF report: context assembly, HTML render, HTTP status mapping.

The authoritative native-lib validation is the CI Docker smoke test; here the
actual PDF render runs only when WeasyPrint can load on this host (guarded by
a helper that skips on the recognized import/native-load failures — plain
importorskip misses the OSError a missing Pango raises)."""

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api import reporting as reporting_api
from app.db import Base, get_db
from app.main import app
from app.models import Assessment, Finding, Organization
from app.services import report_pdf, scoring

from tests.conftest import seed_membership

NOW = datetime(2026, 7, 12, 12, 0, 0, tzinfo=timezone.utc)


def _weasyprint_available() -> bool:
    try:
        import weasyprint  # noqa: F401
    except (ImportError, OSError):
        return False
    return True


@pytest.fixture()
def db_session():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(bind=engine)
    TestSession = sessionmaker(bind=engine, expire_on_commit=False)
    db = TestSession()
    yield db
    db.close()


@pytest.fixture()
def client(db_session):
    def override():
        yield db_session

    app.dependency_overrides[get_db] = override
    app.dependency_overrides[reporting_api.get_reporting_db] = override
    yield TestClient(app)
    app.dependency_overrides.clear()


def _seed(db) -> tuple[str, str]:
    org = Organization(name="PDF SA")
    db.add(org)
    db.commit()
    seed_membership(db, org.id)
    a = Assessment(
        organization_id=org.id, corpus_version="1.3.0", status="COMPLETED",
        requirement_ids=["A.9.2", "A.7.4"],
    )
    db.add(a)
    db.commit()
    for rid, verdict in (("A.9.2", "compliant"), ("A.7.4", "non_compliant")):
        db.add(
            Finding(
                assessment_id=a.id, requirement_id=rid, status="VERIFIED",
                verdict=verdict, attempts=1, requirement_fr=f"Texte {rid}",
                review_status="CONFIRMED", review_action="approve",
                human_verdict=verdict, reviewed_at=NOW, review_count=1,
            )
        )
    db.commit()
    return org.id, a.id


def test_context_and_html_render_without_weasyprint(db_session):
    """Assembly + Jinja render need no native libraries at all."""
    org_id, assessment_id = _seed(db_session)
    scope = scoring.build_reporting_scope(db_session, org_id, assessment_id)
    context = report_pdf.build_report_context(scope)
    assert set(context) == {"scope", "conformity", "register", "trust", "soa"}
    html = report_pdf.render_report_html(context)
    assert "Rapport de conformité ISO/IEC 42001" in html
    assert "A.7.4" in html and "invariant structurel" in html
    assert "Déclaration d'applicabilité" in html
    assert context["scope"]["scoring_policy_version"] in html
    # one snapshot everywhere: every section carries the same generated_at
    stamps = {
        context["conformity"]["scope"]["generated_at"],
        context["register"]["scope"]["generated_at"],
        context["trust"]["scope"]["generated_at"],
        context["soa"]["scope"]["generated_at"],
    }
    assert len(stamps) == 1


def test_pdf_unavailable_maps_to_503_only_for_import_failures(client, db_session, monkeypatch):
    org_id, assessment_id = _seed(db_session)

    def unavailable(context):
        raise report_pdf.PdfUnavailableError("libgobject missing")

    monkeypatch.setattr(report_pdf, "render_report_pdf", unavailable)
    r = client.get(
        f"/api/organizations/{org_id}/reporting/report.pdf",
        params={"assessment_id": assessment_id},
    )
    assert r.status_code == 503
    assert "Export PDF indisponible" in r.json()["detail"]

    # a template/render defect is NOT an environment problem: 500, never 503
    def broken(context):
        raise ValueError("template bug")

    monkeypatch.setattr(report_pdf, "render_report_pdf", broken)
    with pytest.raises(ValueError):
        client.get(
            f"/api/organizations/{org_id}/reporting/report.pdf",
            params={"assessment_id": assessment_id},
        )


def test_non_completed_assessment_pdf_is_409_unless_preliminary(client, db_session, monkeypatch):
    org_id, _ = _seed(db_session)
    running = Assessment(
        organization_id=org_id, corpus_version="1.3.0", status="RUNNING",
        requirement_ids=["A.9.2"],
    )
    db_session.add(running)
    db_session.commit()
    r = client.get(
        f"/api/organizations/{org_id}/reporting/report.pdf",
        params={"assessment_id": running.id},
    )
    assert r.status_code == 409
    assert "include_preliminary" in r.json()["detail"]

    rendered: dict = {}

    def fake_render(context):
        rendered.update(context)
        return b"%PDF-fake"

    monkeypatch.setattr(report_pdf, "render_report_pdf", fake_render)
    r = client.get(
        f"/api/organizations/{org_id}/reporting/report.pdf",
        params={"assessment_id": running.id, "include_preliminary": "true"},
    )
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/pdf"
    assert rendered["scope"]["is_preliminary"] is True  # banner data in context


@pytest.mark.skipif(
    not _weasyprint_available(),
    reason="WeasyPrint native libraries unavailable on this host (CI Docker smoke covers it)",
)
def test_real_pdf_render_smoke(client, db_session):
    org_id, assessment_id = _seed(db_session)
    r = client.get(
        f"/api/organizations/{org_id}/reporting/report.pdf",
        params={"assessment_id": assessment_id},
    )
    assert r.status_code == 200
    assert r.content.startswith(b"%PDF")
