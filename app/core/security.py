from datetime import UTC, datetime, timedelta, timezone
import hashlib
import hmac
import secrets

import bcrypt
from fastapi import HTTPException, status
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


# use hmac to prevent brute-force attack on jwt
def __hash_otp(otp: str) -> str:
    return hmac.new(settings.SECRET_KEY.encode("utf-8"), otp.encode("utf-8"), hashlib.sha256).hexdigest()


# create password reset session token and otp
def create_password_reset_session(email: str) -> tuple[str, str]:
    otp = "".join(str(secrets.randbelow(10)) for _ in range(6))
    expire = datetime.now(UTC) + timedelta(minutes=5)
    to_encode = {"sub": email, "scope": "password_reset_otp", "otp_hash": __hash_otp(otp), "exp": expire}
    encoded_jwt = jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.HASH_ALGORITHM)
    return otp, encoded_jwt


def verify_password_reset_session(token: str, otp: str) -> str:
    try:
        # decode jwt
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.HASH_ALGORITHM])

        # check scope on jwt
        if payload.get("scope") != "password_reset_otp":
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid session.")

        # check otp on jwt
        expected_hash = payload.get("otp_hash")
        if not expected_hash or expected_hash != __hash_otp(otp):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid OTP.")

        # get email from jwt
        email: str | None = payload.get("sub")
        if email is None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid session.")
        return email
    except jwt.ExpiredSignatureError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="OTP session has expired.") from e
    except jwt.PyJWTError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid session.") from e
