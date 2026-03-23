from datetime import date

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import require_role
from app.models.orm import Patient, User, WindowReport, DailyAverage, WeeklyAverage, MonthlyAverage, YearlyAverage, AnomalyLog
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
async def get_yearly_average(
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