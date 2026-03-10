from httpx import AsyncClient
import pytest

from tests.conftest import CARETAKER_USERNAME, TEST_PASSWORD

# ── Endpoint URLs ────────────────────────────────────────────────────────────
_REGISTER = "/api/v1/auth/register"
_LOGIN = "/api/v1/auth/login"


# ══════════════════════════════════════════════════════════════════════════════
# Register
# ══════════════════════════════════════════════════════════════════════════════
class TestRegister:
    # POST /api/v1/auth/register — identity-only provisioning."""

    async def test_caretaker_returns_201_with_bearer_token(self, client: AsyncClient) -> None:
        resp = await client.post(
            _REGISTER,
            json={"username": "new_caretaker", "password": TEST_PASSWORD, "role": "caretaker"},
        )
        assert resp.status_code == 201
        body = resp.json()
        assert "access_token" in body
        assert body["token_type"] == "bearer"  # noqa: S105

    async def test_patient_returns_201(self, client: AsyncClient) -> None:
        resp = await client.post(
            _REGISTER,
            json={"username": "new_patient", "password": TEST_PASSWORD, "role": "patient"},
        )
        assert resp.status_code == 201
        assert "access_token" in resp.json()

    async def test_duplicate_username_returns_409(self, client: AsyncClient, test_user) -> None:  # noqa: ARG002
        resp = await client.post(
            _REGISTER,
            json={"username": CARETAKER_USERNAME, "password": TEST_PASSWORD, "role": "caretaker"},
        )
        assert resp.status_code == 409
        assert "already taken" in resp.json()["detail"].lower()

    async def test_invalid_role_returns_422(self, client: AsyncClient) -> None:
        resp = await client.post(
            _REGISTER,
            json={"username": "bad_role", "password": TEST_PASSWORD, "role": "admin"},
        )
        assert resp.status_code == 422

    async def test_short_password_returns_422(self, client: AsyncClient) -> None:
        resp = await client.post(
            _REGISTER,
            json={"username": "short_pw", "password": "abc", "role": "caretaker"},
        )
        assert resp.status_code == 422

    async def test_missing_fields_returns_422(self, client: AsyncClient) -> None:
        resp = await client.post(_REGISTER, json={"username": "only_name"})
        assert resp.status_code == 422

    async def test_username_too_short_returns_422(self, client: AsyncClient) -> None:
        resp = await client.post(
            _REGISTER,
            json={"username": "ab", "password": TEST_PASSWORD, "role": "caretaker"},
        )
        assert resp.status_code == 422


# ══════════════════════════════════════════════════════════════════════════════
# Login
# ══════════════════════════════════════════════════════════════════════════════
class TestLogin:
    # POST /api/v1/auth/login — OAuth2 password form.

    async def test_valid_credentials_returns_bearer_token(self, client: AsyncClient, test_user) -> None:  # noqa: ARG002
        resp = await client.post(
            _LOGIN,
            data={"username": CARETAKER_USERNAME, "password": TEST_PASSWORD},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert "access_token" in body
        assert body["token_type"] == "bearer"  # noqa: S105

    async def test_wrong_password_returns_401(self, client: AsyncClient, test_user) -> None:  # noqa: ARG002
        resp = await client.post(
            _LOGIN,
            data={"username": CARETAKER_USERNAME, "password": "wrongP@ssword1"},  # noqa: S106
        )
        assert resp.status_code == 401
        assert resp.json()["detail"] == "Incorrect username or password"

    async def test_nonexistent_user_returns_401(self, client: AsyncClient) -> None:
        resp = await client.post(
            _LOGIN,
            data={"username": "ghost_user", "password": TEST_PASSWORD},
        )
        assert resp.status_code == 401

    async def test_missing_password_returns_422(self, client: AsyncClient) -> None:
        resp = await client.post(_LOGIN, data={"username": CARETAKER_USERNAME})
        assert resp.status_code == 422

    @pytest.mark.parametrize("payload", [{"password": TEST_PASSWORD}, {}])
    async def test_missing_username_returns_422(self, client: AsyncClient, payload: dict) -> None:
        resp = await client.post(_LOGIN, data=payload)
        assert resp.status_code == 422
