from logging.config import fileConfig
import os
from urllib.parse import urlparse

from sqlalchemy import engine_from_config, pool

from alembic import context
from app.core.config import settings
from app.models import Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)


# ── Explicit environment selector ────────────────────────────────────────────
_VALID_ENVS = {"dev", "test", "prod"}
_alembic_env = os.getenv("ALEMBIC_TARGET_ENV", "dev").lower()
if _alembic_env not in _VALID_ENVS:
    raise RuntimeError(f"ALEMBIC_TARGET_ENV={_alembic_env!r} is not recognised. Must be one of {_VALID_ENVS}.")


def _resolve_url() -> str:
    """Return the database URL for the declared environment, with safety assertions."""
    if _alembic_env == "test":
        url = os.getenv("TEST_DATABASE_URL") or settings.DATABASE_URL
        db_name = urlparse(url).path.lstrip("/")
        if "gait_test" not in db_name.lower():
            raise RuntimeError(
                f"ALEMBIC_TARGET_ENV=test but the resolved database name is {db_name!r}. "
                "The test database name must contain 'gait_test' to prevent "
                "accidental migrations against a non-test database."
            )
        return url

    # dev / prod — use the application DATABASE_URL
    url = settings.DATABASE_URL
    db_name = urlparse(url).path.lstrip("/")
    if "gait_test" in db_name.lower():
        raise RuntimeError(
            f"ALEMBIC_TARGET_ENV={_alembic_env} but the resolved database name is {db_name!r}. "
            "Refusing to run dev/prod migrations against a database whose name "
            "contains 'gait_test'."
        )
    return url


config.set_main_option("sqlalchemy.url", _resolve_url())

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode — emits SQL to stdout."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode — connects to the database."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
