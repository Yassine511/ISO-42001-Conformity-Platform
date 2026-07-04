from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Organization
from app.schemas import OrganizationCreate, OrganizationOut

router = APIRouter(prefix="/api/organizations", tags=["organizations"])


@router.post("", response_model=OrganizationOut, status_code=201)
def create_organization(payload: OrganizationCreate, db: Session = Depends(get_db)):
    existing = db.scalar(select(Organization).where(Organization.name == payload.name))
    if existing:
        raise HTTPException(409, "Une organisation portant ce nom existe déjà.")
    org = Organization(name=payload.name)
    db.add(org)
    try:
        db.commit()
    except IntegrityError:
        # Concurrent create slipped past the pre-check; the UNIQUE(name)
        # constraint is the atomic gate (mirrors documents upload).
        db.rollback()
        raise HTTPException(409, "Une organisation portant ce nom existe déjà.")
    return org


@router.get("", response_model=list[OrganizationOut])
def list_organizations(db: Session = Depends(get_db)):
    return db.scalars(select(Organization).order_by(Organization.created_at)).all()


@router.get("/{org_id}", response_model=OrganizationOut)
def get_organization(org_id: str, db: Session = Depends(get_db)):
    org = db.get(Organization, org_id)
    if not org:
        raise HTTPException(404, "Organisation introuvable.")
    return org
