from pydantic import BaseModel


class PatientCaregiverStatus(BaseModel):
    has_caregiver: bool
    caregiver_id: int | None = None
