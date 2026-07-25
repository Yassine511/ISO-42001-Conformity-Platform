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
from app.models import AuthSession, Invitation, OrganizationMember, User
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


def test_expired_session_is_401_and_the_row_is_pruned(client):
    _signup(client)
    with client.session_factory() as db:
        session = db.scalars(select(AuthSession)).one()
        session.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
        db.commit()
    assert client.get("/api/auth/me").status_code == 401
    # presenting an expired token deletes it: no cron job prunes these
    with client.session_factory() as db:
        assert db.scalars(select(AuthSession)).all() == []


def test_login_prunes_expired_sessions_but_never_live_ones(client):
    """The pruning sweep at login is scoped to EXPIRED rows. If it ever widened,
    every other device of that user would be silently logged out."""
    _signup(client)
    live_token = client.cookies["int102_session"]
    with client.session_factory() as db:
        live = db.scalars(select(AuthSession)).one()
        # a second, already-expired session for the same user (an old device)
        db.add(
            AuthSession(
                user_id=live.user_id,
                token_hash="dead" * 16,
                expires_at=datetime.now(timezone.utc) - timedelta(days=1),
            )
        )
        db.commit()

    client.cookies.clear()
    assert client.post(
        "/api/auth/login",
        json={"email": "alice@lumen.fr", "password": "correct horse battery"},
    ).status_code == 200

    with client.session_factory() as db:
        hashes = {s.token_hash for s in db.scalars(select(AuthSession))}
    assert "dead" * 16 not in hashes  # expired row swept
    # the pre-existing LIVE session still authenticates
    client.cookies.clear()
    client.cookies.set("int102_session", live_token)
    assert client.get("/api/auth/me").status_code == 200


def test_unknown_email_login_still_pays_the_bcrypt_cost(client, monkeypatch):
    """§1.5: skipping the hash comparison when the address is unknown makes the
    identical 401 answer ~100x faster — an account-enumeration timing oracle."""
    from app.services import auth as auth_service

    calls = []
    monkeypatch.setattr(
        auth_service, "waste_password_comparison", lambda: calls.append(1)
    )
    r = client.post(
        "/api/auth/login", json={"email": "nobody@x.fr", "password": "aaaaaaaaaaaa"}
    )
    assert r.status_code == 401 and calls == [1]


def test_login_is_throttled_and_a_success_clears_the_window(client):
    """Bounds online guessing and the enumeration oracle. The window must also
    be forgiving: a correct password forgets the failures before it."""
    from app.services.rate_limit import LOGIN_MAX_ATTEMPTS

    _signup(client)
    client.cookies.clear()
    bad = {"email": "alice@lumen.fr", "password": "wrong password"}
    for _ in range(LOGIN_MAX_ATTEMPTS):
        assert client.post("/api/auth/login", json=bad).status_code == 401
    r = client.post("/api/auth/login", json=bad)
    assert r.status_code == 429 and "Retry-After" in r.headers
    # the CORRECT password is refused too while the window is open — otherwise
    # the throttle would be trivially bypassed by the attacker who guesses right
    assert client.post(
        "/api/auth/login",
        json={"email": "alice@lumen.fr", "password": "correct horse battery"},
    ).status_code == 429


def test_login_success_resets_the_window(client):
    from app.services.rate_limit import LOGIN_MAX_ATTEMPTS

    _signup(client)
    client.cookies.clear()
    bad = {"email": "alice@lumen.fr", "password": "wrong password"}
    for _ in range(LOGIN_MAX_ATTEMPTS - 1):
        assert client.post("/api/auth/login", json=bad).status_code == 401
    assert client.post(
        "/api/auth/login",
        json={"email": "alice@lumen.fr", "password": "correct horse battery"},
    ).status_code == 200
    # window forgotten: the next wrong password is a plain 401, not a 429
    assert client.post("/api/auth/login", json=bad).status_code == 401


