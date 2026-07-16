"""M10 auth: signup/login/logout lifecycle, membership enforcement and
cross-org isolation, the invite-by-link flow.

The conftest `bypass_auth` override is removed here (real_auth fixture):
every request in this file goes through the real cookie -> session -> user
resolution and the real membership guards.
"""

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.deps import get_current_user
from app.db import Base, get_db
from app.main import app
from app.models import AuthSession, Invitation, OrganizationMember
from tests.conftest import seed_parsed_document


@pytest.fixture(autouse=True)
def real_auth(bypass_auth):
    # depends on bypass_auth so this runs after it and can undo it
    app.dependency_overrides.pop(get_current_user, None)
    yield


@pytest.fixture()
def client():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(bind=engine)
    TestSession = sessionmaker(bind=engine, expire_on_commit=False)

    def override_get_db():
        db = TestSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    tc = TestClient(app)
    tc.session_factory = TestSession
    yield tc
    app.dependency_overrides.pop(get_db, None)


def _signup(tc, email="alice@lumen.fr", org="Lumen SA", name="Alice"):
    return tc.post(
        "/api/auth/signup",
        json={
            "email": email,
            "password": "correct horse battery",
            "display_name": name,
            "organization_name": org,
        },
    )


def test_signup_creates_org_membership_and_session(client):
    r = _signup(client)
    assert r.status_code == 201
    body = r.json()
    assert body["user"]["email"] == "alice@lumen.fr"
    assert [o["name"] for o in body["organizations"]] == ["Lumen SA"]
    assert "int102_session" in client.cookies

    me = client.get("/api/auth/me")
    assert me.status_code == 200
    assert me.json()["user"]["display_name"] == "Alice"

    # the creator really is a member (guard passes on a scoped route)
    org_id = body["organizations"][0]["id"]
    assert client.get(f"/api/organizations/{org_id}/documents").status_code == 200


def test_signup_rejects_duplicates_and_weak_password(client):
    assert _signup(client).status_code == 201
    # duplicate email (case-insensitive) and duplicate org name
    assert _signup(client, email="ALICE@lumen.fr", org="Autre SA").status_code == 409
    assert _signup(client, email="bob@lumen.fr", org="Lumen SA").status_code == 409
    # policy: too short, then over bcrypt's 72-byte cap
    r = client.post(
        "/api/auth/signup",
        json={
            "email": "c@d.fr",
            "password": "short",
            "display_name": "C",
            "organization_name": "C SA",
        },
    )
    assert r.status_code == 422
    r = client.post(
        "/api/auth/signup",
        json={
            "email": "c@d.fr",
            "password": "x" * 73,
            "display_name": "C",
            "organization_name": "C SA",
        },
    )
    assert r.status_code == 422


def test_login_logout_lifecycle(client):
    _signup(client)
    client.cookies.clear()

    # generic 401 for unknown email AND wrong password (no enumeration)
    r = client.post("/api/auth/login", json={"email": "who@x.fr", "password": "aaaaaaaaaaaa"})
    assert r.status_code == 401
    r = client.post("/api/auth/login", json={"email": "alice@lumen.fr", "password": "wrong password"})
    assert r.status_code == 401
    assert r.json()["detail"] == "Identifiants invalides."

    r = client.post(
        "/api/auth/login", json={"email": "Alice@Lumen.fr", "password": "correct horse battery"}
    )
    assert r.status_code == 200
    assert client.get("/api/auth/me").status_code == 200

    assert client.post("/api/auth/logout").status_code == 204
    assert client.get("/api/auth/me").status_code == 401
    # logout deleted ITS session row (the signup session, whose cookie was
    # cleared client-side but never revoked, legitimately remains)
    with client.session_factory() as db:
        assert len(db.scalars(select(AuthSession)).all()) == 1


def test_expired_session_is_401(client):
    _signup(client)
    with client.session_factory() as db:
        session = db.scalars(select(AuthSession)).one()
        session.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
        db.commit()
    assert client.get("/api/auth/me").status_code == 401


def test_anonymous_requests_are_401(client):
    assert client.get("/api/organizations").status_code == 401
    assert client.post("/api/organizations", json={"name": "X SA"}).status_code == 401
    assert client.get("/api/organizations/some-id/documents").status_code == 401
    assert client.get("/api/kb/requirements").status_code == 401
    assert client.get("/api/health").status_code == 200  # stays public


