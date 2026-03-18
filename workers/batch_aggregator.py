import os
import logging
from datetime import datetime, timedelta, date
from apscheduler.schedulers.blocking import BlockingScheduler

from sqlalchemy import create_engine, select, func
from sqlalchemy.orm import sessionmaker

from app.models import WindowReport, DailyAverage, SessionReport 

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] BATCH_JOB — %(message)s")
log = logging.getLogger(__name__)

DATABASE_URL = os.getenv("DATABASE_URL")
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def calculate_daily_average():
    """
    ฟังก์ชันตื่นมาคำนวณค่าเฉลี่ยรายวัน (รันทุกๆ เที่ยงคืน)
    """
    yesterday = date.today() - timedelta(days=1)
    log.info(f"Start summary for date: {yesterday}")

    with SessionLocal() as db:
        try:
            # ใช้ SQLAlchemy ในการทำ Group By และ Aggregate (AVG, SUM, COUNT)
            stmt = select(
                WindowReport.patient_id,
                func.count().label("total_windows"),
                func.sum(WindowReport.steps).label("total_steps"),
                func.sum(WindowReport.calories).label("total_calories"),
                func.sum(WindowReport.distance_m).label("total_distance_m"),
                
                func.avg(WindowReport.max_gyr_ms).label("avg_max_gyr_ms"),
                func.avg(WindowReport.val_gyr_hs).label("avg_val_gyr_hs"),
                func.avg(WindowReport.swing_time).label("avg_swing_time"),
                func.avg(WindowReport.stance_time).label("avg_stance_time"),
                func.avg(WindowReport.stride_cv).label("avg_stride_cv"),
                
                # นับจำนวนครั้งที่เกิด Anomaly ในวันนั้น
                func.sum(
                    func.cast(WindowReport.gait_health == 'ANOMALY_DETECTED', func.integer())
                ).label("anomaly_count")
            ).where(
                # กรองเอาเฉพาะข้อมูลของเมื่อวาน และเอาเฉพาะสถานะ MONITORING (ไม่เอาตอน Calibrate)
                func.date(WindowReport.timestamp) == yesterday,
                WindowReport.status == 'MONITORING'
            ).group_by(
                WindowReport.patient_id
            )

            # สั่งรัน Query
            results = db.execute(stmt).all()

            # เอาผลลัพธ์มาวนลูปยัดลงตาราง DailyAverage
            for row in results:
                daily_record = DailyAverage(
                    daily_report_id=f"daily_{row.patient_id}_{yesterday.strftime('%Y%m%d')}",
                    patient_id=row.patient_id,
                    report_date=yesterday,
                    
                    total_windows_analyzed=row.total_windows,
                    total_steps=row.total_steps,
                    total_calories=row.total_calories,
                    total_distance_m=row.total_distance_m,
                    
                    avg_max_gyr_ms=row.avg_max_gyr_ms,
                    avg_val_gyr_hs=row.avg_val_gyr_hs,
                    avg_swing_time=row.avg_swing_time,
                    avg_stance_time=row.avg_stance_time,
                    avg_stride_cv=row.avg_stride_cv,
                    
                    anomaly_count=row.anomaly_count
                )
                db.add(daily_record)
            
            db.commit()
            log.info(f"Saved DailyAverage successfully, {len(results)} row")
            
        except Exception as e:
            db.rollback()
            log.error(f"Error occured inserting Daily Average: {e}")

if __name__ == "__main__":
    # สร้าง Scheduler
    scheduler = BlockingScheduler()
    
    # สั่งให้ทำงานทุกๆ วัน เวลา 00:01 น.
    scheduler.add_job(calculate_daily_average, 'cron', hour=0, minute=1)
    
    # for test use cron for every minute:
    # scheduler.add_job(calculate_daily_average, 'interval', minutes=1)
    
    log.info("Batch Aggregator Started. Waiting for scheduled jobs...")
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        log.info("Scheduler stopped.")