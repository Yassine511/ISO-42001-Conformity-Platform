"""M10 auth endpoints — signup (creates the organization), login, logout,
me, and the invite-by-link flow.

Cookie contract: `int102_session`, httpOnly, SameSite=Lax (a cross-site POST
never carries it — the CSRF mitigation for this same-origin deployment),
Secure per settings. The value is the raw opaque token; the DB knows only
its sha256 (services/auth.py).
"""

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import SESSION_COOKIE, get_current_user, require_org_member
from app.config import settings
from app.db import get_db
from app.models import Organization, OrganizationMember, User
from app.schemas import (
    InvitationAcceptIn,
    InvitationCreatedOut,
    InvitationCreateIn,
    InvitationPublicOut,
    LoginIn,
    SessionOut,
    SignupIn,
)
from app.services import auth as auth_service

router = APIRouter(prefix="/api/auth", tags=["auth"])

# Org-scoped invite creation lives with the other /api/organizations/{org_id}
# routes so the membership guard applies the same way.
org_router = APIRouter(
    prefix="/api/organizations/{org_id}",
    tags=["auth"],
    dependencies=[Depends(require_org_member)],
)


def _validate_password(password: str) -> None:
    if len(password) < auth_service.MIN_PASSWORD_LENGTH:
        raise HTTPException(
            422,
            f"Le mot de passe doit contenir au moins {auth_service.MIN_PASSWORD_LENGTH} caractères.",
        )
    if len(password.encode("utf-8")) > auth_service.MAX_PASSWORD_BYTES:
        raise HTTPException(422, "Le mot de passe est trop long (72 octets maximum).")


def _set_session_cookie(response: Response, raw_token: str) -> None:
    response.set_cookie(
        SESSION_COOKIE,
        raw_token,
        max_age=settings.session_ttl_hours * 3600,
        httponly=True,
        samesite="lax",
        secure=settings.session_cookie_secure,
        path="/",
    )


def _session_body(db: Session, user: User) -> SessionOut:
    return SessionOut.model_validate(
        {
            "user": user,
            "organizations": auth_service.user_organizations(db, user.id),
        },
        from_attributes=True,
    )


@router.post("/signup", response_model=SessionOut, status_code=201)
def signup(payload: SignupIn, response: Response, db: Session = Depends(get_db)):
    _validate_password(payload.password)
    email = auth_service.normalize_email(payload.email)
    if "@" not in email:
        raise HTTPException(422, "Adresse e-mail invalide.")
    if auth_service.get_user_by_email(db, email):
        raise HTTPException(409, "Un compte existe déjà avec cette adresse e-mail.")
    existing_org = db.query(Organization).filter_by(name=payload.organization_name).first()
    if existing_org:
        raise HTTPException(409, "Une organisation portant ce nom existe déjà.")

    user = User(
        email=email,
        password_hash=auth_service.hash_password(payload.password),
        display_name=payload.display_name,
    )
    org = Organization(name=payload.organization_name)
    db.add_all([user, org])
    db.flush()
    db.add(OrganizationMember(organization_id=org.id, user_id=user.id))
    raw_token = auth_service.create_session(db, user)
    try:
        db.commit()
    except IntegrityError:
        # concurrent duplicate slipped past the pre-checks; the UNIQUE
        # constraints (users.email, organizations.name) are the atomic gate
        db.rollback()
        raise HTTPException(409, "Adresse e-mail ou nom d'organisation déjà utilisés.")
    _set_session_cookie(response, raw_token)
    return _session_body(db, user)


@router.post("/login", response_model=SessionOut)
def login(payload: LoginIn, response: Response, db: Session = Depends(get_db)):
    user = auth_service.get_user_by_email(db, payload.email)
    # generic message for unknown email AND wrong password — no enumeration
    if user is None or not auth_service.verify_password(payload.password, user.password_hash):
        raise HTTPException(401, "Identifiants invalides.")
    raw_token = auth_service.create_session(db, user)
    db.commit()
    _set_session_cookie(response, raw_token)
    return _session_body(db, user)


@router.post("/logout", status_code=204)
def logout(request: Request, response: Response, db: Session = Depends(get_db)):
    raw_token = request.cookies.get(SESSION_COOKIE)
    if raw_token:
        auth_service.revoke_session(db, raw_token)
        db.commit()
    response.delete_cookie(SESSION_COOKIE, path="/")


@router.get("/me", response_model=SessionOut)
def me(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return _session_body(db, user)


@router.get("/invitations/{token}", response_model=InvitationPublicOut)
def invitation_info(token: str, db: Session = Depends(get_db)):
    """Public metadata for the accept page. Looked up by hash; an unknown or
    already-accepted token is a plain 404."""
    invitation = auth_service.get_invitation_by_token(db, token)
    if invitation is None or invitation.accepted_at is not None:
        raise HTTPException(404, "Invitation introuvable ou déjà utilisée.")
    org = db.get(Organization, invitation.organization_id)
    return InvitationPublicOut(
        organization_name=org.name if org else "",
        email=invitation.email,
        expired=auth_service.invitation_expired(invitation),
    )


@router.post("/invitations/{token}/accept", response_model=SessionOut, status_code=201)
def accept_invitation(
    token: str,
    payload: InvitationAcceptIn,
    response: Response,
    db: Session = Depends(get_db),
):
    invitation = auth_service.get_invitation_by_token(db, token)
    if invitation is None or invitation.accepted_at is not None:
        raise HTTPException(404, "Invitation introuvable ou déjà utilisée.")
    if auth_service.invitation_expired(invitation):
        raise HTTPException(410, "Cette invitation a expiré.")
    _validate_password(payload.password)
    if auth_service.get_user_by_email(db, invitation.email):
        raise HTTPException(409, "Un compte existe déjà avec cette adresse e-mail.")

    user = User(
        email=invitation.email,
        password_hash=auth_service.hash_password(payload.password),
        display_name=payload.display_name,
    )
    db.add(user)
    db.flush()
    db.add(
        OrganizationMember(organization_id=invitation.organization_id, user_id=user.id)
    )
    invitation.accepted_at = auth_service._now()
    invitation.accepted_by_user_id = user.id
    raw_token = auth_service.create_session(db, user)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Un compte existe déjà avec cette adresse e-mail.")
    _set_session_cookie(response, raw_token)
    return _session_body(db, user)


@org_router.post("/invitations", response_model=InvitationCreatedOut, status_code=201)
def create_invitation(
    org_id: str,
    payload: InvitationCreateIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    email = auth_service.normalize_email(payload.email)
    if "@" not in email:
        raise HTTPException(422, "Adresse e-mail invalide.")
    if auth_service.get_user_by_email(db, email):
        raise HTTPException(409, "Un compte existe déjà avec cette adresse e-mail.")
    invitation, raw_token = auth_service.create_invitation(db, org_id, email, user)
    db.commit()
    return InvitationCreatedOut(
        invite_token=raw_token, email=invitation.email, expires_at=invitation.expires_at
    )