def test_cross_org_isolation_including_unscoped_document_routes(client):
    org_a = _signup(client).json()["organizations"][0]["id"]
    with client.session_factory() as db:
        doc_a = seed_parsed_document(db, org_a, "p.txt", ["politique IA " * 5]).id

    # second account in its own org
    client.cookies.clear()
    r = _signup(client, email="eve@autre.fr", org="Autre SA", name="Eve")
    org_b = r.json()["organizations"][0]["id"]

    # own org fine, foreign org 404 (never 403 — no existence leak)
    assert client.get(f"/api/organizations/{org_b}/documents").status_code == 200
    for url in (
        f"/api/organizations/{org_a}",
        f"/api/organizations/{org_a}/documents",
        f"/api/organizations/{org_a}/assessments",
        f"/api/organizations/{org_a}/reporting/conformity",
        f"/api/organizations/{org_a}/remediation-cases",
    ):
        assert client.get(url).status_code == 404, url
    # org list never shows the foreign org
    assert [o["id"] for o in client.get("/api/organizations").json()] == [org_b]

    # the org-UNSCOPED document family resolves doc -> org -> membership
    assert client.get(f"/api/documents/{doc_a}/pages").status_code == 404
    assert client.get(f"/api/documents/{doc_a}/versions").status_code == 404
    assert client.delete(f"/api/documents/{doc_a}").status_code == 404
    # the owner still reaches it
    client.cookies.clear()
    client.post(
        "/api/auth/login", json={"email": "alice@lumen.fr", "password": "correct horse battery"}
    )
    assert client.get(f"/api/documents/{doc_a}/pages").status_code == 200


def test_invitation_flow(client):
    org_a = _signup(client).json()["organizations"][0]["id"]

    r = client.post(
        f"/api/organizations/{org_a}/invitations", json={"email": "bob@lumen.fr"}
    )
    assert r.status_code == 201
    token = r.json()["invite_token"]
    # only the hash is stored
    with client.session_factory() as db:
        inv = db.scalars(select(Invitation)).one()
        assert inv.token_hash != token

    # public metadata for the accept page (no cookie needed)
    client.cookies.clear()
    info = client.get(f"/api/auth/invitations/{token}")
    assert info.status_code == 200
    assert info.json() == {
        "organization_name": "Lumen SA",
        "email": "bob@lumen.fr",
        "expired": False,
    }

    r = client.post(
        f"/api/auth/invitations/{token}/accept",
        json={"password": "bob mot de passe", "display_name": "Bob"},
    )
    assert r.status_code == 201
    assert [o["id"] for o in r.json()["organizations"]] == [org_a]
    assert client.get(f"/api/organizations/{org_a}/documents").status_code == 200

    # single-use: the accepted token is dead for info AND accept
    assert client.get(f"/api/auth/invitations/{token}").status_code == 404
    r = client.post(
        f"/api/auth/invitations/{token}/accept",
        json={"password": "encore un essai", "display_name": "Mallory"},
    )
    assert r.status_code == 404

    with client.session_factory() as db:
        assert (
            db.query(OrganizationMember).filter_by(organization_id=org_a).count() == 2
        )


def test_invitation_expiry_and_existing_email(client):
    org_a = _signup(client).json()["organizations"][0]["id"]
    # inviting an already-registered email is rejected upfront
    r = client.post(
        f"/api/organizations/{org_a}/invitations", json={"email": "alice@lumen.fr"}
    )
    assert r.status_code == 409

    r = client.post(
        f"/api/organizations/{org_a}/invitations", json={"email": "late@lumen.fr"}
    )
    token = r.json()["invite_token"]
    with client.session_factory() as db:
        inv = db.scalars(select(Invitation)).one()
        inv.expires_at = datetime.now(timezone.utc) - timedelta(hours=1)
        db.commit()

    client.cookies.clear()
    assert client.get(f"/api/auth/invitations/{token}").json()["expired"] is True
    r = client.post(
        f"/api/auth/invitations/{token}/accept",
        json={"password": "mot de passe valide", "display_name": "Late"},
    )
    assert r.status_code == 410


def test_non_member_cannot_create_invitations(client):
    org_a = _signup(client).json()["organizations"][0]["id"]
    client.cookies.clear()
    _signup(client, email="eve@autre.fr", org="Autre SA", name="Eve")
    r = client.post(
        f"/api/organizations/{org_a}/invitations", json={"email": "x@y.fr"}
    )
    assert r.status_code == 404
