from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import require_role
from app.models.orm import (
    AnomalyLog,
    Caretaker,
    DailyAverage,
    MonthlyAverage,
    Patient,
    User,
    WeeklyAverage,
    YearlyAverage,
)
from app.schemas.caretaker_patients import LinkPatientRequest, PatientListItem, PatientProfileResponse

router = APIRouter(prefix="/caretakers/patients", tags=["caretaker-patients"])


async def _get_caretaker_profile(user: User, db: AsyncSession) -> Caretaker:
    caretaker = await db.scalar(select(Caretaker).where(Caretaker.user_id == user.id))
    if caretaker is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Caretaker profile not found")
    return caretaker


@router.post("", status_code=status.HTTP_204_NO_CONTENT)
async def link_patient(
    body: LinkPatientRequest,
    current_user: User = Depends(require_role("caretaker")),
    db: AsyncSession = Depends(get_db),
) -> None:
    # Link a patient (by username) to this caretaker.
    caretaker = await _get_caretaker_profile(current_user, db)

    patient_user = await db.scalar(select(User).where(User.username == body.username, User.role == "patient"))
    if patient_user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Patient user not found")

    patient = await db.scalar(select(Patient).where(Patient.user_id == patient_user.id))
    if patient is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Patient profile not found")

    if patient.caretaker_id is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Patient already linked to a caretaker")

    patient.caretaker_id = caretaker.id
    try:
        await db.commit()
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to link patient") from e


@router.delete("/{username}", status_code=status.HTTP_204_NO_CONTENT)
async def unlink_patient(
    username: str,
    current_user: User = Depends(require_role("caretaker")),
    db: AsyncSession = Depends(get_db),
) -> None:
    # Unlink a patient from this caretaker (soft-unlink: sets caretaker_id to NULL).
    caretaker = await _get_caretaker_profile(current_user, db)

    patient_user = await db.scalar(select(User).where(User.username == username, User.role == "patient"))
    if patient_user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Patient user not found")

    patient = await db.scalar(select(Patient).where(Patient.user_id == patient_user.id))
    if patient is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Patient profile not found")

    if patient.caretaker_id != caretaker.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Patient is not linked to you")

    patient.caretaker_id = None
    try:
        await db.commit()
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to unlink patient") from e


@router.get("", response_model=list[PatientListItem])
async def list_patients(
    current_user: User = Depends(require_role("caretaker")),
    db: AsyncSession = Depends(get_db),
) -> list[PatientListItem]:
    # List all patients managed by this caretaker.
    caretaker = await _get_caretaker_profile(current_user, db)
    # use join for better performance instead of N+1 queries
    stmt = (
        select(Patient.id, User.username, Patient.first_name, Patient.last_name)
        .join(User, Patient.user_id == User.id)
        .where(Patient.caretaker_id == caretaker.id)
    )

    results = (await db.execute(stmt)).all()
    return [PatientListItem.model_validate(row) for row in results]


@router.get("/{username}", response_model=PatientProfileResponse)
async def get_patient_profile(
    username: str,
    current_user: User = Depends(require_role("caretaker")),
    db: AsyncSession = Depends(get_db),
) -> PatientProfileResponse:
    # Get the full profile of a patient linked to this caretaker.
    caretaker = await _get_caretaker_profile(current_user, db)

    patient_user = await db.scalar(select(User).where((User.username == username) & (User.role == "patient")))
    if patient_user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Patient user not found")

    patient = await db.scalar(select(Patient).where(Patient.user_id == patient_user.id))
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


@router.get("/dailyAverage/{username}")
async def get_patient_daily_average(
    username: str,
    current_user: User = Depends(require_role("caretaker")),
    db: AsyncSession = Depends(get_db),
):
    caretaker = await _get_caretaker_profile(current_user, db)
    patient_user = await db.scalar(select(User).where((User.username == username) & (User.role == "patient")))

    if patient_user is None:
        raise HTTPException(status_code=404, detail="Patient username not found")
    patient = await db.scalar(select(Patient).where(Patient.user_id == patient_user.id))

    if patient is None:
        raise HTTPException(status_code=404, detail="Patient not found")
    if patient.caretaker_id != caretaker.id:
        raise HTTPException(status_code=403, detail="Unauthorized caretaker")

    result = await db.execute(select(DailyAverage).where(DailyAverage.patient_id == patient.id))
    daily_avg = result.scalars().all()
    if not daily_avg:
        raise HTTPException(status_code=404, detail="Report not found")
    return daily_avg


