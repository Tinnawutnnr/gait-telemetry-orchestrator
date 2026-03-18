import asyncio
import json
import logging
import os
import signal
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.models import WindowReport, AnomalyLog

from aiokafka import AIOKafkaConsumer

from workers.realtime_processor import GaitSystem

#DB conneciton
DATABASE_URL = os.getenv("DATABASE_URL")

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# ตั้งค่า Logging ให้อ่านง่ายเวลารันใน Docker
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(levelname)s] ML_WORKER — %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
)
log = logging.getLogger(__name__)

# Configuration ของ Environment var
KAFKA_BROKER_URL = os.getenv("KAFKA_BROKER_URL")
KAFKA_TOPIC = os.getenv("KAFKA_TOPIC")
KAFKA_GROUP_ID = os.getenv("KAFKA_GROUP_ID")

system = GaitSystem()
_shutdown_event = asyncio.Event()

import uuid
from datetime import datetime, timezone

def save_to_database(report_dict, anomaly_dict=None):
    with SessionLocal() as db:
        try:
            new_report = WindowReport(**report_dict)
            db.add(new_report)
            
            if anomaly_dict:
                new_anomaly = AnomalyLog(**anomaly_dict)
                db.add(new_anomaly)
                
            db.commit()
            log.info(f"Saved WindowReport (ID: {report_dict['window_report_id']}) to DB.")
            
        except Exception as e:
            db.rollback() 
            log.error(f"Database Insert Failed: {e}")

def create_window_report_json(ml_result, patient_id):
    # WindowReport
    report = {
        "window_report_id": str(uuid.uuid4()), # new UUID
        "patient_id": patient_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        
        "status": None,
        "gait_health": None,
        "anomaly_score": None,
        
        "max_gyr_ms": None,
        "val_gyr_hs": None,
        "swing_time": None,
        "stance_time": None,
        "stride_time": None,
        "stride_cv": None,
        "n_strides": None,
        
        "steps": None,
        "calories": None,
        "distance_m": None
    }

    # case 1 : calibrate case
    if ml_result.get("type") == "status":
        report["status"] = "CALIBRATING"

    # case2 : monitoring
    elif ml_result.get("type") == "analysis":
        report["status"] = "MONITORING"
        report["gait_health"] = ml_result.get("gait_health")
        report["anomaly_score"] = ml_result.get("anomaly_score")
        
        metrics = ml_result.get("metrics", {})
        report["max_gyr_ms"] = metrics.get("max_gyr_ms")
        report["val_gyr_hs"] = metrics.get("val_gyr_hs")
        report["swing_time"] = metrics.get("swing_time")
        report["stance_time"] = metrics.get("stance_time")
        report["stride_time"] = metrics.get("stride_time")
        report["stride_cv"] = metrics.get("stride_cv")
        report["n_strides"] = metrics.get("n_strides")
        
        # ดึง Steps สะสมจากตัว System ออกมาตรงๆ เลย
        report["steps"] = system.total_steps
        report["calories"] = system.total_calories
        
        # สมมติระยะทาง: 1 ก้าวเดินเฉลี่ย = 0.7 เมตร (ปรับแก้ตามสูตรจริงของคุณได้)
        report["distance_m"] = system.total_steps * 0.7 

    return report

def create_anomaly_log_json(ml_result, window_report_id, patient_id):
    contribution = ml_result.get("contribution", {})
    return {
        "anomaly_id": str(uuid.uuid4()),
        "window_id": window_report_id,
        "patient_id": patient_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "anomaly_score": ml_result.get("anomaly_score"),
        "root_cause_feature": contribution.get("feature"),
        "z_score": contribution.get("z_score"),
        "current_val": contribution.get("current_val"),
        "normal_ref": contribution.get("normal_ref")
    }


def _signal_handler():
    log.info("Received stop signal. Gracefully shutting down...")
    _shutdown_event.set()


