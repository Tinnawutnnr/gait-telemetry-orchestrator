import asyncio
import os

from dotenv import load_dotenv
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from app.models.orm import CohortBenchmarkData, DailyAverage, Patient

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL").replace("postgresql://", "postgresql+asyncpg://", 1)
engine = create_async_engine(DATABASE_URL)
AsyncSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

AGE_BAND = 5

# Add avg_cadence directly to the METRICS list
METRICS = [
    "avg_max_gyr_ms",
    "avg_val_gyr_hs",
    "avg_swing_time",
    "avg_stance_time",
    "avg_stride_cv",
    "total_steps",
    "avg_cadence",
]


async def refresh_all_cohorts():
    print("Starting 2 AM Daily Cohort Aggregation...")
    async with AsyncSessionLocal() as db:
        ages_result = await db.execute(select(Patient.age).distinct().where(Patient.age.isnot(None)))
        unique_ages = [r[0] for r in ages_result.fetchall()]

        for age in unique_ages:
            age_min, age_max = age - AGE_BAND, age + AGE_BAND

            cohort_result = await db.execute(select(Patient.id).where(Patient.age.between(age_min, age_max)))
            cohort_ids = [r[0] for r in cohort_result.fetchall()]

            if not cohort_ids:
                continue

            # 3. Query DailyAverage and report_date
            subq = (
                select(DailyAverage.patient_id, func.max(DailyAverage.report_date).label("max_date"))
                .where(DailyAverage.patient_id.in_(cohort_ids))
                .group_by(DailyAverage.patient_id)
                .subquery()
            )

            rows_result = await db.execute(
                select(DailyAverage).join(
                    subq,
                    (DailyAverage.patient_id == subq.c.patient_id) & (DailyAverage.report_date == subq.c.max_date),
                )
            )
            peer_records = rows_result.scalars().all()

            extracted_data = {m: [] for m in METRICS}

            for record in peer_records:
                for m in METRICS:
                    val = getattr(record, m)
                    if val is not None:
                        extracted_data[m].append(float(val))

            # Upsert into database
            for metric_name, vals in extracted_data.items():
                stmt = insert(CohortBenchmarkData).values(
                    age_center=age, metric=metric_name, cohort_vals=vals, updated_at=func.now()
                )
                stmt = stmt.on_conflict_do_update(
                    index_elements=["age_center", "metric"], set_=dict(cohort_vals=vals, updated_at=func.now())
                )
                await db.execute(stmt)

        await db.commit()
    print(" 2 AM Aggregation Complete!")


if __name__ == "__main__":
    asyncio.run(refresh_all_cohorts())
