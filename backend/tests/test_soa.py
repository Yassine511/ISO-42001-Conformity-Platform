"""M8 Statement of Applicability: 38-per-control rows, append-only decisions."""

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api import reporting as reporting_api
from app.db import Base, get_db
from app.main import app
from app.models import Assessment, Finding, Organization, SoaControl, SoaDecision
from app.services import scoring
from app.services import soa as soa_service

from tests.conftest import seed_membership

NOW = datetime(2026, 7, 12, 12, 0, 0, tzinfo=timezone.utc)


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


_ORG_SEQ = iter(range(1, 100))


def _org(db) -> str:
    org = Organization(name=f"SoA SA {next(_ORG_SEQ)}")
    db.add(org)
    db.commit()
    seed_membership(db, org.id)
    return org.id


def test_soa_generates_38_control_rows_from_kb(client, db_session):
    org = _org(db_session)
    r = client.get(f"/api/organizations/{org}/reporting/soa")
    assert r.status_code == 200
    body = r.json()
    controls = body["controls"]
    assert len(controls) == 38
    ids = [c["control_id"] for c in controls]
    assert ids[0] == "A.2.2" and ids[-1] == "A.10.4"
    assert all(c["applicable"] and c["is_default"] for c in controls)
    assert all(c["status"] == "non_evalue" for c in controls)
    # holdout posture: no requirement text without a finding snapshot
    assert all(c["requirement_fr"] is None for c in controls)
    assert body["applicability_scope"] == "organization_current"
    assert len(body["domains"]) == 9


def test_soa_status_from_exact_requirement_and_annotate_not_filter(client, db_session):
    org = _org(db_session)
    a = Assessment(
        organization_id=org, corpus_version="1.3.0", status="COMPLETED",
        requirement_ids=["A.9.2", "A.9.4"],
    )
    db_session.add(a)
    db_session.commit()
    for rid, verdict in (("A.9.2", "compliant"), ("A.9.4", "partial")):
        db_session.add(
            Finding(
                assessment_id=a.id, requirement_id=rid, status="VERIFIED",
                verdict=verdict, attempts=1, requirement_fr=f"Texte {rid}",
                review_status="CONFIRMED", review_action="approve",
                human_verdict=verdict, reviewed_at=NOW, review_count=1,
            )
        )
    db_session.commit()
    # mark the GAP control non-applicable: it must stay in risk outputs
    client.put(
        f"/api/organizations/{org}/reporting/soa/A.9.4",
        json={"applicable": False, "justification_fr": "Hors périmètre produit."},
    )

    body = client.get(f"/api/organizations/{org}/reporting/soa").json()
    by_id = {c["control_id"]: c for c in body["controls"]}
    assert by_id["A.9.2"]["status"] == "conforme"
    assert by_id["A.9.4"]["status"] == "ecart"  # status untouched by applicability
    assert by_id["A.9.4"]["applicable"] is False
    assert by_id["A.9.2"]["requirement_fr"] == "Texte A.9.2"  # snapshot text
    assert by_id["A.9.3"]["status"] == "non_evalue"
    # annotate-not-filter: the register still carries the A.9.4 gap
    register = client.get(f"/api/organizations/{org}/reporting/risk-register").json()
    assert [r["requirement_id"] for r in register["rows"]] == ["A.9.4"]


def test_soa_decision_history_is_append_only(client, db_session):
    org = _org(db_session)
    r1 = client.put(
        f"/api/organizations/{org}/reporting/soa/A.2.2",
        json={"applicable": False, "justification_fr": "Non applicable.", "editor_label": "Yas"},
    )
    assert r1.status_code == 200 and r1.json()["decision_count"] == 1
    r2 = client.put(
        f"/api/organizations/{org}/reporting/soa/A.2.2",
        json={"applicable": True, "justification_fr": "Finalement applicable."},
    )
    assert r2.json()["decision_count"] == 2 and r2.json()["applicable"] is True
    history = client.get(f"/api/organizations/{org}/reporting/soa/A.2.2/history").json()
    assert [h["sequence"] for h in history] == [1, 2]
    assert history[0]["applicable"] is False and history[1]["applicable"] is True
    # projection matches the latest decision
    proj = db_session.scalar(select(SoaControl).where(SoaControl.organization_id == org))
    assert proj.applicable is True and proj.decision_count == 2
    assert db_session.scalars(select(SoaDecision)).all().__len__() == 2


def test_soa_validation_and_isolation(client, db_session):
    org = _org(db_session)
    # justification required
    r = client.put(
        f"/api/organizations/{org}/reporting/soa/A.2.2",
        json={"applicable": False, "justification_fr": "  "},
    )
    assert r.status_code == 422
    # unknown control (incl. a clause 4-10 id: SoA is Annex A only)
    for bad in ("A.99.9", "6.1.2"):
        r = client.put(
            f"/api/organizations/{org}/reporting/soa/{bad}",
            json={"applicable": False, "justification_fr": "x"},
        )
        assert r.status_code == 404
    # unknown org
    r = client.put(
        "/api/organizations/nope/reporting/soa/A.2.2",
        json={"applicable": False, "justification_fr": "x"},
    )
    assert r.status_code == 404
    # cross-org: a decision in org A never leaks into org B
    client.put(
        f"/api/organizations/{org}/reporting/soa/A.2.2",
        json={"applicable": False, "justification_fr": "org A"},
    )
    other = _org(db_session)
    body = client.get(f"/api/organizations/{other}/reporting/soa").json()
    a22 = next(c for c in body["controls"] if c["control_id"] == "A.2.2")
    assert a22["applicable"] is True and a22["is_default"]
