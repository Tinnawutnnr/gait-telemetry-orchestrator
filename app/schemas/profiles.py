from pydantic import BaseModel, Field


class ProfileStatus(BaseModel):
    has_profile: bool
    role: str


class CaretakerProfile(BaseModel):
    model_config = {"extra": "forbid"}

    first_name: str = Field(min_length=1, max_length=100)
    last_name: str = Field(min_length=1, max_length=100)


class PatientProfile(BaseModel):
    model_config = {"extra": "forbid"}

    first_name: str = Field(min_length=1, max_length=100)
    last_name: str = Field(min_length=1, max_length=100)
    age: int = Field(ge=0, le=150)
    height: float = Field(gt=0)
    weight: float = Field(gt=0)


class ProfileResponse(BaseModel):
    id: int
    first_name: str
    last_name: str

    model_config = {"from_attributes": True}
