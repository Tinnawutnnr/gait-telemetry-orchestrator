from sqlalchemy import desc, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.models.orm import DailyAverage, MonthlyAverage, Patient, WeeklyAverage, YearlyAverage
from app.schemas.reports import SingleMetricBenchmarkSchema, SingleMetricPeriod

AGE_BAND = 5


def _percentile(patient_val: float | None, cohort_vals: list[float]) -> float | None:
    if patient_val is None or not cohort_vals:
        return None
    below = sum(1 for v in cohort_vals if v < patient_val)
    return round((below / len(cohort_vals)) * 100, 1)


def _label(percentile: float | None) -> str | None:
    if percentile is None:
        return None
    if percentile > 75:
        return "above_peers"
    if percentile < 25:
        return "below_peers"
    return "with_peers"


def _make_metric(
    patient_val: float | None,
    cohort_vals: list[float],
) -> SingleMetricPeriod:
    cohort_avg = round(sum(cohort_vals) / len(cohort_vals), 4) if cohort_vals else None
    pct = _percentile(patient_val, cohort_vals)
    return SingleMetricPeriod(
        patient_value=patient_val,
        cohort_avg=cohort_avg,
        cohort_size=len(cohort_vals),
        percentile=pct,
        label=_label(pct),
    )


async def compute_benchmark(
    patient: Patient,
    metric: str,
    db: AsyncSession,
) -> SingleMetricBenchmarkSchema:
    age_min, age_max = patient.age - AGE_BAND, patient.age + AGE_BAND

    cohort_result = await db.execute(
        select(Patient.id).where(
            Patient.age.between(age_min, age_max),
            Patient.id != patient.id,
        )
    )
    cohort_ids = [r for (r,) in cohort_result.fetchall()]

    async def patient_latest(model, order_col) -> float | None:
        r = await db.execute(
            select(getattr(model, metric))
            .where(model.patient_id == patient.id)
            .order_by(desc(getattr(model, order_col)))
            .limit(1)
        )
        row = r.first()
        return row[0] if row else None

    async def cohort_vals(model, order_col) -> list[float]:
        if not cohort_ids:
            return []
        subq = (
            select(
                model.patient_id,
                func.max(getattr(model, order_col)).label("max_period"),
            )
            .where(model.patient_id.in_(cohort_ids))
            .group_by(model.patient_id)
            .subquery()
        )
        r = await db.execute(
            select(getattr(model, metric)).join(
                subq,
                (model.patient_id == subq.c.patient_id) & (getattr(model, order_col) == subq.c.max_period),
            )
        )
        return [row[0] for row in r.fetchall() if row[0] is not None]

    import asyncio

    (
        p_daily,
        p_weekly,
        p_monthly,
        p_yearly,
        c_daily,
        c_weekly,
        c_monthly,
        c_yearly,
    ) = await asyncio.gather(
        patient_latest(DailyAverage, "report_date"),
        patient_latest(WeeklyAverage, "report_week"),
        patient_latest(MonthlyAverage, "report_month"),
        patient_latest(YearlyAverage, "report_year"),
        cohort_vals(DailyAverage, "report_date"),
        cohort_vals(WeeklyAverage, "report_week"),
        cohort_vals(MonthlyAverage, "report_month"),
        cohort_vals(YearlyAverage, "report_year"),
    )

    return SingleMetricBenchmarkSchema(
        metric=metric,
        patient_age=patient.age,
        cohort_age_range=f"{age_min}–{age_max}",
        daily=_make_metric(p_daily, c_daily),
        weekly=_make_metric(p_weekly, c_weekly),
        monthly=_make_metric(p_monthly, c_monthly),
        yearly=_make_metric(p_yearly, c_yearly),
    )
