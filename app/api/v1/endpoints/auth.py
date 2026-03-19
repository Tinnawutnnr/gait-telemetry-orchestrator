from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import create_access_token, hash_password, verify_password
from app.models.orm import User
from app.schemas.auth import RegisterRequest, Token

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=Token, status_code=status.HTTP_201_CREATED)
async def register(body: RegisterRequest, db: AsyncSession = Depends(get_db)) -> Token:
    """Identity-only provisioning. Creates a User row and returns a JWT."""
    stmt = select(User).where(
        or_(User.username == body.username, User.email == body.email)
    )
    existing_user = await db.scalar(stmt)

    if existing_user:
        if existing_user.username == body.username:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Username already taken")
        if existing_user.email == body.email:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already taken")

    user = User(
        username=body.username,
        email=body.email,
        hashed_password=hash_password(body.password),
        role=body.role,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)

    token = create_access_token({"sub": str(user.id), "role": user.role})
    return Token(access_token=token)


@router.post("/login", response_model=Token)
async def login(form: OAuth2PasswordRequestForm = Depends(), db: AsyncSession = Depends(get_db)) -> Token:
    user = await db.scalar(select(User).where(User.email == form.username))

    if not user or not verify_password(form.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = create_access_token({"sub": str(user.id), "role": user.role})
    return Token(access_token=token)