def test_signup_enumeration_probing_is_throttled(client):
    """The 409 «address already taken» is structural (no e-mail server), so the
    mitigation is bounding how often it can be asked, not hiding it."""
    from app.services.rate_limit import SIGNUP_MAX_ATTEMPTS

    _signup(client)
    client.cookies.clear()
    probe = {
        "email": "alice@lumen.fr",
        "password": "correct horse battery",
        "display_name": "X",
        "organization_name": "X SA",
    }
    # the successful _signup above already spent one attempt on this address
    seen = [
        client.post("/api/auth/signup", json=probe).status_code
        for _ in range(SIGNUP_MAX_ATTEMPTS - 1)
    ]
    assert set(seen) == {409}  # still discloses, deliberately
    assert client.post("/api/auth/signup", json=probe).status_code == 429


def test_invite_accept_password_branch_is_throttled(client):
    """The invitation survives a wrong password (by design), so that branch is
    an unlimited guessing surface for the address it names unless throttled."""
    from app.services.rate_limit import LOGIN_MAX_ATTEMPTS

    org_id = _signup(client).json()["organizations"][0]["id"]
    token = client.post(
        f"/api/organizations/{org_id}/invitations", json={"email": "bob@lumen.fr"}
    ).json()["invite_token"]
    # bob already has an account elsewhere -> accept authenticates it
    client.cookies.clear()
    _signup(client, email="bob@lumen.fr", org="Bob SA", name="Bob")
    client.cookies.clear()

    bad = {"password": "not bobs password"}
    for _ in range(LOGIN_MAX_ATTEMPTS):
        assert client.post(f"/api/auth/invitations/{token}/accept", json=bad).status_code == 401
    assert client.post(f"/api/auth/invitations/{token}/accept", json=bad).status_code == 429
    # refused without consuming the single-use invitation
    with client.session_factory() as db:
        assert db.scalars(select(Invitation)).one().accepted_at is None


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
        "account_exists": False,
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


def test_invitation_expiry_and_duplicate_guards(client):
    org_a = _signup(client).json()["organizations"][0]["id"]
    # inviting an existing MEMBER is pointless — rejected upfront
    r = client.post(
        f"/api/organizations/{org_a}/invitations", json={"email": "alice@lumen.fr"}
    )
    assert r.status_code == 409
    assert "déjà membre" in r.json()["detail"]

    # a second live invitation for one address would survive revoking the first
    client.post(f"/api/organizations/{org_a}/invitations", json={"email": "dup@lumen.fr"})
    r = client.post(
        f"/api/organizations/{org_a}/invitations", json={"email": "dup@lumen.fr"}
    )
    assert r.status_code == 409 and "déjà en cours" in r.json()["detail"]

    r = client.post(
        f"/api/organizations/{org_a}/invitations", json={"email": "late@lumen.fr"}
    )
    token = r.json()["invite_token"]
    with client.session_factory() as db:
        inv = db.scalars(
            select(Invitation).where(Invitation.email == "late@lumen.fr")
        ).one()
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


# ---------------------------------------------- existing user joins a 2nd org


def _invite(tc, org_id, email):
    r = tc.post(f"/api/organizations/{org_id}/invitations", json={"email": email})
    assert r.status_code == 201, r.text
    return r.json()["invite_token"]


