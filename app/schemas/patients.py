from pydantic import BaseModel


class PatientCaretakerStatus(BaseModel):
    has_caretaker: bool
    caretaker_id: int | None = None
