from httpx import ASGITransport, AsyncClient
import pytest
import pytest_asyncio
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.core.security import create_access_token, hash_password
from app.main import app
from app.models.orm import Base, User

# create an engine for the test database; use connection pooling with pre-ping to avoid stale connections
_engine = create_engine(settings.DATABASE_URL, pool_pre_ping=True)

# Reusable constants for test users
TEST_PASSWORD: str = "secureP@ss123"  # noqa: S105
CARETAKER_USERNAME: str = "caretaker_jane"
PATIENT_USERNAME: str = "patient_john"


# ── Schema lifecycle (once per session, on-demand) ───────────────────────────
@pytest.fixture(scope="session")
def _create_tables():
    # Create all ORM tables; drop them after the session finishes.
    Base.metadata.create_all(bind=_engine)
    yield
    Base.metadata.drop_all(bind=_engine)


# ── Per-test transactional isolation ─────────────────────────────────────────
@pytest.fixture()
def db_session(_create_tables):
    # Yield a Session wrapped in a savepoint; rolls back after the test (doesn't commit to the DB).
    connection = _engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection, join_transaction_mode="create_savepoint")

    # Wire FastAPI to use this session for the duration of the test
    app.dependency_overrides[get_db] = lambda: session

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
