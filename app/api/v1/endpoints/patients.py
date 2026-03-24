from datetime import date, timedelta

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import require_role
from app.models.orm import (
    AnomalyLog,
    DailyAverage,
    MonthlyAverage,
    Patient,
    User,
    WeeklyAverage,
    WindowReport,
    YearlyAverage,
)
from app.schemas.patients import PatientCaretakerStatus
from workers.batch_aggregator import calculate_averages_for_date

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


@router.post("/me/sessions/stop")
async def stop_gait_session(
    background_tasks: BackgroundTasks,
    current_user: User = Depends(require_role("patient")),
    db: AsyncSession = Depends(get_db),
):
    patient = await db.scalar(select(Patient).where(Patient.user_id == current_user.id))

    if not patient:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Patient profile not found.")

    today = date.today()

    # Pass patient.id
    background_tasks.add_task(calculate_averages_for_date, today, patient.id)

    return {
        "status": "success",
        "message": "Gait monitoring session stopped. Aggregating today's data in the background.",
    }


@router.get("/me/windowReport")
async def get_window_reports(
    current_user: User = Depends(require_role("patient")),
    db: AsyncSession = Depends(get_db),
):
    patient = await db.scalar(select(Patient).where(Patient.user_id == current_user.id))

    if not patient:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Patient profile not found.")

    result = await db.execute(
        select(WindowReport)
        .where(WindowReport.patient_id == patient.id)
        .order_by(desc(WindowReport.timestamp))
        .limit(1)
    )
    latest_report = result.scalars().first()
    if not latest_report:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No window report found.")
    return latest_report


@router.get("/me/dailyAverage")
async def get_daily_average(
    current_user: User = Depends(require_role("patient")),
    db: AsyncSession = Depends(get_db),
):
    patient = await db.scalar(select(Patient).where(Patient.user_id == current_user.id))

    if not patient:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Patient profile not found.")

    result = await db.execute(select(DailyAverage).where(DailyAverage.patient_id == patient.id))
    daily_avg = result.scalars().all()
    if not daily_avg:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Requested report not found.")
    return daily_avg


@router.get("/me/weeklyAverage")
async def get_weekly_average(
    current_user: User = Depends(require_role("patient")),
    db: AsyncSession = Depends(get_db),
):
    patient = await db.scalar(select(Patient).where(Patient.user_id == current_user.id))

    if not patient:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Patient profile not found.")

    result = await db.execute(select(WeeklyAverage).where(WeeklyAverage.patient_id == patient.id))
    weekly_avg = result.scalars().all()
    if not weekly_avg:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Requested report not found.")
    return weekly_avg


@router.get("/me/monthlyAverage")
async def get_monthly_average(
    current_user: User = Depends(require_role("patient")),
    db: AsyncSession = Depends(get_db),
):
    patient = await db.scalar(select(Patient).where(Patient.user_id == current_user.id))

    if not patient:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Patient profile not found.")

    result = await db.execute(select(MonthlyAverage).where(MonthlyAverage.patient_id == patient.id))
    monthly_avg = result.scalars().all()
    if not monthly_avg:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Requested report not found.")
    return monthly_avg


@router.get("/me/yearlyAverage")
async def get_yearly_average(
    current_user: User = Depends(require_role("patient")),
    db: AsyncSession = Depends(get_db),
):
    patient = await db.scalar(select(Patient).where(Patient.user_id == current_user.id))

    if not patient:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Patient profile not found.")

    result = await db.execute(select(YearlyAverage).where(YearlyAverage.patient_id == patient.id))
    yearly_avg = result.scalars().all()
    if not yearly_avg:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Requested report not found.")
    return yearly_avg


@router.get("/me/anomalyLog")
async def get_anomaly_log(
    current_user: User = Depends(require_role("patient")),
    db: AsyncSession = Depends(get_db),
):
    patient = await db.scalar(select(Patient).where(Patient.user_id == current_user.id))

    if not patient:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Patient profile not found.")

    result = await db.execute(select(AnomalyLog).where(AnomalyLog.patient_id == patient.id))
    anomaly_log = result.scalars().all()
    if not anomaly_log:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Requested report not found.")
    return anomaly_log


@router.get("/me/{telemetry_token}")
async def get_patient_id_by_telemetry_token(
    telemetry_token: str,
    db: AsyncSession = Depends(get_db),
) -> int:
    patient = await db.scalar(select(Patient).where(Patient.telemetry_token == telemetry_token))
    if patient is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Patient profile not found")
    return patient.id


@router.get("/me/dailyAverage/byDate")
async def get_daily_average_by_date(
    date_str: str,
    current_user: User = Depends(require_role("patient")),
    db: AsyncSession = Depends(get_db),
):
    try:
        day = date.fromisoformat(date_str)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid date format. Use YYYY-MM-DD."
        ) from e

    patient = await db.scalar(select(Patient).where(Patient.user_id == current_user.id))
    if not patient:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Patient profile not found.")

    result = await db.execute(
        select(DailyAverage).where((DailyAverage.patient_id == patient.id) & (DailyAverage.report_date == day))
    )
    daily_avg = result.scalars().first()
    if not daily_avg:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Requested report not found.")
    return daily_avg


@router.get("/me/fallAnalysis")
async def fall_analysis(
    date_str: str = Query(..., description="Date in YYYY-MM-DD format"),
    current_user: User = Depends(require_role("patient")),
    db: AsyncSession = Depends(get_db),
):
    try:
        ref_date = date.fromisoformat(date_str)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid date format. Use YYYY-MM-DD."
        ) from e

    patient = await db.scalar(select(Patient).where(Patient.user_id == current_user.id))
    if not patient:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Patient profile not found.")

    # Helper functions to get period keys
    def week_key(dt):
        return f"{dt.isocalendar()[0]}-W{dt.isocalendar()[1]:02d}"

    def month_key(dt):
        return dt.strftime("%Y-%m")

    def year_key(dt):
        return dt.year

    # Get keys for latest and previous periods
    latest_week = week_key(ref_date)
    prev_week = week_key(ref_date - timedelta(weeks=1))
    latest_month = month_key(ref_date)
    prev_month = month_key(ref_date.replace(day=1) - timedelta(days=1))
    latest_year = year_key(ref_date)
    prev_year = latest_year - 1

    # Query for each period
    async def get_pair(model, field, prev_val, latest_val):
        latest = await db.scalar(
            select(model).where((model.patient_id == patient.id) & (getattr(model, field) == latest_val))
        )
        prev = await db.scalar(
            select(model).where((model.patient_id == patient.id) & (getattr(model, field) == prev_val))
        )
        if not latest or not prev:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail=f"Not enough data for {model.__tablename__}"
            )
        return {"previous": prev, "latest": latest}

    week_pair = await get_pair(WeeklyAverage, "report_week", prev_week, latest_week)
    month_pair = await get_pair(MonthlyAverage, "report_month", prev_month, latest_month)
    year_pair = await get_pair(YearlyAverage, "report_year", prev_year, latest_year)

    return {
        "week": week_pair,
        "month": month_pair,
        "year": year_pair,
    }
