from pydantic import BaseModel, Field


class LinkPatientRequest(BaseModel):
    username: str = Field(min_length=3, max_length=50)


class PatientListItem(BaseModel):
    id: int
    username: str
    first_name: str
    last_name: str

    model_config = {"from_attributes": True}


class PatientProfileResponse(BaseModel):
    id: int
    first_name: str
    last_name: str
    age: int | None
    height: float
    weight: float

    model_config = {"from_attributes": True}