@router.get("/weeklyAverage/{username}")
async def get_patient_weekly_average(
    username: str,
    current_user: User = Depends(require_role("caretaker")),
    db: AsyncSession = Depends(get_db),
):
    caretaker = await _get_caretaker_profile(current_user, db)
    patient_user = await db.scalar(select(User).where((User.username == username) & (User.role == "patient")))

    if patient_user is None:
        raise HTTPException(status_code=404, detail="Patient username not found")
    patient = await db.scalar(select(Patient).where(Patient.user_id == patient_user.id))

    if patient is None:
        raise HTTPException(status_code=404, detail="Patient not found")
    if patient.caretaker_id != caretaker.id:
        raise HTTPException(status_code=403, detail="Unauthorized caretaker")

    result = await db.execute(select(WeeklyAverage).where(WeeklyAverage.patient_id == patient.id))
    weekly_avg = result.scalars().all()
    if not weekly_avg:
        raise HTTPException(status_code=404, detail="Report not found")
    return weekly_avg


@router.get("/monthlyAverage/{username}")
async def get_patient_monthly_average(
    username: str,
    current_user: User = Depends(require_role("caretaker")),
    db: AsyncSession = Depends(get_db),
):
    caretaker = await _get_caretaker_profile(current_user, db)
    patient_user = await db.scalar(select(User).where((User.username == username) & (User.role == "patient")))

    if patient_user is None:
        raise HTTPException(status_code=404, detail="Patient username not found")
    patient = await db.scalar(select(Patient).where(Patient.user_id == patient_user.id))

    if patient is None:
        raise HTTPException(status_code=404, detail="Patient not found")
    if patient.caretaker_id != caretaker.id:
        raise HTTPException(status_code=403, detail="Unauthorized caretaker")

    result = await db.execute(select(MonthlyAverage).where(MonthlyAverage.patient_id == patient.id))
    monthly_avg = result.scalars().all()
    if not monthly_avg:
        raise HTTPException(status_code=404, detail="Report not found")
    return monthly_avg


@router.get("/yearlyAverage/{username}")
async def get_patient_yearly_average(
    username: str,
    current_user: User = Depends(require_role("caretaker")),
    db: AsyncSession = Depends(get_db),
):
    caretaker = await _get_caretaker_profile(current_user, db)
    patient_user = await db.scalar(select(User).where((User.username == username) & (User.role == "patient")))

    if patient_user is None:
        raise HTTPException(status_code=404, detail="Patient username not found")
    patient = await db.scalar(select(Patient).where(Patient.user_id == patient_user.id))

    if patient is None:
        raise HTTPException(status_code=404, detail="Patient not found")
    if patient.caretaker_id != caretaker.id:
        raise HTTPException(status_code=403, detail="Unauthorized caretaker")

    result = await db.execute(select(YearlyAverage).where(YearlyAverage.patient_id == patient.id))
    yearly_avg = result.scalars().all()
    if not yearly_avg:
        raise HTTPException(status_code=404, detail="Report not found")
    return yearly_avg


@router.get("/anomalyLog/{username}")
async def get_patient_anomaly_log(
    username: str,
    current_user: User = Depends(require_role("caretaker")),
    db: AsyncSession = Depends(get_db),
):
    caretaker = await _get_caretaker_profile(current_user, db)
    patient_user = await db.scalar(select(User).where((User.username == username) & (User.role == "patient")))

    if patient_user is None:
        raise HTTPException(status_code=404, detail="Patient username not found")
    patient = await db.scalar(select(Patient).where(Patient.user_id == patient_user.id))

    if patient is None:
        raise HTTPException(status_code=404, detail="Patient not found")
    if patient.caretaker_id != caretaker.id:
        raise HTTPException(status_code=403, detail="Unauthorized caretaker")

    result = await db.execute(select(AnomalyLog).where(AnomalyLog.patient_id == patient.id))
    anomaly_log = result.scalars().all()
    if not anomaly_log:
        raise HTTPException(status_code=404, detail="Report not found")
    return anomaly_log


