from pydantic import BaseModel, EmailStr, Field


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"  # noqa: S105


class TokenData(BaseModel):
    user_id: int
    role: str


class RegisterRequest(BaseModel):
    """Identity-only registration — profile is provisioned separately."""

    username: str = Field(min_length=3, max_length=50)
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    role: str = Field(pattern=r"^(caretaker|patient)$")


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ForgotPasswordResponse(BaseModel):
    message: str
    reset_session_token: str


class ResetPasswordRequest(BaseModel):
    reset_session_token: str
    otp: str = Field(min_length=6, max_length=6)
    new_password: str = Field(min_length=8)