async def run_worker():
    loop = asyncio.get_running_loop()
    # SIGINT = signal interrupt(from Ctrl + C),
    for sig in (signal.SIGINT, signal.SIGTERM):  # SIGTERM = signal terminate(from docker stop or else)
        # if we get SIGINT or SINGTERM
        loop.add_signal_handler(sig, _signal_handler)  # dont just kill worker run func _signal_handler first

    # Kafka Consumer Config
    consumer = AIOKafkaConsumer(
        KAFKA_TOPIC,
        bootstrap_servers=KAFKA_BROKER_URL,
        value_deserializer=lambda m: json.loads(m.decode("utf-8")),
        group_id=KAFKA_GROUP_ID,
        auto_offset_reset="earliest",  # if worker terminated, process old data on new worker first
    )

    await consumer.start()
    log.info("ML worker listening to topic '%s' on '%s'", KAFKA_TOPIC, KAFKA_BROKER_URL)

    active_systems = {}
    active_buffers = {}

    try:
        while not _shutdown_event.is_set():
            try:
                msg = await asyncio.wait_for(consumer.getone(), timeout=1.0)
                payload = msg.value
                
                # 1. แกะ patient_id ออกมาก่อนเลย (สำคัญมากสำหรับการแยกคน)
                try:
                    patient_id = int(msg.key.decode('utf-8')) if msg.key else 1
                except:
                    patient_id = 1

                if isinstance(payload, dict) and payload.get("command") == "START_SESSION":
                    # แอปส่ง {"command": "START_SESSION", "patient_id": 1} มา
                    cmd_patient_id = payload.get("patient_id", patient_id)
                    log.info(f"รับคำสั่ง START_SESSION: รีเซ็ตโมเดลและล้างท่อสำหรับ Patient {cmd_patient_id}")
                    
                    # รีเซ็ตระบบใหม่เอี่ยมให้กับคนไข้คนนี้
                    active_systems[cmd_patient_id] = GaitSystem()
                    active_buffers[cmd_patient_id] = []
                    continue 

                # 3. เตรียม System และ Buffer ประจำตัวคนไข้
                # (ถ้าเพิ่งส่งข้อมูลมาครั้งแรก และยังไม่มีชื่อในระบบ ให้สร้างใหม่)
                if patient_id not in active_systems:
                    active_systems[patient_id] = GaitSystem()
                    active_buffers[patient_id] = []
                
                # ดึงตัวแทนของคนไข้รายนี้ออกมาทำงาน
                system = active_systems[patient_id]
                buffer = active_buffers[patient_id]

                # 4. ดึงข้อมูลก้าวเดิน (Data Ingestion)
                samples = []
                if isinstance(payload, dict):
                    raw = payload.get("gyro_z")
                    if isinstance(raw, list):
                        samples = raw
                    elif isinstance(raw, (int, float)):
                        samples = [raw]
                elif isinstance(payload, list):
                    samples = payload
                else:
                    log.warning("Skipping malformed payload type=%s", type(payload).__name__)
                    continue

                valid_count = 0
                for v in samples:
                    try:
                        buffer.append(float(v))
                        valid_count += 1
                    except (TypeError, ValueError):
                        continue

                if valid_count == 0:
                    continue

                # 5. ประมวลผลทีละ 100 ก้อน
                while len(buffer) >= 100:
                    chunk = buffer[:100]
                    # ตัดก้อนเก่าทิ้ง
                    active_buffers[patient_id] = buffer[100:] 
                    buffer = active_buffers[patient_id]

                    result = await asyncio.to_thread(system.process_stream_chunk, chunk)

                    if result:
                        log.info(f"[Patient {patient_id}] ML Report: {result.get('type')}")
                        
                        # สร้าง JSON และเซฟลง DB
                        window_report_data = create_window_report_json(result, patient_id, system)
                        anomaly_log_data = None

                        if window_report_data.get("gait_health") == "ANOMALY_DETECTED":
                            anomaly_log_data = create_anomaly_log_json(result, window_report_data["window_report_id"], patient_id)
                            log.warning(f"[Patient {patient_id}] Anomaly Detected!")

                        await asyncio.to_thread(save_to_database, window_report_data, anomaly_log_data)

            except TimeoutError:
                continue

    except Exception as e:
        log.error(f"Worker crashed: {e}")
    finally:
        log.info("Closing Kafka Consumer. Leaving group ...")
        await consumer.stop()
        log.info("Worker stopped.")


if __name__ == "__main__":
    asyncio.run(run_worker())
