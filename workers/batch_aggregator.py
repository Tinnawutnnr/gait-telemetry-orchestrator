import os
import logging
from datetime import datetime, timedelta, date
from apscheduler.schedulers.blocking import BlockingScheduler

from sqlalchemy import create_engine, select, func, delete, cast, Integer
from sqlalchemy.orm import sessionmaker

from app.models.orm import WindowReport, DailyAverage

# Setup Logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] BATCH_JOB — %(message)s")
log = logging.getLogger(__name__)

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://test:test@localhost:5433/gait_test")
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Set the number of days to keep raw data (WindowReport) for retrospect
RETENTION_DAYS = 1  

def calculate_daily_average_and_cleanup():
    """
    Function wakes up to do 2 things: 
    1. Calculate yesterday's average
    2. Delete raw data older than 1 day
    """
    yesterday = date.today() - timedelta(days=1)
    cutoff_date = date.today() - timedelta(days=RETENTION_DAYS)
    
    log.info(f"Started Batch Job for date: {yesterday}")

    with SessionLocal() as db:
        try:
            stmt = select(
                WindowReport.patient_id,
                func.count().label("total_windows"),
                func.max(WindowReport.steps).label("total_steps"), # Use max because it is an accumulated value
                func.max(WindowReport.calories).label("total_calories"),
                func.max(WindowReport.distance_m).label("total_distance_m"),
                
                func.avg(WindowReport.max_gyr_ms).label("avg_max_gyr_ms"),
                func.avg(WindowReport.val_gyr_hs).label("avg_val_gyr_hs"),
                func.avg(WindowReport.swing_time).label("avg_swing_time"),
                func.avg(WindowReport.stance_time).label("avg_stance_time"),
                func.avg(WindowReport.stride_cv).label("avg_stride_cv"),
                
                func.sum(
                    cast(WindowReport.gait_health == 'ANOMALY_DETECTED', Integer)
                ).label("anomaly_count")
            ).where(
                func.date(WindowReport.timestamp) == yesterday,
                WindowReport.status == 'MONITORING'
            ).group_by(
                WindowReport.patient_id
            )

            results = db.execute(stmt).all()

            for row in results:
                daily_record = DailyAverage(
                    daily_report_id=f"daily_{row.patient_id}_{yesterday.strftime('%Y%m%d')}",
                    patient_id=row.patient_id,
                    report_date=yesterday,
                    
                    total_windows_analyzed=row.total_windows,
                    total_steps=row.total_steps or 0,
                    total_calories=row.total_calories or 0.0,
                    total_distance_m=row.total_distance_m or 0.0,
                    
                    avg_max_gyr_ms=row.avg_max_gyr_ms,
                    avg_val_gyr_hs=row.avg_val_gyr_hs,
                    avg_swing_time=row.avg_swing_time,
                    avg_stance_time=row.avg_stance_time,
                    avg_stride_cv=row.avg_stride_cv,
                    
                    anomaly_count=row.anomaly_count or 0
                )
                db.add(daily_record)
            
            # Save daily record
            db.commit()
            log.info(f"Successfully saved DailyAverage records, count: {len(results)} records")

            # ==========================================
            # 🧹 PHASE 2: Database Cleanup (Data Cleanup)
            # ==========================================
            del_stmt = delete(WindowReport).where(
                func.date(WindowReport.timestamp) < cutoff_date
            )
            del_result = db.execute(del_stmt)
            
            # Commit deletion
            db.commit()
            log.info(f"Cleaned up WindowReport data older than {cutoff_date} successfully ({del_result.rowcount} rows)")
            
        except Exception as e:
            db.rollback()
            log.error(f"❌ Error occurred in Batch Job: {e}")

if __name__ == "__main__":
    scheduler = BlockingScheduler()
    
    # Run on Production: Execute every day at 00:01
    scheduler.add_job(calculate_daily_average_and_cleanup, 'cron', hour=0, minute=1)
    
    # ---------------------------------------------------------
    # ⚠️ Test Mode (uncomment the line below to test every 1 minute)
    # scheduler.add_job(calculate_daily_average_and_cleanup, 'interval', minutes=1)
    # ---------------------------------------------------------
    
    log.info("Batch Aggregator Started. Waiting for scheduled jobs...")
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        log.info("Scheduler stopped.")