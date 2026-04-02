import asyncio
from datetime import date, timedelta

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.benchmark import compute_benchmark
from app.core.database import get_db
from app.core.dependencies import get_current_patient_profile, get_report_pair
from app.models.orm import (
    AnomalyLog,
    DailyAverage,
    MonthlyAverage,
    Patient,
    WeeklyAverage,
    WindowReport,
    YearlyAverage,
)
from app.schemas.patients import PatientCaretakerStatus
from app.schemas.reports import (
    AllMetricsBenchmarkSchema,
    AnomalyLogSchema,
    DailyAverageSchema,
    FallAnalysisResponseSchema,
    MonthlyAverageSchema,
    WeeklyAverageSchema,
    YearlyAverageSchema,
)
from workers.batch_aggregator import calculate_averages_for_date

router = APIRouter(prefix="/patients", tags=["patients"])


# for checking is patient already has caretaker or not
@router.get("/me/status", response_model=PatientCaretakerStatus)
async def patient_caretaker_status(
    patient: Patient = Depends(get_current_patient_profile),
) -> PatientCaretakerStatus:
    # Return whether this patient has been linked to a caretaker.
    return PatientCaretakerStatus(
        has_caretaker=patient.caretaker_id is not None,
        caretaker_id=patient.caretaker_id,
    )


@router.post("/me/sessions/stop")
async def stop_gait_session(
    background_tasks: BackgroundTasks,
    patient: Patient = Depends(get_current_patient_profile),
):
    today = date.today()

    # Pass patient.id
    background_tasks.add_task(calculate_averages_for_date, today, patient.id)

    return {
        "status": "success",
        "message": "Gait monitoring session stopped. Aggregating today's data in the background.",
    }


@router.get("/me/windowReport")
async def get_window_reports(
    patient: Patient = Depends(get_current_patient_profile),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(WindowReport)
        .where(WindowReport.patient_id == patient.id)
        .order_by(desc(WindowReport.timestamp))
        .limit(1)
    )
    latest_report = result.scalars().first()
    return latest_report


@router.get("/me/dailyAverage", response_model=list[DailyAverageSchema])
async def get_daily_average(
    patient: Patient = Depends(get_current_patient_profile),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(DailyAverage).where(DailyAverage.patient_id == patient.id))
    daily_avg = result.scalars().all()
    return daily_avg


@router.get("/me/weeklyAverage", response_model=list[WeeklyAverageSchema])
async def get_weekly_average(
    patient: Patient = Depends(get_current_patient_profile),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(WeeklyAverage).where(WeeklyAverage.patient_id == patient.id))
    weekly_avg = result.scalars().all()
    return weekly_avg


@router.get("/me/monthlyAverage", response_model=list[MonthlyAverageSchema])
async def get_monthly_average(
    patient: Patient = Depends(get_current_patient_profile),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(MonthlyAverage).where(MonthlyAverage.patient_id == patient.id))
    monthly_avg = result.scalars().all()
    return monthly_avg


@router.get("/me/yearlyAverage", response_model=list[YearlyAverageSchema])
async def get_yearly_average(
    patient: Patient = Depends(get_current_patient_profile),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(YearlyAverage).where(YearlyAverage.patient_id == patient.id))
    yearly_avg = result.scalars().all()
    return yearly_avg


@router.get("/me/anomalyLog", response_model=list[AnomalyLogSchema])
async def get_anomaly_log(
    patient: Patient = Depends(get_current_patient_profile),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(AnomalyLog).where(AnomalyLog.patient_id == patient.id))
    anomaly_log = result.scalars().all()
    return anomaly_log


@router.get("/{telemetry_token}")
async def get_patient_id_by_telemetry_token(
    telemetry_token: str,
    db: AsyncSession = Depends(get_db),
) -> int:
    patient = await db.scalar(select(Patient).where(Patient.telemetry_token == telemetry_token))
    if not patient:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Patient profile not found")
    return patient.id


@router.get("/me/dailyAverage/byDate", response_model=DailyAverageSchema | None)
async def get_daily_average_by_date(
    date_str: str = Query(..., description="Date in YYYY-MM-DD format"),
    patient: Patient = Depends(get_current_patient_profile),
    db: AsyncSession = Depends(get_db),
):
    try:
        day = date.fromisoformat(date_str)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid date format. Use YYYY-MM-DD."
        ) from e

    result = await db.execute(
        select(DailyAverage).where((DailyAverage.patient_id == patient.id) & (DailyAverage.report_date == day))
    )
    return result.scalars().first()


@router.get("/me/fallAnalysis", response_model=FallAnalysisResponseSchema)
async def fall_analysis(
    date_str: str = Query(..., description="Date in YYYY-MM-DD format"),
    patient: Patient = Depends(get_current_patient_profile),
    db: AsyncSession = Depends(get_db),
):
    try:
        ref_date = date.fromisoformat(date_str)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid date format. Use YYYY-MM-DD."
        ) from e

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
    week_pair, month_pair, year_pair = await asyncio.gather(
        get_report_pair(db, patient.id, WeeklyAverage, "report_week", prev_week, latest_week),
        get_report_pair(db, patient.id, MonthlyAverage, "report_month", prev_month, latest_month),
        get_report_pair(db, patient.id, YearlyAverage, "report_year", prev_year, latest_year),
    )

    return {
        "week": week_pair,
        "month": month_pair,
        "year": year_pair,
    }


@router.get("/me/benchmark", response_model=AllMetricsBenchmarkSchema)
async def get_patient_benchmark(
    patient: Patient = Depends(get_current_patient_profile),
    db: AsyncSession = Depends(get_db),
):
    if patient.age is None:
        raise HTTPException(status_code=400, detail="Patient age not set.")

    return await compute_benchmark(patient, db)
