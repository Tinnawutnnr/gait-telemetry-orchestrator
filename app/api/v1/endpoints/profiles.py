import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.models.orm import Caregiver, Patient, User
from app.schemas.profiles import CaregiverProfile, PatientProfile, ProfileResponse, ProfileStatus

router = APIRouter(prefix="/profiles", tags=["profiles"])


@router.get("/me/status", response_model=ProfileStatus)
async def profile_status(
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> ProfileStatus:
    # Check whether the authenticated user has created a profile yet.
    if current_user.role == "caregiver":
        has = await db.scalar(select(Caregiver).where(Caregiver.user_id == current_user.id)) is not None
    else:
        has = await db.scalar(select(Patient).where(Patient.user_id == current_user.id)) is not None
    return ProfileStatus(has_profile=has, role=current_user.role)


@router.post("/me", response_model=ProfileResponse, status_code=status.HTTP_201_CREATED)
async def create_profile(
    body: CaregiverProfile | PatientProfile,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Caregiver | Patient:
    # One-time profile provisioning based on the user's role.
    if current_user.role == "caregiver":
        if await db.scalar(select(Caregiver).where(Caregiver.user_id == current_user.id)):
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Profile already exists")
        if not isinstance(body, CaregiverProfile):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid payload for caregiver"
            )
        profile = Caregiver(user_id=current_user.id, first_name=body.first_name, last_name=body.last_name)

    else:
        if await db.scalar(select(Patient).where(Patient.user_id == current_user.id)):
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
            telemetry_token=str(uuid.uuid4()),
        )

    try:
        db.add(profile)
        await db.commit()
        await db.refresh(profile)
        return profile
    except Exception as e:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to provision profile due to a database error.",
        ) from e


@router.put("/me", response_model=ProfileResponse, status_code=status.HTTP_200_OK)
async def update_profile(
    body: CaregiverProfile | PatientProfile,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Caregiver | Patient:
    if current_user.role == "caregiver":
        profile = await db.scalar(select(Caregiver).where(Caregiver.user_id == current_user.id))
        if profile is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Profile not found")
        if not isinstance(body, CaregiverProfile):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid payload for caregiver"
            )
        profile.first_name = body.first_name
        profile.last_name = body.last_name

    else:
        profile = await db.scalar(select(Patient).where(Patient.user_id == current_user.id))
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
        await db.commit()
        await db.refresh(profile)
        return profile
    except Exception as e:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update profile due to a database error.",
        ) from e


@router.get("/me", response_model=PatientProfile | CaregiverProfile, status_code=status.HTTP_200_OK)
async def get_profile(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CaregiverProfile | PatientProfile:
    if current_user.role == "caregiver":
        profile = await db.scalar(select(Caregiver).where(Caregiver.user_id == current_user.id))
        if profile is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Profile not found")
        return CaregiverProfile(first_name=profile.first_name, last_name=profile.last_name)

    else:
        profile = await db.scalar(select(Patient).where(Patient.user_id == current_user.id))
        if profile is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Profile not found")
        return PatientProfile(
            first_name=profile.first_name,
            last_name=profile.last_name,
            age=profile.age,
            height=profile.height,
            weight=profile.weight,
        )
