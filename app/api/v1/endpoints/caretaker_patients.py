from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dependencies import require_role
from app.models.orm import Caretaker, Patient, User
from app.schemas.caretaker_patients import LinkPatientRequest, PatientListItem, PatientProfileResponse

router = APIRouter(prefix="/caretakers/patients", tags=["caretaker-patients"])


def _get_caretaker_profile(user: User, db: Session) -> Caretaker:
    caretaker = db.scalar(select(Caretaker).where(Caretaker.user_id == user.id))
    if caretaker is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Caretaker profile not found")
    return caretaker


@router.post("", status_code=status.HTTP_204_NO_CONTENT)
def link_patient(
    body: LinkPatientRequest,
    current_user: User = Depends(require_role("caretaker")),
    db: Session = Depends(get_db),
) -> None:
    # Link a patient (by username) to this caretaker.
    caretaker = _get_caretaker_profile(current_user, db)

    patient_user = db.scalar(select(User).where(User.username == body.username, User.role == "patient"))
    if patient_user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Patient user not found")

    patient = db.scalar(select(Patient).where(Patient.user_id == patient_user.id))
    if patient is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Patient profile not found")

    if patient.caretaker_id is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Patient already linked to a caretaker")

    patient.caretaker_id = caretaker.id
    try:
        db.commit()
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to link patient") from e


@router.delete("/{username}", status_code=status.HTTP_204_NO_CONTENT)
def unlink_patient(
    username: str,
    current_user: User = Depends(require_role("caretaker")),
    db: Session = Depends(get_db),
) -> None:
    # Unlink a patient from this caretaker (soft-unlink: sets caretaker_id to NULL).
    caretaker = _get_caretaker_profile(current_user, db)

    patient_user = db.scalar(select(User).where(User.username == username, User.role == "patient"))
    if patient_user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Patient user not found")

    patient = db.scalar(select(Patient).where(Patient.user_id == patient_user.id))
    if patient is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Patient profile not found")

    if patient.caretaker_id != caretaker.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Patient is not linked to you")

    patient.caretaker_id = None
    try:
        db.commit()
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to unlink patient") from e


@router.get("", response_model=list[PatientListItem])
def list_patients(
    current_user: User = Depends(require_role("caretaker")),
    db: Session = Depends(get_db),
) -> list[PatientListItem]:
    # List all patients managed by this caretaker.
    caretaker = _get_caretaker_profile(current_user, db)
    # use join for better performance instead of N+1 queries
    stmt = (
        select(Patient.id, User.username, Patient.first_name, Patient.last_name)
        .join(User, Patient.user_id == User.id)
        .where(Patient.caretaker_id == caretaker.id)
    )

    results = db.execute(stmt).all()
    return [PatientListItem.model_validate(row) for row in results]


@router.get("/{username}", response_model=PatientProfileResponse)
def get_patient_profile(
    username: str,
    current_user: User = Depends(require_role("caretaker")),
    db: Session = Depends(get_db),
) -> PatientProfileResponse:
    # Get the full profile of a patient linked to this caretaker.
    caretaker = _get_caretaker_profile(current_user, db)

    patient_user = db.scalar(select(User).where(User.username == username, User.role == "patient"))
    if patient_user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Patient user not found")

    patient = db.scalar(select(Patient).where(Patient.user_id == patient_user.id))
    if patient is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Patient profile not found")

    if patient.caretaker_id != caretaker.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Patient is not linked to you")

    return PatientProfileResponse(
        id=patient.id,
        first_name=patient.first_name,
        last_name=patient.last_name,
        age=patient.age,
        height=patient.height,
        weight=patient.weight,
    )
