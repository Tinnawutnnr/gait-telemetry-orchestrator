from httpx import AsyncClient
from sqlalchemy.orm import Session

from app.models.orm import Caretaker, Patient, User

# ── Endpoint URLs ────────────────────────────────────────────────────────────
_STATUS = "/api/v1/profiles/me/status"
_CREATE = "/api/v1/profiles/me"


# ══════════════════════════════════════════════════════════════════════════════
# Profile Status
# ══════════════════════════════════════════════════════════════════════════════
class TestProfileStatus:
    # GET /api/v1/profiles/me/status

    async def test_no_profile_returns_false(self, authorized_client: AsyncClient) -> None:
        resp = await authorized_client.get(_STATUS)
        assert resp.status_code == 200
        body = resp.json()
        assert body["has_profile"] is False
        assert body["role"] == "caretaker"

    async def test_with_profile_returns_true(
        self, authorized_client: AsyncClient, test_user, db_session: Session
    ) -> None:
        db_session.add(Caretaker(user_id=test_user.id, first_name="Jane", last_name="Doe"))
        db_session.flush()

        resp = await authorized_client.get(_STATUS)
        assert resp.status_code == 200
        assert resp.json()["has_profile"] is True

    async def test_patient_role_reports_correct_role(self, patient_client: AsyncClient) -> None:
        resp = await patient_client.get(_STATUS)
        assert resp.status_code == 200
        body = resp.json()
        assert body["role"] == "patient"
        assert body["has_profile"] is False

    async def test_patient_with_profile_returns_true(
        self, patient_client: AsyncClient, patient_user: User, db_session: Session
    ) -> None:
        db_session.add(
            Patient(user_id=patient_user.id, first_name="John", last_name="Smith", age=30, height=175.0, weight=70.0)
        )
        db_session.flush()

        resp = await patient_client.get(_STATUS)
        assert resp.status_code == 200
        assert resp.json()["has_profile"] is True

    async def test_unauthenticated_returns_401(self, client: AsyncClient) -> None:
        resp = await client.get(_STATUS)
        assert resp.status_code == 401


# ══════════════════════════════════════════════════════════════════════════════
# Create Profile
# ══════════════════════════════════════════════════════════════════════════════
class TestCreateProfile:
    # POST /api/v1/profiles/me

    async def test_caretaker_profile_returns_201(self, authorized_client: AsyncClient) -> None:
        resp = await authorized_client.post(
            _CREATE,
            json={"first_name": "Jane", "last_name": "Doe"},
        )
        assert resp.status_code == 201
        body = resp.json()
        assert body["first_name"] == "Jane"
        assert body["last_name"] == "Doe"
        assert "id" in body

    async def test_patient_profile_returns_201(self, patient_client: AsyncClient) -> None:
        resp = await patient_client.post(
            _CREATE,
            json={
                "first_name": "John",
                "last_name": "Smith",
                "age": 30,
                "height": 175.0,
                "weight": 70.0,
            },
        )
        assert resp.status_code == 201
        body = resp.json()
        assert body["first_name"] == "John"

    async def test_duplicate_profile_returns_409(
        self, authorized_client: AsyncClient, test_user, db_session: Session
    ) -> None:
        db_session.add(Caretaker(user_id=test_user.id, first_name="Jane", last_name="Doe"))
        db_session.flush()

        resp = await authorized_client.post(_CREATE, json={"first_name": "Jane", "last_name": "Doe"})
        assert resp.status_code == 409
        assert "already exists" in resp.json()["detail"].lower()

    async def test_unauthenticated_returns_401(self, client: AsyncClient) -> None:
        resp = await client.post(_CREATE, json={"first_name": "Jane", "last_name": "Doe"})
        assert resp.status_code == 401

    async def test_caretaker_missing_last_name_returns_422(self, authorized_client: AsyncClient) -> None:
        resp = await authorized_client.post(_CREATE, json={"first_name": "Jane"})
        assert resp.status_code == 422

    async def test_empty_first_name_returns_422(self, authorized_client: AsyncClient) -> None:
        resp = await authorized_client.post(_CREATE, json={"first_name": "", "last_name": "Doe"})
        assert resp.status_code == 422
