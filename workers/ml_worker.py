import asyncio
from datetime import UTC, datetime, timezone, timedelta
import json
import logging
import os
import signal
import time
import uuid

from aiokafka import AIOKafkaConsumer
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.models.orm import AnomalyLog, Patient, User, WindowReport
from app.services.email import send_anomaly_alert_email
from workers.realtime_processor import GaitSystem

BKK_TZ = timezone(timedelta(hours=7))

# DB connection
DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL environment variable is not set or empty; cannot initialize database engine.")

engine = create_engine(DATABASE_URL)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Setup Logging for clear Docker output
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(levelname)s] ML_WORKER — %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
)
log = logging.getLogger(__name__)

# Environment variables configuration
KAFKA_BROKER_URL = os.getenv("KAFKA_BROKER_URL")
KAFKA_TOPIC = os.getenv("KAFKA_TOPIC")
KAFKA_GROUP_ID = os.getenv("KAFKA_GROUP_ID")


def _get_float_env(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        value = float(raw)
    except ValueError:
        log.warning("Invalid %s=%r, falling back to %s", name, raw, default)
        return default
    return value if value > 0 else default


PATIENT_STATE_TTL_SECONDS = _get_float_env("PATIENT_STATE_TTL_SECONDS", 1800.0)
PATIENT_STATE_CLEANUP_INTERVAL_SECONDS = _get_float_env("PATIENT_STATE_CLEANUP_INTERVAL_SECONDS", 60.0)

system = GaitSystem()
_shutdown_event = asyncio.Event()


def save_to_database(report_dict, anomaly_dict=None):
    with SessionLocal() as db:
        try:
            new_report = WindowReport(**report_dict)
            db.add(new_report)
            db.flush()

            if anomaly_dict:
                anomaly_payload = dict(anomaly_dict)
                anomaly_payload["window_id"] = new_report.window_report_id
                anomaly_payload["timestamp"] = new_report.timestamp
                new_anomaly = AnomalyLog(**anomaly_payload)
                db.add(new_anomaly)

            db.commit()
            log.info(f"Saved WindowReport (ID: {report_dict['window_report_id']}) to DB.")

        except Exception as e:
            db.rollback()
            log.error(f"Database Insert Failed: {e}")


def create_window_report_json(ml_result, patient_id, current_time: datetime):
    report = {
        "window_report_id": str(uuid.uuid4()),
        "patient_id": patient_id,
        "timestamp": current_time,
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
        "distance_m": None,
    }

    if ml_result.get("type") == "status":
        status = ml_result.get("status") or "CALIBRATING"
        report["status"] = status

    elif ml_result.get("type") == "analysis":
        report["status"] = "MONITORING"
        report["gait_health"] = ml_result.get("gait_health")
        report["anomaly_score"] = ml_result.get("anomaly_score")

        params = ml_result.get("params", {})
        report["max_gyr_ms"] = params.get("max_gyr_ms")
        report["val_gyr_hs"] = params.get("val_gyr_hs")
        report["swing_time"] = params.get("swing_time")
        report["stance_time"] = params.get("stance_time")
        report["stride_time"] = params.get("stride_time")
        report["stride_cv"] = params.get("stride_cv")
        report["n_strides"] = params.get("n_strides")

        metrics = ml_result.get("metrics", {})
        report["steps"] = int(metrics.get("steps", 0))
        report["calories"] = float(metrics.get("calories", 0.0))
        report["distance_m"] = float(metrics.get("distance_m", 0.0))

    return report


def create_anomaly_log_json(ml_result, patient_id):
    contribution = ml_result.get("contribution", {})
    return {
        "anomaly_id": str(uuid.uuid4()),
        "patient_id": patient_id,
        "anomaly_score": ml_result.get("anomaly_score"),
        "root_cause_feature": contribution.get("feature"),
        "z_score": contribution.get("z_score"),
        "current_val": contribution.get("current_val"),
        "normal_ref": contribution.get("normal_ref"),
    }


def _get_patient_profile_sync(patient_id):
    with SessionLocal() as db:
        try:
            patient = db.scalar(select(Patient).where(Patient.id == patient_id))
            if patient:
                return {"weight": patient.weight, "height": patient.height}
        except Exception as e:
            log.error(f"Failed to fetch patient profile for {patient_id}: {e}")
    return {"weight": 70.0, "height": 175.0}


async def get_patient_profile(patient_id):
    return await asyncio.to_thread(_get_patient_profile_sync, patient_id)


def _get_patient_email_sync(patient_id):
    with SessionLocal() as db:
        try:
            return db.scalar(
                select(User.email).join(Patient, Patient.user_id == User.id).where(Patient.id == patient_id)
            )
        except Exception as e:
            log.error(f"Failed to fetch patient email for {patient_id}: {e}")
            return None


async def get_patient_email(patient_id):
    return await asyncio.to_thread(_get_patient_email_sync, patient_id)


def _signal_handler():
    log.info("Received stop signal. Gracefully shutting down...")
    _shutdown_event.set()


def _cleanup_inactive_patients(active_systems, active_buffers, active_last_seen, now_ts: float) -> int:
    stale_patient_ids = [
        patient_id
        for patient_id, last_seen_ts in active_last_seen.items()
        if (now_ts - last_seen_ts) > PATIENT_STATE_TTL_SECONDS
    ]

    for patient_id in stale_patient_ids:
        active_systems.pop(patient_id, None)
        active_buffers.pop(patient_id, None)
        active_last_seen.pop(patient_id, None)

    return len(stale_patient_ids)


async def run_worker():
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, _signal_handler)

    consumer = AIOKafkaConsumer(
        KAFKA_TOPIC,
        bootstrap_servers=KAFKA_BROKER_URL,
        value_deserializer=lambda m: json.loads(m.decode("utf-8")),
        group_id=KAFKA_GROUP_ID,
        auto_offset_reset="earliest",
    )

    await consumer.start()
    log.info("ML worker listening to topic '%s' on '%s'", KAFKA_TOPIC, KAFKA_BROKER_URL)

    active_systems = {}
    active_buffers = {}
    active_last_seen = {}
    last_cleanup_ts = time.monotonic()

    try:
        while not _shutdown_event.is_set():
            try:
                msg = await asyncio.wait_for(consumer.getone(), timeout=1.0)
                payload = msg.value
                now_ts = time.monotonic()

                if (now_ts - last_cleanup_ts) >= PATIENT_STATE_CLEANUP_INTERVAL_SECONDS:
                    evicted = _cleanup_inactive_patients(active_systems, active_buffers, active_last_seen, now_ts)
                    if evicted:
                        log.info("Evicted %s inactive patient state entries", evicted)
                    last_cleanup_ts = now_ts

                patient_id = None

                if msg.key:
                    try:
                        patient_id = int(msg.key.decode("utf-8"))
                    except (ValueError, UnicodeDecodeError, AttributeError):
                        patient_id = None

                if patient_id is None and isinstance(payload, dict):
                    raw_patient_id = payload.get("patient_id")
                    try:
                        if raw_patient_id is not None:
                            patient_id = int(raw_patient_id)
                    except (TypeError, ValueError):
                        patient_id = None

                if patient_id is None:
                    log.warning(
                        "Dropping telemetry: missing/invalid patient_id (kafka_key_present=%s, payload_type=%s)",
                        bool(msg.key),
                        type(payload).__name__,
                    )
                    continue

                if isinstance(payload, dict) and payload.get("command") == "START_SESSION":
                    cmd_patient_id = patient_id
                    log.info(
                        "Received START_SESSION cmd: resetting model and buffer for Patient %s",
                        cmd_patient_id,
                    )
                    profile = await get_patient_profile(cmd_patient_id)
                    active_systems[cmd_patient_id] = GaitSystem(
                        user_weight_kg=profile["weight"], user_height_cm=profile["height"]
                    )
                    active_buffers[cmd_patient_id] = []
                    active_last_seen[cmd_patient_id] = now_ts
                    continue

                if patient_id not in active_systems:
                    profile = await get_patient_profile(patient_id)
                    active_systems[patient_id] = GaitSystem(
                        user_weight_kg=profile["weight"], user_height_cm=profile["height"]
                    )
                    active_buffers[patient_id] = []

                system = active_systems[patient_id]
                buffer = active_buffers[patient_id]

                samples = []
                if isinstance(payload, dict):
                    raw = payload.get("gyro_z")
                    if isinstance(raw, list):
                        samples = raw
                    elif isinstance(raw, (int, float)):
                        samples = [raw]
                elif isinstance(payload, list):
                    samples = payload
                elif isinstance(payload, (int, float)):
                    samples = [payload]
                else:
                    log.warning("Skipping malformed payload type=%s", type(payload).__name__)
                    continue

                active_last_seen[patient_id] = now_ts

                valid_count = 0
                for v in samples:
                    try:
                        buffer.append(float(v))
                        valid_count += 1
                    except (TypeError, ValueError):
                        continue

                if valid_count == 0:
                    continue

                while len(buffer) >= 100:
                    chunk = buffer[:100]
                    active_buffers[patient_id] = buffer[100:]
                    buffer = active_buffers[patient_id]

                    t0_ml = time.perf_counter()
                    result = await asyncio.to_thread(system.process_stream_chunk, chunk)
                    ml_proc_ms = (time.perf_counter() - t0_ml) * 1000

                    if result:
                        now_bkk_str = datetime.now(BKK_TZ).strftime("%H:%M:%S.%f")[:-3]
                        res_type = result.get("type")

                        if res_type == "info":
                            log.info(f"[{now_bkk_str}] 🛡️ [REJECTED] {result.get('msg')} | ML Time: {ml_proc_ms:.2f}ms")
                            continue

                        current_timestamp = datetime.now(UTC)
                        window_report_data = create_window_report_json(result, patient_id, current_timestamp)
                        status_label = window_report_data["status"]

                        if status_label == "CALIBRATING":
                            progress = result.get("progress", "Waiting")
                            log.info(f"[{now_bkk_str}] ⚙️ [CALIBRATION] Progress: {progress} | ML Time: {ml_proc_ms:.2f}ms")
                            continue

                        elif status_label == "MONITORING":
                            gait_health = window_report_data.get("gait_health")
                            msg_score = f"Score: {window_report_data.get('anomaly_score', 0):.2f}"

                            if gait_health == "NORMAL":
                                log.info(f"[{now_bkk_str}] ✅ [NORMAL WALK] {msg_score} | ML Time: {ml_proc_ms:.2f}ms")
                            else:
                                anomaly_log_data = create_anomaly_log_json(result, patient_id)
                                root_cause = anomaly_log_data["root_cause_feature"]
                                log.warning(f"[{now_bkk_str}] 🚨 [ANOMALY DETECTED] {msg_score} | Cause: {root_cause} | ML Time: {ml_proc_ms:.2f}ms")

                                log.info("Anomaly detected! Sending alert email...")
                                patient_email = await get_patient_email(patient_id)
                                try:
                                    email_task = asyncio.create_task(
                                        send_anomaly_alert_email(
                                            email=patient_email,
                                            patient_id=str(patient_id),
                                            anomaly_score=anomaly_log_data["anomaly_score"],
                                            root_cause_feature=anomaly_log_data["root_cause_feature"],
                                            z_score=anomaly_log_data["z_score"],
                                            current_val=anomaly_log_data["current_val"],
                                            normal_ref=anomaly_log_data["normal_ref"],
                                            timestamp=current_timestamp,
                                        )
                                    )
                                    email_task.add_done_callback(lambda t, pid=patient_id: t.exception() and log.error(f"[Patient {pid}] Failed to send email: {t.exception()}"))
                                except Exception as e:
                                    log.error(f"[Patient {patient_id}] Failed to schedule anomaly alert email: {e}")

                            t0_db = time.perf_counter()
                            await asyncio.to_thread(save_to_database, window_report_data, anomaly_log_data if gait_health == "ANOMALY_DETECTED" else None)
                            db_save_ms = (time.perf_counter() - t0_db) * 1000
                            e2e_latency_ms = ml_proc_ms + db_save_ms

                            log.info(f"   ↳ 💾 DB Save: {db_save_ms:.2f}ms | Total E2E Latency: {e2e_latency_ms:.2f}ms")

            except TimeoutError:
                now_ts = time.monotonic()
                if (now_ts - last_cleanup_ts) >= PATIENT_STATE_CLEANUP_INTERVAL_SECONDS:
                    evicted = _cleanup_inactive_patients(active_systems, active_buffers, active_last_seen, now_ts)
                    if evicted:
                        log.info("Evicted %s inactive patient state entries", evicted)
                    last_cleanup_ts = now_ts
                continue

            except Exception as e:
                log.error(f"Error processing chunk for patient {patient_id}: {e}", exc_info=True)
                continue

    except Exception as e:
        log.error(f"Worker crashed: {e}")
    finally:
        log.info("Closing Kafka Consumer. Leaving group ...")
        await consumer.stop()
        log.info("Worker stopped.")


if __name__ == "__main__":
    asyncio.run(run_worker())