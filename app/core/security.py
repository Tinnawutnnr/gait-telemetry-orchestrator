from datetime import datetime, timedelta, timezone

import jwt
from passlib.context import CryptContext

from app.core.config import settings

# manage crypto
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


# hash
def hash_password(plain: str) -> str:
    return pwd_context.hash(plain)


# verify
def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


# create access token by data
def create_access_token(data: dict, expires_delta: timedelta | None = None) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (expires_delta or timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES))  # noqa: UP017
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.HASH_ALGORITHM)
