from datetime import date, timedelta
from functools import lru_cache
import logging
import os

from apscheduler.schedulers.blocking import BlockingScheduler
from sqlalchemy import Date, Integer, cast, create_engine, delete, extract, func, select
from sqlalchemy.orm import sessionmaker

from app.models.orm import DailyAverage, MonthlyAverage, WeeklyAverage, WindowReport, YearlyAverage

log = logging.getLogger(__name__)

# Set to 0 to deletes yesterday's data
RETENTION_DAYS = 0


@lru_cache(maxsize=1)
def _get_session_local() -> sessionmaker:
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL is not set")

    engine = create_engine(database_url)
    return sessionmaker(autocommit=False, autoflush=False, bind=engine)


def calculate_averages_for_date(target_date: date, patient_id: int | None = None):
    log.info(f"Starting Data Aggregation for date: {target_date}, Patient ID: {patient_id or 'ALL'}")

    target_date_str = target_date.strftime("%Y%m%d")

    iso_year, iso_week, _ = target_date.isocalendar()
    target_week_str = f"{iso_year}-W{iso_week:02d}"

    target_month_str = target_date.strftime("%Y-%m")
    target_year_int = target_date.year

    # Calculate start and end of the week
    start_of_week = target_date - timedelta(days=target_date.weekday())
    end_of_week = start_of_week + timedelta(days=6)

    session_local = _get_session_local()
    with session_local() as db:
        try:
            # dailyAverage
            daily_conditions = [cast(WindowReport.timestamp, Date) == target_date, WindowReport.status == "MONITORING"]
            if patient_id is not None:
                daily_conditions.append(WindowReport.patient_id == patient_id)

            stmt_daily = (
                select(
                    WindowReport.patient_id,
                    func.count().label("total_windows"),
                    func.max(WindowReport.steps).label("total_steps"),
                    func.max(WindowReport.calories).label("total_calories"),
                    func.max(WindowReport.distance_m).label("total_distance_m"),
                    func.avg(WindowReport.max_gyr_ms).label("avg_max_gyr_ms"),
                    func.avg(WindowReport.val_gyr_hs).label("avg_val_gyr_hs"),
                    func.avg(WindowReport.swing_time).label("avg_swing_time"),
                    func.avg(WindowReport.stance_time).label("avg_stance_time"),
                    func.avg(WindowReport.stride_cv).label("avg_stride_cv"),
                    func.sum(cast(WindowReport.gait_health == "ANOMALY_DETECTED", Integer)).label("anomaly_count"),
                )
                .where(*daily_conditions)
                .group_by(WindowReport.patient_id)
            )

            results_daily = db.execute(stmt_daily).all()
            for row in results_daily:
                daily_record = DailyAverage(
                    daily_report_id=f"daily_{row.patient_id}_{target_date_str}",
                    patient_id=row.patient_id,
                    report_date=target_date,
                    total_windows_analyzed=row.total_windows,
                    total_steps=row.total_steps or 0,
                    total_calories=row.total_calories or 0.0,
                    total_distance_m=row.total_distance_m or 0.0,
                    avg_max_gyr_ms=row.avg_max_gyr_ms,
                    avg_val_gyr_hs=row.avg_val_gyr_hs,
                    avg_swing_time=row.avg_swing_time,
                    avg_stance_time=row.avg_stance_time,
                    avg_stride_cv=row.avg_stride_cv,
                    anomaly_count=row.anomaly_count or 0,
                )
                db.merge(daily_record)
            db.commit()
            log.info(f"Daily Average saved ({len(results_daily)} records)")

            # weeklyAverage
            weekly_conditions = [DailyAverage.report_date >= start_of_week, DailyAverage.report_date <= end_of_week]
            if patient_id is not None:
                weekly_conditions.append(DailyAverage.patient_id == patient_id)

            stmt_weekly = (
                select(
                    DailyAverage.patient_id,
                    func.sum(DailyAverage.total_windows_analyzed).label("total_windows"),
                    func.sum(DailyAverage.total_steps).label("total_steps"),
                    func.sum(DailyAverage.total_calories).label("total_calories"),
                    func.sum(DailyAverage.total_distance_m).label("total_distance_m"),
                    func.avg(DailyAverage.avg_max_gyr_ms).label("avg_max_gyr_ms"),
                    func.avg(DailyAverage.avg_val_gyr_hs).label("avg_val_gyr_hs"),
                    func.avg(DailyAverage.avg_swing_time).label("avg_swing_time"),
                    func.avg(DailyAverage.avg_stance_time).label("avg_stance_time"),
                    func.avg(DailyAverage.avg_stride_cv).label("avg_stride_cv"),
                    func.sum(DailyAverage.anomaly_count).label("anomaly_count"),
                )
                .where(*weekly_conditions)
                .group_by(DailyAverage.patient_id)
            )

            results_weekly = db.execute(stmt_weekly).all()
            for row in results_weekly:
                weekly_record = WeeklyAverage(
                    weekly_report_id=f"weekly_{row.patient_id}_{target_week_str}",
                    patient_id=row.patient_id,
                    report_week=target_week_str,
                    total_windows_analyzed=row.total_windows,
                    total_steps=row.total_steps or 0,
                    total_calories=row.total_calories or 0.0,
                    total_distance_m=row.total_distance_m or 0.0,
                    avg_max_gyr_ms=row.avg_max_gyr_ms,
                    avg_val_gyr_hs=row.avg_val_gyr_hs,
                    avg_swing_time=row.avg_swing_time,
                    avg_stance_time=row.avg_stance_time,
                    avg_stride_cv=row.avg_stride_cv,
                    anomaly_count=row.anomaly_count or 0,
                )
                db.merge(weekly_record)
            db.commit()
            log.info("Weekly Average saved")

            # monthlyAverage
            monthly_conditions = [func.to_char(DailyAverage.report_date, "YYYY-MM") == target_month_str]
            if patient_id is not None:
                monthly_conditions.append(DailyAverage.patient_id == patient_id)

            stmt_monthly = (
                select(
                    DailyAverage.patient_id,
                    func.sum(DailyAverage.total_windows_analyzed).label("total_windows"),
                    func.sum(DailyAverage.total_steps).label("total_steps"),
                    func.sum(DailyAverage.total_calories).label("total_calories"),
                    func.sum(DailyAverage.total_distance_m).label("total_distance_m"),
                    func.avg(DailyAverage.avg_max_gyr_ms).label("avg_max_gyr_ms"),
                    func.avg(DailyAverage.avg_val_gyr_hs).label("avg_val_gyr_hs"),
                    func.avg(DailyAverage.avg_swing_time).label("avg_swing_time"),
                    func.avg(DailyAverage.avg_stance_time).label("avg_stance_time"),
                    func.avg(DailyAverage.avg_stride_cv).label("avg_stride_cv"),
                    func.sum(DailyAverage.anomaly_count).label("anomaly_count"),
                )
                .where(*monthly_conditions)
                .group_by(DailyAverage.patient_id)
            )

            results_monthly = db.execute(stmt_monthly).all()
            for row in results_monthly:
                monthly_record = MonthlyAverage(
                    monthly_report_id=f"monthly_{row.patient_id}_{target_month_str}",
                    patient_id=row.patient_id,
                    report_month=target_month_str,
                    total_windows_analyzed=row.total_windows,
                    total_steps=row.total_steps or 0,
                    total_calories=row.total_calories or 0.0,
                    total_distance_m=row.total_distance_m or 0.0,
                    avg_max_gyr_ms=row.avg_max_gyr_ms,
                    avg_val_gyr_hs=row.avg_val_gyr_hs,
                    avg_swing_time=row.avg_swing_time,
                    avg_stance_time=row.avg_stance_time,
                    avg_stride_cv=row.avg_stride_cv,
                    anomaly_count=row.anomaly_count or 0,
                )
                db.merge(monthly_record)
            db.commit()
            log.info("Monthly Average saved")

            # yearlyAverage
            yearly_conditions = [extract("year", DailyAverage.report_date) == target_year_int]
            if patient_id is not None:
                yearly_conditions.append(DailyAverage.patient_id == patient_id)

            stmt_yearly = (
                select(
                    DailyAverage.patient_id,
                    func.sum(DailyAverage.total_windows_analyzed).label("total_windows"),
                    func.sum(DailyAverage.total_steps).label("total_steps"),
                    func.sum(DailyAverage.total_calories).label("total_calories"),
                    func.sum(DailyAverage.total_distance_m).label("total_distance_m"),
                    func.avg(DailyAverage.avg_max_gyr_ms).label("avg_max_gyr_ms"),
                    func.avg(DailyAverage.avg_val_gyr_hs).label("avg_val_gyr_hs"),
                    func.avg(DailyAverage.avg_swing_time).label("avg_swing_time"),
                    func.avg(DailyAverage.avg_stance_time).label("avg_stance_time"),
                    func.avg(DailyAverage.avg_stride_cv).label("avg_stride_cv"),
                    func.sum(DailyAverage.anomaly_count).label("anomaly_count"),
                )
                .where(*yearly_conditions)
                .group_by(DailyAverage.patient_id)
            )

            results_yearly = db.execute(stmt_yearly).all()
            for row in results_yearly:
                yearly_record = YearlyAverage(
                    yearly_report_id=f"yearly_{row.patient_id}_{target_year_int}",
                    patient_id=row.patient_id,
                    report_year=target_year_int,
                    total_windows_analyzed=row.total_windows,
                    total_steps=row.total_steps or 0,
                    total_calories=row.total_calories or 0.0,
                    total_distance_m=row.total_distance_m or 0.0,
                    avg_max_gyr_ms=row.avg_max_gyr_ms,
                    avg_val_gyr_hs=row.avg_val_gyr_hs,
                    avg_swing_time=row.avg_swing_time,
                    avg_stance_time=row.avg_stance_time,
                    avg_stride_cv=row.avg_stride_cv,
                    anomaly_count=row.anomaly_count or 0,
                )
                db.merge(yearly_record)
            db.commit()
            log.info("Yearly Average saved")

            # Clean up data
            if patient_id is None:
                cutoff_date = date.today() - timedelta(days=RETENTION_DAYS)
                del_stmt = delete(WindowReport).where(cast(WindowReport.timestamp, Date) < cutoff_date)
                del_result = db.execute(del_stmt)
                db.commit()
                log.info(f"Cleanup: Removed raw WindowReport older than {cutoff_date} ({del_result.rowcount} rows)")

        except Exception as e:
            db.rollback()
            log.error(f"Error occurred during data aggregation: {e}")


# midnight scheduler
def run_scheduled_job():
    yesterday = date.today() - timedelta(days=1)
    calculate_averages_for_date(yesterday)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] BATCH_JOB — %(message)s")
    scheduler = BlockingScheduler()

    # Run every day at 00:01 AM
    scheduler.add_job(run_scheduled_job, "cron", hour=0, minute=1)

    # Uncomment to test
    # scheduler.add_job(run_scheduled_job, 'interval', minutes=1)

    log.info("Batch Aggregator Started. Waiting for scheduled jobs...")
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        log.info("Scheduler stopped.")
