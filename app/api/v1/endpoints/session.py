from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import select, func, cast, Integer
from datetime import datetime
import uuid
from typing import Optional
from pydantic import BaseModel

from app.core.database import get_db
from app.models import WindowReport, SessionReport

router = APIRouter()

# สำหรับรับ Request จาก Mobile App
class SessionStopRequest(BaseModel):
    patient_id: int
    start_time: datetime
    end_time: datetime

@router.post("/sessions/stop")
def stop_session(payload: SessionStopRequest, db: Session = Depends(get_db)):
    """
    API สำหรับแอปมือถือกดปุ่ม 'หยุดเดิน' 
    ระบบจะรวบรวม WindowReport ในช่วงเวลานั้นมาสร้างเป็น SessionReport
    """
    
    # 2.  ทำ Aggregation
    stmt = select(
        func.count().label("total_windows"),
        
        # ใช้ func.max() เพื่อดึงค่า "ก้าวล่าสุดที่ทำได้" ไม่ใช่เอามา sum() กัน
        func.max(WindowReport.steps).label("total_steps"),
        func.max(WindowReport.calories).label("total_calories"),
        func.max(WindowReport.distance_m).label("total_distance_m"),
        
        # ค่าเฉลี่ย (AVG)
        func.avg(WindowReport.max_gyr_ms).label("avg_max_gyr_ms"),
        func.avg(WindowReport.val_gyr_hs).label("avg_val_gyr_hs"),
        func.avg(WindowReport.swing_time).label("avg_swing_time"),
        func.avg(WindowReport.stance_time).label("avg_stance_time"),
        func.avg(WindowReport.stride_cv).label("avg_stride_cv"),
        
        # นับจำนวนหน้าต่างที่เกิด Anomaly
        func.sum(
            cast(WindowReport.gait_health == 'ANOMALY_DETECTED', Integer)
        ).label("anomaly_count")
    ).where(
        WindowReport.patient_id == payload.patient_id,
        WindowReport.timestamp >= payload.start_time,
        WindowReport.timestamp <= payload.end_time,
        WindowReport.status == 'MONITORING' # เอาเฉพาะตอนเดินจริง ไม่นับตอน Calibrate
    )

    result = db.execute(stmt).first()

    # ถ้าไม่มีข้อมูลเลย (เช่น เปิดแอปแล้วกดปิดทันทีโดยไม่เดิน)
    if not result or result.total_windows == 0:
        raise HTTPException(status_code=404, detail="ไม่พบข้อมูลการเดินในช่วงเวลานี้")

    # 3. สร้าง Record ลงตาราง SessionReport
    new_session = SessionReport(
        session_report_id=str(uuid.uuid4()),
        patient_id=payload.patient_id,
        timestamp=payload.end_time,
        
        total_windows_analyzed=result.total_windows,
        total_steps=result.total_steps or 0,
        total_calories=result.total_calories or 0.0,
        total_distance_m=result.total_distance_m or 0.0,
        
        avg_max_gyr_ms=result.avg_max_gyr_ms,
        avg_val_gyr_hs=result.avg_val_gyr_hs,
        avg_swing_time=result.avg_swing_time,
        avg_stance_time=result.avg_stance_time,
        avg_stride_cv=result.avg_stride_cv,
        
        anomaly_count=result.anomaly_count or 0
    )

    db.add(new_session)
    db.commit()
    db.refresh(new_session)

    return {"message": "Session saved successfully", "data": new_session}