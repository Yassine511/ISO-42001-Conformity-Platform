"""Imports and helpers shared by every model module.

Split note: the model layer was one 2 000-line file. It is now a package whose
submodules are imported ONLY by app/models/__init__.py, which re-exports
everything — `from app.models import X` keeps working unchanged for every
caller, and alembic/env.py still populates Base.metadata with a single
`from app import models`. That indirection is the point: a submodule nobody
imports would silently drop its tables from the metadata, and the SQLite test
path (create_all) would quietly stop creating them.
"""

import uuid
from datetime import date, datetime, timezone
from enum import Enum

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base

__all__ = [
    "JSON", "Base", "Boolean", "CheckConstraint", "Date", "DateTime", "Enum",
    "Float", "ForeignKey", "ForeignKeyConstraint", "Index", "Integer",
    "Mapped", "String", "Text", "UniqueConstraint", "date", "datetime",
    "mapped_column", "relationship", "text", "timezone", "uuid",
    "_now", "_uuid",
]


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(timezone.utc)
