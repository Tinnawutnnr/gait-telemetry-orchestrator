from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.models.orm import Caretaker, Patient, User
from app.schemas.profiles import CaretakerProfile, PatientProfile, ProfileResponse, ProfileStatus

router = APIRouter(prefix="/profiles", tags=["profiles"])


@router.get("/me/status", response_model=ProfileStatus)
def profile_status(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> ProfileStatus:
    # Check whether the authenticated user has created a profile yet.
    if current_user.role == "caretaker":
        has = db.scalar(select(Caretaker).where(Caretaker.user_id == current_user.id)) is not None
    else:
        has = db.scalar(select(Patient).where(Patient.user_id == current_user.id)) is not None
    return ProfileStatus(has_profile=has, role=current_user.role)


@router.post("/me", response_model=ProfileResponse, status_code=status.HTTP_201_CREATED)
def create_profile(
    body: CaretakerProfile | PatientProfile,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Caretaker | Patient:
    # One-time profile provisioning based on the user's role.
    if current_user.role == "caretaker":
        if db.scalar(select(Caretaker).where(Caretaker.user_id == current_user.id)):
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Profile already exists")
        if not isinstance(body, CaretakerProfile):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid payload for caretaker"
            )
        profile = Caretaker(user_id=current_user.id, first_name=body.first_name, last_name=body.last_name)

    else:
        if db.scalar(select(Patient).where(Patient.user_id == current_user.id)):
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Profile already exists")
        if not isinstance(body, PatientProfile):
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid payload for patient")
        profile = Patient(
            user_id=current_user.id,
            first_name=body.first_name,
            last_name=body.last_name,
            age=body.age,
            height=body.height,
            weight=body.weight,
        )

    try:
        db.add(profile)
        db.commit()
        db.refresh(profile)
        return profile
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to provision profile due to a database error.",
        ) from e


@router.put("/me", response_model=ProfileResponse, status_code=status.HTTP_200_OK)
def update_profile(
    body: CaretakerProfile | PatientProfile,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Caretaker | Patient:
    if current_user.role == "caretaker":
        profile = db.scalar(select(Caretaker).where(Caretaker.user_id == current_user.id))
        if profile is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Profile not found")
        if not isinstance(body, CaretakerProfile):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid payload for caretaker"
            )
        profile.first_name = body.first_name
        profile.last_name = body.last_name

    else:
        profile = db.scalar(select(Patient).where(Patient.user_id == current_user.id))
        if profile is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Profile not found")
        if not isinstance(body, PatientProfile):
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid payload for patient")
        profile.first_name = body.first_name
        profile.last_name = body.last_name
        profile.age = body.age
        profile.height = body.height
        profile.weight = body.weight

    try:
        db.commit()
        db.refresh(profile)
        return profile
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update profile due to a database error.",
        ) from e
