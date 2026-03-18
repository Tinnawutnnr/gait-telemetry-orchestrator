from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import require_role
from app.models.orm import Patient, User
from app.schemas.patients import PatientCaretakerStatus

router = APIRouter(prefix="/patients", tags=["patients"])


# for checking is patient already has caretaker or not
@router.get("/me/status", response_model=PatientCaretakerStatus)
async def patient_caretaker_status(
    current_user: User = Depends(require_role("patient")),
    db: AsyncSession = Depends(get_db),
) -> PatientCaretakerStatus:
    # Return whether this patient has been linked to a caretaker.
    patient = await db.scalar(select(Patient).where(Patient.user_id == current_user.id))
    if patient is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Patient profile not found")
    return PatientCaretakerStatus(
        has_caretaker=patient.caretaker_id is not None,
        caretaker_id=patient.caretaker_id,
    )
