from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from app import models  # noqa: F401 — register tables on Base metadata
from app.config import settings
from app.db import Base

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Single source of truth for the URL: application settings.
config.set_main_option("sqlalchemy.url", settings.database_url)

target_metadata = Base.metadata

# LangGraph's PostgresSaver owns these tables (created by .setup(), versioned
# by the library): autogenerate must never propose dropping them.
LANGGRAPH_TABLES = {
    "checkpoints",
    "checkpoint_blobs",
    "checkpoint_writes",
    "checkpoint_migrations",
}


def include_object(obj, name, type_, reflected, compare_to) -> bool:
    if type_ == "table" and name in LANGGRAPH_TABLES:
        return False
    if type_ == "index" and getattr(obj, "table", None) is not None:
        return obj.table.name not in LANGGRAPH_TABLES
    return True


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        include_object=include_object,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            include_object=include_object,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
