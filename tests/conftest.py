import os

from alembic.config import Config
from httpx import ASGITransport, AsyncClient
import pytest
import pytest_asyncio
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import NullPool

from alembic import command
from app.core.database import get_db
from app.core.security import create_access_token, hash_password
from app.main import app
from app.models.orm import User

_test_db_url = os.getenv("TEST_DATABASE_URL")
if not _test_db_url or "gait_test" not in _test_db_url.lower():
    pytest.exit(
        "CRITICAL ERROR: 'TEST_DATABASE_URL' is missing or does not contain the word 'gait_test'. "
        "Running tests against a production or dev database is strictly prohibited to prevent data loss."
    )
_engine = create_engine(_test_db_url, poolclass=NullPool)

# Reusable constants for test users
TEST_PASSWORD: str = "secureP@ss123"  # noqa: S105
CARETAKER_USERNAME: str = "caretaker_jane"
PATIENT_USERNAME: str = "patient_john"


# ── Schema lifecycle (once per session, via Alembic) ─────────────────────────
@pytest.fixture(scope="session")
def _apply_migrations():
    # Run the real migration chain so tests validate the same schema path as production.
    os.environ["ALEMBIC_TARGET_ENV"] = "test"
    cfg = Config("alembic.ini")
    command.upgrade(cfg, "head")
    yield
    command.downgrade(cfg, "base")


# ── Per-test transactional isolation ─────────────────────────────────────────
@pytest.fixture()
def db_session(_apply_migrations):
    # Every test runs inside an outer transaction that is rolled back at the end.
    # The test thread and the FastAPI threadpool each get their own Session
    # to avoid cross-thread Session sharing, but both are bound to the same
    # connection/transaction so the rollback reverts all changes.
    connection = _engine.connect()
    transaction = connection.begin()

    # Override: each request gets a fresh Session on the shared connection.
    def _override_get_db():
        req_session = Session(bind=connection, join_transaction_mode="create_savepoint")
        try:
            yield req_session
        finally:
            req_session.close()

    app.dependency_overrides[get_db] = _override_get_db

    # Separate session for test-side setup and assertions.
    session = Session(bind=connection, join_transaction_mode="create_savepoint")

    yield session

    session.close()
    transaction.rollback()
    connection.close()
    app.dependency_overrides.pop(get_db, None)


# ── User factories ───────────────────────────────────────────────────────────
# These create persisted users with known credentials, so we can test authentication and role-based access control.
@pytest.fixture()
def test_user(db_session: Session) -> User:
    # A persisted caretaker user with a known password.
    user = User(
        username=CARETAKER_USERNAME,
        hashed_password=hash_password(TEST_PASSWORD),
        role="caretaker",
    )
    db_session.add(user)
    db_session.flush()
    return user


@pytest.fixture()
def patient_user(db_session: Session) -> User:

    # A persisted patient user with a known password.
    user = User(
        username=PATIENT_USERNAME,
        hashed_password=hash_password(TEST_PASSWORD),
        role="patient",
    )
    db_session.add(user)
    db_session.flush()
    return user


# ── Auth helper ──────────────────────────────────────────────────────────────
def _bearer_headers(user: User) -> dict[str, str]:
    # Build Bearer Authorization headers with a fresh JWT.
    token = create_access_token({"sub": str(user.id), "role": user.role})
    return {"Authorization": f"Bearer {token}"}


# ── HTTP client fixtures ─────────────────────────────────────────────────────
@pytest_asyncio.fixture()
async def client(db_session: Session):  # noqa: ARG001
    # Unauthenticated httpx.AsyncClient backed by the test DB session.
    transport = ASGITransport(app=app)  # type: ignore[arg-type]
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac


@pytest_asyncio.fixture()
async def authorized_client(test_user: User):
    # httpx.AsyncClient pre-authenticated as test_user (caretaker).
    transport = ASGITransport(app=app)  # type: ignore[arg-type]
    async with AsyncClient(
        transport=transport,
        base_url="http://testserver",
        headers=_bearer_headers(test_user),
    ) as ac:
        yield ac


@pytest_asyncio.fixture()
async def patient_client(patient_user: User):
    # httpx.AsyncClient pre-authenticated as patient_user.
    transport = ASGITransport(app=app)  # type: ignore[arg-type]
    async with AsyncClient(
        transport=transport,
        base_url="http://testserver",
        headers=_bearer_headers(patient_user),
    ) as ac:
        yield ac
