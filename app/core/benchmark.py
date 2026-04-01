import statistics

from sqlalchemy import desc
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.models.orm import CohortBenchmarkData, DailyAverage, Patient
from app.schemas.reports import AllMetricsBenchmarkSchema, SingleMetricPeriod

AGE_BAND = 5


def _percentile(patient_val: float | None, cohort_vals: list[float]) -> float | None:
    if patient_val is None or not cohort_vals:
        return None
    below = sum(1 for v in cohort_vals if v < patient_val)
    return round((below / len(cohort_vals)) * 100, 1)


def _make_metric(
    patient_val: float | None,
    cohort_vals: list[float],
) -> SingleMetricPeriod:

    # Handle no peers in cohort
    if not cohort_vals:
        return SingleMetricPeriod(
            patient_value=patient_val,
            cohort_avg=None,
            cohort_size=0,
            percentile=None,
            lower_bound=None,
            upper_bound=None,
            label=None,
        )

    # Calculate Average
    cohort_avg = sum(cohort_vals) / len(cohort_vals)

    # Calculate Standard Deviation
    if len(cohort_vals) > 1:
        sd = statistics.stdev(cohort_vals)
    else:
        sd = 0.0

    # Create Bounds (Mean ± 1 SD)
    lower_bound = cohort_avg - sd
    upper_bound = cohort_avg + sd

    # Determine Label based on actual values crossing the bounds
    label = None
    if patient_val is not None:
        if patient_val > upper_bound:
            label = "above_peers"
        elif patient_val < lower_bound:
            label = "below_peers"
        else:
            label = "with_peers"

    # Keep percentile for the UI
    pct = _percentile(patient_val, cohort_vals)

    return SingleMetricPeriod(
        patient_value=round(patient_val, 4) if patient_val is not None else None,
        cohort_avg=round(cohort_avg, 4),
        cohort_size=len(cohort_vals),
        percentile=pct,
        lower_bound=round(lower_bound, 4),
        upper_bound=round(upper_bound, 4),
        label=label,
    )


async def compute_benchmark(
    patient: Patient,
    db: AsyncSession,
) -> AllMetricsBenchmarkSchema:
    age_min, age_max = patient.age - AGE_BAND, patient.age + AGE_BAND

    # Fetch patient's latest DailyAverage
    r_patient = await db.execute(
        select(DailyAverage)
        .where(DailyAverage.patient_id == patient.id)
        .order_by(desc(DailyAverage.report_date))
        .limit(1)
    )
    patient_latest = r_patient.scalars().first()

    # Extract patient values directly from the database row
    patient_vals = {
        "avg_max_gyr_ms": getattr(patient_latest, "avg_max_gyr_ms", None) if patient_latest else None,
        "avg_val_gyr_hs": getattr(patient_latest, "avg_val_gyr_hs", None) if patient_latest else None,
        "avg_swing_time": getattr(patient_latest, "avg_swing_time", None) if patient_latest else None,
        "avg_stance_time": getattr(patient_latest, "avg_stance_time", None) if patient_latest else None,
        "avg_stride_cv": getattr(patient_latest, "avg_stride_cv", None) if patient_latest else None,
        "total_steps": getattr(patient_latest, "total_steps", None) if patient_latest else None,
        "avg_cadence": getattr(patient_latest, "avg_cadence", None) if patient_latest else None,
    }

    # Fetch PRE-CALCULATED cohort arrays for all metrics 
    r_cohort = await db.execute(
        select(CohortBenchmarkData.metric, CohortBenchmarkData.cohort_vals)
        .where(CohortBenchmarkData.age_center == patient.age)
    )
    
    # Store it in a dictionary mapping metric_name -> list of float values
    cohort_data = {row.metric: row.cohort_vals for row in r_cohort.fetchall()}

    metrics_result = {}
    for metric_name, p_val in patient_vals.items():
        c_vals = cohort_data.get(metric_name, [])
        metrics_result[metric_name] = _make_metric(p_val, c_vals)

    # 5. Return the newly formatted schema
    return AllMetricsBenchmarkSchema(
        patient_age=patient.age,
        cohort_age_range=f"{age_min}–{age_max}",
        metrics=metrics_result
    )