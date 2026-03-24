import asyncio
from typing import TypeVar

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
import jwt
from jwt.exceptions import PyJWTError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.models.orm import Caretaker, Patient, User
from app.schemas.auth import TokenData

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")


async def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    # Unauthorized error handler
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.HASH_ALGORITHM])
        sub: str | None = payload.get("sub")
        role: str | None = payload.get("role")
        if sub is None or role is None:
            raise credentials_exception
        token_data = TokenData(user_id=int(sub), role=role)
    except (PyJWTError, ValueError):
        raise credentials_exception from None

    user = await db.get(User, token_data.user_id)
    if user is None:
        raise credentials_exception
    return user


def require_role(*allowed_roles: str):
    # role check => can use to prevent access specific role
    def _check(current_user: User = Depends(get_current_user)) -> User:
        if current_user.role not in allowed_roles:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")
        return current_user

    return _check


async def _get_caretaker_profile(user: User, db: AsyncSession) -> Caretaker:
    caretaker = await db.scalar(select(Caretaker).where(Caretaker.user_id == user.id))
    if not caretaker:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Caretaker profile not found")
    return caretaker


async def _get_patient_profile(username: str, db: AsyncSession) -> Patient:
    patient_user = await db.scalar(select(User).where(User.username == username, User.role == "patient"))
    if not patient_user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Patient username not found")

    patient = await db.scalar(select(Patient).where(Patient.user_id == patient_user.id))
    if not patient:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Patient profile not found")
    return patient


async def get_authorized_patient_for_caretaker(
    username: str,
    current_user: User = Depends(require_role("caretaker")),
    db: AsyncSession = Depends(get_db),
) -> Patient:
    caretaker, patient = await asyncio.gather(
        _get_caretaker_profile(current_user, db), _get_patient_profile(username, db)
    )

    if not patient.caretaker_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Patient is not linked to any caretaker")

    if patient.caretaker_id != caretaker.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Patient is not linked to you")

    return patient


async def get_current_patient_profile(
    current_user: User = Depends(require_role("patient")),
    db: AsyncSession = Depends(get_db),
) -> Patient:
    patient = await db.scalar(select(Patient).where(Patient.user_id == current_user.id))
    if not patient:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Patient profile not found")
    return patient


T = TypeVar("T")


async def get_report_pair(
    db: AsyncSession, patient_id: int, model: type[T], field: str, prev_val: str | int, latest_val: str | int
) -> dict[str, T | None]:
    async def fetch(val: str | int) -> T | None:
        return await db.scalar(select(model).where((model.patient_id == patient_id) & (getattr(model, field) == val)))

    prev, latest = await asyncio.gather(fetch(prev_val), fetch(latest_val))
    return {"previous": prev, "latest": latest}
