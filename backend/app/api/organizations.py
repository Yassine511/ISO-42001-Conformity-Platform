from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_org_member
from app.db import get_db
from app.models import Organization, OrganizationMember, User
from app.schemas import OrganizationCreate, OrganizationOut
from app.services import auth as auth_service

router = APIRouter(prefix="/api/organizations", tags=["organizations"])


@router.post("", response_model=OrganizationOut, status_code=201)
def create_organization(
    payload: OrganizationCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    existing = db.scalar(select(Organization).where(Organization.name == payload.name))
    if existing:
        raise HTTPException(409, "Une organisation portant ce nom existe déjà.")
    org = Organization(name=payload.name)
    db.add(org)
    db.flush()
    # the creator is always a member — this is also what lets every API test
    # that creates its org through this endpoint pass the membership guard
    db.add(OrganizationMember(organization_id=org.id, user_id=user.id))
    try:
        db.commit()
    except IntegrityError:
        # Concurrent create slipped past the pre-check; the UNIQUE(name)
        # constraint is the atomic gate (mirrors documents upload).
        db.rollback()
        raise HTTPException(409, "Une organisation portant ce nom existe déjà.")
    return org


@router.get("", response_model=list[OrganizationOut])
def list_organizations(
    user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    # only the caller's organizations — there is no global listing anymore
    return auth_service.user_organizations(db, user.id)


@router.get("/{org_id}", response_model=OrganizationOut)
def get_organization(
    org_id: str,
    user: User = Depends(require_org_member),
    db: Session = Depends(get_db),
):
    org = db.get(Organization, org_id)
    if not org:
        raise HTTPException(404, "Organisation introuvable.")
    return org
