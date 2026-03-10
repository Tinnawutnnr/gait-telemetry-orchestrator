from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.models.orm import User
from app.schemas.auth import TokenData

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")


def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
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
    except (JWTError, ValueError):
        raise credentials_exception from None

    user = db.get(User, token_data.user_id)
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
