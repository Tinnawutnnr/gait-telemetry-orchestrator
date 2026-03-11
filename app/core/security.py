from datetime import UTC, datetime, timedelta, timezone

import bcrypt
import jwt

from app.core.config import settings


# hash
def hash_password(plain: str) -> str:
    # bcrypt requires bytes
    pwd_bytes = plain.encode("utf-8")
    salt = bcrypt.gensalt(rounds=12)
    hashed = bcrypt.hashpw(pwd_bytes, salt)
    return hashed.decode("utf-8")


# verify
def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except ValueError:
        # Handle malformed hashes without crashing
        return False


# create access token by data
def create_access_token(data: dict, expires_delta: timedelta | None = None) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (expires_delta or timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES))  # noqa: UP017
    to_encode.update({"exp": expire, "iat": datetime.now(UTC)})  # add issued-at claim for auditing
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.HASH_ALGORITHM)
