from pydantic import BaseModel, Field


class ProfileStatus(BaseModel):
    has_profile: bool
    role: str


class CaretakerProfileCreate(BaseModel):
    first_name: str = Field(min_length=1, max_length=100)
    last_name: str = Field(min_length=1, max_length=100)


class PatientProfileCreate(BaseModel):
    first_name: str = Field(min_length=1, max_length=100)
    last_name: str = Field(min_length=1, max_length=100)
    age: int | None = Field(default=None, ge=0, le=150)
    height: float = Field(gt=0)
    weight: float = Field(gt=0)


class ProfileResponse(BaseModel):
    id: int
    first_name: str
    last_name: str

    model_config = {"from_attributes": True}
