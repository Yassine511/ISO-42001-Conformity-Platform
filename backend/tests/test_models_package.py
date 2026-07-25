"""Guards on the app.models PACKAGE boundary (split out of one 2 000-line file).

The split's whole risk is silence: a submodule nobody imports, or a class
nobody re-exports, produces no error — it just quietly disappears from
Base.metadata (so create_all stops creating the table) or from
`from app.models import X` (so the caller gets an ImportError only on the code
path that happens to need it). These tests make both failures loud.
"""

import importlib
import pkgutil

from sqlalchemy.orm import DeclarativeBase

from app import models
from app.db import Base


def _submodules() -> list[str]:
    return [f"app.models.{m.name}" for m in pkgutil.iter_modules(models.__path__)]


def test_every_submodule_is_imported_by_the_package():
    """Importing `app.models` must pull in every submodule. Alembic's env.py
    populates Base.metadata with nothing but `from app import models`; a
    submodule missing from __init__ would take its tables with it."""
    for name in _submodules():
        assert name in importlib.sys.modules, (
            f"{name} is not imported by app/models/__init__.py — its tables are "
            "absent from Base.metadata"
        )


def test_every_model_class_is_re_exported():
    """`from app.models import X` must keep working for every model, which is
    what lets the ~40 call sites stay unchanged."""
    missing = []
    for name in _submodules():
        module = importlib.import_module(name)
        for attr, value in vars(module).items():
            if attr.startswith("_") or not isinstance(value, type):
                continue
            if not issubclass(value, DeclarativeBase) or value is Base:
                continue
            if value.__module__ != name:
                continue  # imported from a sibling, exported by its own module
            if getattr(models, attr, None) is not value:
                missing.append(f"{attr} ({name})")
    assert not missing, "not re-exported from app.models: " + ", ".join(sorted(missing))


def test_declared_table_set_is_the_expected_33():
    """A blunt count, on purpose: it fails loudly if a split, a merge or a new
    model changes the schema surface without anyone saying so."""
    assert len(Base.metadata.tables) == 33, sorted(Base.metadata.tables)


def test_all_lists_only_real_attributes():
    for name in models.__all__:
        assert hasattr(models, name), f"__all__ names {name}, which does not exist"