def test_existing_user_joins_a_second_organization(client):
    """The gap this closes: before, an address with an account could not be
    invited at all, so multi-org membership was unreachable over HTTP."""
    org_a = _signup(client).json()["organizations"][0]["id"]

    # Bob already has his own account and org
    client.cookies.clear()
    org_b = _signup(client, email="bob@lumen.fr", org="Bob SA", name="Bob").json()[
        "organizations"
    ][0]["id"]

    # Alice invites Bob's existing address — now allowed
    client.cookies.clear()
    client.post(
        "/api/auth/login",
        json={"email": "alice@lumen.fr", "password": "correct horse battery"},
    )
    token = _invite(client, org_a, "bob@lumen.fr")

    # the accept page is told an account exists, so it renders "sign in to join"
    client.cookies.clear()
    info = client.get(f"/api/auth/invitations/{token}").json()
    assert info["account_exists"] is True

    # wrong password: 401 AND the invitation is NOT consumed
    r = client.post(
        f"/api/auth/invitations/{token}/accept", json={"password": "pas le bon"}
    )
    assert r.status_code == 401
    assert client.get(f"/api/auth/invitations/{token}").status_code == 200
    with client.session_factory() as db:
        assert db.scalars(select(Invitation)).one().accepted_at is None

    # correct password authenticates the EXISTING account and adds membership
    r = client.post(
        f"/api/auth/invitations/{token}/accept",
        json={"password": "correct horse battery"},
    )
    assert r.status_code == 201
    body = r.json()
    assert body["user"]["display_name"] == "Bob"  # kept, not overwritten
    assert sorted(o["id"] for o in body["organizations"]) == sorted([org_a, org_b])

    # Bob now really reaches Alice's org, and no second account was created
    assert client.get(f"/api/organizations/{org_a}/documents").status_code == 200
    with client.session_factory() as db:
        assert db.query(User).filter_by(email="bob@lumen.fr").count() == 1


def test_new_account_path_still_requires_a_display_name(client):
    org_a = _signup(client).json()["organizations"][0]["id"]
    token = _invite(client, org_a, "carol@lumen.fr")
    client.cookies.clear()
    assert client.get(f"/api/auth/invitations/{token}").json()["account_exists"] is False
    r = client.post(
        f"/api/auth/invitations/{token}/accept", json={"password": "mot de passe long"}
    )
    assert r.status_code == 422


# --------------------------------------------------------- member management


def test_members_listing_and_removal(client):
    org_a = _signup(client).json()["organizations"][0]["id"]
    token = _invite(client, org_a, "bob@lumen.fr")
    client.cookies.clear()
    bob = client.post(
        f"/api/auth/invitations/{token}/accept",
        json={"password": "bob mot de passe", "display_name": "Bob"},
    ).json()["user"]["id"]

    members = client.get(f"/api/organizations/{org_a}/members").json()
    assert [m["email"] for m in members] == ["alice@lumen.fr", "bob@lumen.fr"]
    assert [m["is_self"] for m in members] == [False, True]  # Bob is the caller

    # Bob leaves (any member may remove any member — no roles by design)
    assert client.delete(f"/api/organizations/{org_a}/members/{bob}").status_code == 204
    # access ends on the very next request; no session revocation needed
    assert client.get(f"/api/organizations/{org_a}/documents").status_code == 404
    assert client.delete(f"/api/organizations/{org_a}/members/{bob}").status_code == 404


def test_last_member_cannot_be_removed(client):
    body = _signup(client).json()
    org_a, alice = body["organizations"][0]["id"], body["user"]["id"]
    r = client.delete(f"/api/organizations/{org_a}/members/{alice}")
    assert r.status_code == 409
    assert "dernier membre" in r.json()["detail"]
    assert client.get(f"/api/organizations/{org_a}/documents").status_code == 200


def test_pending_invitations_are_listable_and_revocable(client):
    org_a = _signup(client).json()["organizations"][0]["id"]
    token = _invite(client, org_a, "bob@lumen.fr")

    pending = client.get(f"/api/organizations/{org_a}/invitations").json()
    assert [p["email"] for p in pending] == ["bob@lumen.fr"]
    assert "invite_token" not in pending[0]  # the raw token is unrecoverable
    invitation_id = pending[0]["id"]

    assert (
        client.delete(f"/api/organizations/{org_a}/invitations/{invitation_id}").status_code
        == 204
    )
    # the link is dead immediately, and revoking frees the address to be re-invited
    client.cookies.clear()
    assert client.get(f"/api/auth/invitations/{token}").status_code == 404
    client.post(
        "/api/auth/login",
        json={"email": "alice@lumen.fr", "password": "correct horse battery"},
    )
    assert client.get(f"/api/organizations/{org_a}/invitations").json() == []
    _invite(client, org_a, "bob@lumen.fr")


