import asyncio
import logging
import os

from apscheduler.schedulers.blocking import BlockingScheduler
from dotenv import load_dotenv
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from app.models.orm import CohortBenchmarkData, DailyAverage, Patient

load_dotenv()

# Setup clean logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] BATCH_JOB — %(message)s")
log = logging.getLogger(__name__)

DATABASE_URL = os.getenv("DATABASE_URL").replace("postgresql://", "postgresql+asyncpg://", 1)
engine = create_async_engine(DATABASE_URL)
AsyncSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

AGE_BAND = 5

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
    """The core asynchronous database logic."""
    log.info("Starting 2 AM Daily Cohort Aggregation...")
    async with AsyncSessionLocal() as db:
        ages_result = await db.execute(select(Patient.age).distinct().where(Patient.age.isnot(None)))
        unique_ages = [r[0] for r in ages_result.fetchall()]

        for age in unique_ages:
            age_min, age_max = age - AGE_BAND, age + AGE_BAND

            cohort_result = await db.execute(select(Patient.id).where(Patient.age.between(age_min, age_max)))
            cohort_ids = [r[0] for r in cohort_result.fetchall()]

            if not cohort_ids:
                continue

            # Query DailyAverage and report_date
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
    log.info("Aggregation Complete!")


def run_scheduled_job():
    """
    Synchronous wrapper for the scheduler.
    It bridges the gap between BlockingScheduler and async database operations.
    """
    asyncio.run(refresh_all_cohorts())


if __name__ == "__main__":
    scheduler = BlockingScheduler()

    # Run every day at 02:00 AM
    # Note: If your server is on UTC and you want Bangkok time, use:
    scheduler.add_job(run_scheduled_job, "cron", hour=2, minute=0, timezone="Asia/Bangkok")

    # Uncomment this line to test it running every 1 minute while you develop!
    # scheduler.add_job(run_scheduled_job, 'interval', minutes=1)

    log.info("Batch Aggregator Started. Waiting for scheduled jobs...")
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        log.info("Scheduler stopped.")
