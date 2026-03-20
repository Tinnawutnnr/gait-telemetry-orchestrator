import logging

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import (
    create_access_token,
    create_password_reset_session,
    hash_password,
    verify_password,
    verify_password_reset_session,
)
from app.models.orm import User
from app.schemas.auth import (
    ForgotPasswordRequest,
    ForgotPasswordResponse,
    RegisterRequest,
    ResetPasswordRequest,
    Token,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=Token, status_code=status.HTTP_201_CREATED)
async def register(body: RegisterRequest, db: AsyncSession = Depends(get_db)) -> Token:
    """Identity-only provisioning. Creates a User row and returns a JWT."""
    stmt = select(User).where(or_(User.username == body.username, User.email == body.email))
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


# mock by logging for now
async def send_password_reset_email(email: str, otp: str) -> None:
    logger.info(f"Mock email sent to {email}. Your OTP for password reset is: {otp}")


@router.post("/forgot-password", status_code=status.HTTP_202_ACCEPTED, response_model=ForgotPasswordResponse)
async def forgot_password(
    request: ForgotPasswordRequest, background_tasks: BackgroundTasks, db: AsyncSession = Depends(get_db)
) -> ForgotPasswordResponse:
    # Generate OTP and session token unconditionally to prevent email enumeration
    otp, session_token = create_password_reset_session(email=request.email)

    stmt = select(User).where(User.email == request.email)
    user = await db.scalar(stmt)

    if user:
        background_tasks.add_task(send_password_reset_email, user.email, otp)

    return ForgotPasswordResponse(
        message="If that email address is used by an account, we will send you an OTP to reset your password.",
        reset_session_token=session_token,
    )


@router.post("/reset-password", status_code=status.HTTP_200_OK)
async def reset_password(request: ResetPasswordRequest, db: AsyncSession = Depends(get_db)) -> dict[str, str]:
    email = verify_password_reset_session(request.reset_session_token, request.otp)

    stmt = select(User).where(User.email == email)
    user = await db.scalar(stmt)

    if not user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid request. Unable to reset password."
        )

    user.hashed_password = hash_password(request.new_password)
    db.add(user)
    await db.commit()

    return {"message": "Password has been reset successfully."}
