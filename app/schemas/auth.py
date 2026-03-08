from pydantic import BaseModel, Field


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"  # noqa: S105


class TokenData(BaseModel):
    user_id: int
    role: str


class RegisterRequest(BaseModel):
    """Identity-only registration — profile is provisioned separately."""

    username: str = Field(min_length=3, max_length=50)
    password: str = Field(min_length=8, max_length=128)
    role: str = Field(pattern=r"^(caretaker|patient)$")