def test_accepted_invitations_are_not_deletable(client):
    org_a = _signup(client).json()["organizations"][0]["id"]
    token = _invite(client, org_a, "bob@lumen.fr")
    invitation_id = client.get(f"/api/organizations/{org_a}/invitations").json()[0]["id"]
    client.cookies.clear()
    client.post(
        f"/api/auth/invitations/{token}/accept",
        json={"password": "bob mot de passe", "display_name": "Bob"},
    )
    # the record of how Bob got access is not erasable, and it left the list
    assert (
        client.delete(f"/api/organizations/{org_a}/invitations/{invitation_id}").status_code
        == 404
    )
    assert client.get(f"/api/organizations/{org_a}/invitations").json() == []


def test_member_routes_are_org_scoped(client):
    body = _signup(client).json()
    org_a, alice = body["organizations"][0]["id"], body["user"]["id"]
    client.cookies.clear()
    _signup(client, email="eve@autre.fr", org="Autre SA", name="Eve")
    assert client.get(f"/api/organizations/{org_a}/members").status_code == 404
    assert client.get(f"/api/organizations/{org_a}/invitations").status_code == 404
    assert client.delete(f"/api/organizations/{org_a}/members/{alice}").status_code == 404


def test_non_ascii_token_candidates_never_500(client):
    """Audit pass 5 (F1): the session cookie and the invitation path token are
    attacker-controlled strings, not guaranteed ASCII (Starlette decodes
    headers as latin-1 and percent-decodes paths as UTF-8). `_hash_token` used
    `.encode("ascii")`, so any byte >= 0x7F raised an unhandled
    UnicodeEncodeError: every authenticated route AND both unauthenticated
    invitation routes answered 500 instead of 401/404."""
    org = _signup(client).json()["organizations"][0]["id"]
    client.cookies.clear()

    # raw latin-1 byte in the cookie -> unauthenticated, never a crash
    bad_cookie = {b"Cookie": b"int102_session=caf\xe9"}
    for method, path in (
        ("GET", "/api/auth/me"),
        ("GET", "/api/organizations"),
        ("GET", "/api/kb/requirements"),
        ("GET", f"/api/organizations/{org}/documents"),
    ):
        assert client.request(method, path, headers=bad_cookie).status_code == 401, path
    # logout is idempotent and must not crash on an unusable cookie either
    assert client.post("/api/auth/logout", headers=bad_cookie).status_code == 204

    # non-ASCII invitation token (percent-encoded UTF-8) -> plain 404
    assert client.get("/api/auth/invitations/caf%C3%A9").status_code == 404
    assert (
        client.post(
            "/api/auth/invitations/caf%C3%A9/accept",
            json={"password": "un mot de passe", "display_name": "X"},
        ).status_code
        == 404
    )


def test_ascii_token_hashes_are_unchanged_by_the_utf8_fix(client):
    """The F1 fix switched _hash_token to UTF-8. Every token we mint is
    `secrets.token_urlsafe` (ASCII), for which UTF-8 and ASCII encode
    identically — so no already-stored session or invitation hash moved."""
    import hashlib

    from app.services import auth as auth_service

    for sample in ("abc123", "aGVsbG8td29ybGQ", "-_" * 20):
        assert (
            auth_service._hash_token(sample)
            == hashlib.sha256(sample.encode("ascii")).hexdigest()
        )

    # and a live session still resolves after the change
    body = _signup(client, email="carol@lumen.fr", org="Carol SA", name="Carol").json()
    assert client.get("/api/auth/me").json()["user"]["id"] == body["user"]["id"]
