import asyncio
import json
import logging
import os
import signal
from aiokafka import AIOKafkaConsumer

from workers.realtime_processor import GaitSystem

#ตั้งค่า Logging ให้อ่านง่ายเวลารันใน Docker
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] ML_WORKER — %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
log = logging.getLogger(__name__)

#Configuration ของ Environment var
KAFKA_BROKER_URL = os.getenv("KAFKA_BROKER_URL")
KAFKA_TOPIC = os.getenv("KAFKA_TOPIC")
KAFKA_GROUP_ID = os.getenv("KAFKA_GROUP_ID")

system = GaitSystem()
_shutdown_event = asyncio.Event()

def _signal_handler():
    log.info("Received stop signal. Gracefully shutting down...")
    _shutdown_event.set()

async def run_worker():
    loop = asyncio.get_running_loop()
    #SIGINT = signal interrupt(from Ctrl + C), 
    for sig in (signal.SIGINT, signal.SIGTERM): #SIGTERM = signal terminate(from docker stop or else)
       #if we get SIGINT or SINGTERM
        loop.add_signal_handler(sig, _signal_handler) #dont just kill worker run func _signal_handler first

    #Kafka Consumer Config
    consumer = AIOKafkaConsumer(
        KAFKA_TOPIC,
        bootstrap_servers=KAFKA_BROKER_URL,
        value_deserializer=lambda m: json.loads(m.decode("utf-8")),
        group_id=KAFKA_GROUP_ID,
        auto_offset_reset="earliest" #if worker terminated, process old data on new worker first
    )

    await consumer.start()
    log.info("ML worker listening to topic '%s' on '%s'", KAFKA_TOPIC, KAFKA_BROKER_URL)

    buffer =[]

    try:
        while not _shutdown_event.is_set():
            try:
                #loop of waiting only 1 sec for data
                msg = await asyncio.wait_for(consumer.getone(), timeout=1.0)
                payload = msg.value

                samples = []

                if isinstance(payload, dict):
                    raw = payload.get("gyro_z")
                    if isinstance(raw, list):
                        samples = raw
                    elif isinstance(raw, (int, float)):
                        samples = [raw]
                elif isinstance(payload, list):
                    # allow direct list payloads too
                    samples = payload
                elif isinstance(payload, (int, float)):
                    samples = [payload]
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
                    log.warning("No valid gyro samples in payload")
                    continue

                # process in fixed chunks of 100 samples
                while len(buffer) >= 100:
                    chunk = buffer[:100]
                    buffer = buffer[100:]

                    result = await asyncio.to_thread(system.process_stream_chunk, chunk)

                    if result:
                        log.info("ML Report Generated: %s", result.get("type"))
                        if result.get("gait_health"):
                            log.info(
                                "Status: %s | score: %s",
                                result["gait_health"],
                                result.get("anomaly_score"),
                            )

                        # todo: save result to postgreSQL
            except asyncio.TimeoutError:
                #if no data in for 1 sec go start new loop
                continue

    except Exception as e:
        log.error(f"Worker crashed: {e}")
    finally:
        log.info("Closing Kafka Consumer. Leaving group ...")
        await consumer.stop()
        log.info("Worker stopped.")

if __name__ == "__main__":
    asyncio.run(run_worker())


    