@router.get("/dailyAverage/byDate/{username}")
async def get_patient_daily_average_by_date(
    username: str,
    date_str: str,
    current_user: User = Depends(require_role("caretaker")),
    db: AsyncSession = Depends(get_db),
):
    try:
        day = date.fromisoformat(date_str)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD.")

    caretaker = await db.scalar(select(Caretaker).where(Caretaker.user_id == current_user.id))
    if not caretaker:
        raise HTTPException(status_code=404, detail="Caretaker profile not found.")

    patient_user = await db.scalar(select(User).where((User.username == username) & (User.role == "patient")))
    if not patient_user:
        raise HTTPException(status_code=404, detail="Patient username not found.")

    patient = await db.scalar(select(Patient).where(Patient.user_id == patient_user.id))
    if not patient or patient.caretaker_id != caretaker.id:
        raise HTTPException(status_code=403, detail="Unauthorized caretaker or patient not found.")

    result = await db.execute(
        select(DailyAverage).where((DailyAverage.patient_id == patient.id) & (DailyAverage.report_date == day))
    )
    daily_avg = result.scalars().first()
    if not daily_avg:
        raise HTTPException(status_code=404, detail="Requested report not found.")
    return daily_avg


@router.get("/fallAnalysis/{username}")
async def get_patient_fall_analysis(
    username: str,
    date_str: str = Query(..., description="Date in YYYY-MM-DD format"),
    current_user: User = Depends(require_role("caretaker")),
    db: AsyncSession = Depends(get_db),
):
    try:
        ref_date = date.fromisoformat(date_str)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD.")

    caretaker = await db.scalar(select(Caretaker).where(Caretaker.user_id == current_user.id))
    if not caretaker:
        raise HTTPException(status_code=404, detail="Caretaker profile not found.")

    patient_user = await db.scalar(select(User).where((User.username == username) & (User.role == "patient")))
    if not patient_user:
        raise HTTPException(status_code=404, detail="Patient username not found.")

    patient = await db.scalar(select(Patient).where(Patient.user_id == patient_user.id))
    if not patient or patient.caretaker_id != caretaker.id:
        raise HTTPException(status_code=403, detail="Unauthorized caretaker or patient not found.")

    def week_key(dt):
        return f"{dt.isocalendar()[0]}-W{dt.isocalendar()[1]:02d}"

    def month_key(dt):
        return dt.strftime("%Y-%m")

    def year_key(dt):
        return dt.year

    latest_week = week_key(ref_date)
    prev_week = week_key(ref_date - timedelta(weeks=1))
    latest_month = month_key(ref_date)
    prev_month = month_key(ref_date.replace(day=1) - timedelta(days=1))
    latest_year = year_key(ref_date)
    prev_year = latest_year - 1

    async def get_pair(model, field, prev_val, latest_val):
        latest = await db.scalar(
            select(model).where((model.patient_id == patient.id) & (getattr(model, field) == latest_val))
        )
        prev = await db.scalar(
            select(model).where((model.patient_id == patient.id) & (getattr(model, field) == prev_val))
        )
        if not latest or not prev:
            raise HTTPException(status_code=404, detail=f"Not enough data for {model.__tablename__}")
        return {"previous": prev, "latest": latest}

    week_pair = await get_pair(WeeklyAverage, "report_week", prev_week, latest_week)
    month_pair = await get_pair(MonthlyAverage, "report_month", prev_month, latest_month)
    year_pair = await get_pair(YearlyAverage, "report_year", prev_year, latest_year)

    return {
        "week": week_pair,
        "month": month_pair,
        "year": year_pair,
    }
