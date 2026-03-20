from pydantic import BaseModel, EmailStr, Field, field_validator


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"  # noqa: S105


class TokenData(BaseModel):
    user_id: int
    role: str


class RegisterRequest(BaseModel):
    """Identity-only registration — profile is provisioned separately."""

    email: EmailStr
    username: str = Field(min_length=3, max_length=50)
    password: str = Field(min_length=8, max_length=128)
    role: str = Field(pattern=r"^(caretaker|patient)$")

    @field_validator("username")
    @classmethod
    def normalize_username(cls, v: str) -> str:
        return v.strip().lower()

    @field_validator("email")
    @classmethod
    def normalize_email(cls, v: str) -> str:
        return v.strip().lower()


class ForgotPasswordRequest(BaseModel):
    email: EmailStr

    @field_validator("email")
    @classmethod
    def normalize_email(cls, v: str) -> str:
        return v.strip().lower()


class ForgotPasswordResponse(BaseModel):
    message: str
    reset_session_token: str


class ResetPasswordRequest(BaseModel):
    reset_session_token: str
    otp: str = Field(min_length=6, max_length=6)
    new_password: str = Field(min_length=8)
