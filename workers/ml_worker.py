import asyncio
from datetime import datetime, timedelta, timezone
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


def create_window_report_json(ml_result, patient_id, system, current_time: datetime):
    # WindowReport
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

    # case 1 : calibrate case
    if ml_result.get("type") == "status":
        status = ml_result.get("status") or "CALIBRATING"
        report["status"] = status

    # case2 : monitoring
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

        report["steps"] = system.total_steps
        report["calories"] = system.total_calories
        stride_length_m = (system.user_height_cm * 0.415) / 100
        report["distance_m"] = system.total_steps * stride_length_m

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
    return {"weight": 70.0, "height": 175.0}  # Fallback defaults


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

                # 1. Extract patient_id first
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

                # Prepare System and Buffer for the patient
                if patient_id not in active_systems:
                    profile = await get_patient_profile(patient_id)
                    active_systems[patient_id] = GaitSystem(
                        user_weight_kg=profile["weight"], user_height_cm=profile["height"]
                    )
                    active_buffers[patient_id] = []

                # Retrieve the instance for this patient to work on
                system = active_systems[patient_id]
                buffer = active_buffers[patient_id]

                # Retrieve gait data (Data Ingestion)
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

                # Process in chunks of 100
                while len(buffer) >= 100:
                    chunk = buffer[:100]
                    # Remove old chunk
                    active_buffers[patient_id] = buffer[100:]
                    buffer = active_buffers[patient_id]

                    result = await asyncio.to_thread(system.process_stream_chunk, chunk)

                    if result:
                        log.info(f"[Patient {patient_id}] ML Report: {result.get('type')}")
                        gmt7 = timezone(timedelta(hours=7))
                        current_timestamp = datetime.now(gmt7)

                        window_report_data = create_window_report_json(result, patient_id, system, current_timestamp)

                        # Save to DB only when status is MONITORING
                        if window_report_data["status"] == "MONITORING":
                            anomaly_log_data = None

                            if window_report_data.get("gait_health") == "ANOMALY_DETECTED":
                                anomaly_log_data = create_anomaly_log_json(result, patient_id)  # create log
                                log.info("Anomaly detected saving to anomaly log")
                                patient_email = await get_patient_email(patient_id)
                                # send email
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

                                    def _log_email_task_result(task: asyncio.Task, pid=patient_id) -> None:
                                        try:
                                            task.result()
                                        except Exception as e:
                                            log.error(f"[Patient {pid}] Failed to send anomaly alert email: {e}")

                                    email_task.add_done_callback(_log_email_task_result)
                                except Exception as e:
                                    log.error(f"[Patient {patient_id}] Failed to schedule anomaly alert email: {e}")

                            await asyncio.to_thread(save_to_database, window_report_data, anomaly_log_data)

                        else:
                            # Skip saving if in CALIBRATING phase
                            log.info(f"[Patient {patient_id}] Calibrating phase... Skipping DB save")

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
                continue  # Skip bad chunk and keep listening

    except Exception as e:
        log.error(f"Worker crashed: {e}")
    finally:
        log.info("Closing Kafka Consumer. Leaving group ...")
        await consumer.stop()
        log.info("Worker stopped.")


if __name__ == "__main__":
    asyncio.run(run_worker())
