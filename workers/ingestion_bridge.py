from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
import signal
import ssl
import sys
from typing import NoReturn

from aiokafka import AIOKafkaProducer
import aiomqtt

# Structured logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
    stream=sys.stdout,
)
log = logging.getLogger("ingestion_bridge")


# Configuration
def _get_int_env(name: str, default: int) -> int:
    # Safely parse an integer environment variable, falling back to default on error.
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        log.error(
            "Invalid integer value for environment variable %s=%r; using default %d",
            name,
            raw,
            default,
        )
        return default


KAFKA_BROKER_URL: str = os.environ.get("KAFKA_BROKER_URL", "localhost:9092")
KAFKA_TOPIC: str = os.environ.get("KAFKA_TOPIC", "raw-gait-telemetry")
KAFKA_GROUP_ID: str = os.environ.get("KAFKA_GROUP_ID", "gait_data_consumers")


MQTT_BROKER: str = os.environ.get("MQTT_BROKER", "localhost")
MQTT_PORT: int = _get_int_env("MQTT_PORT", 8883)
MQTT_USERNAME: str | None = os.environ.get("MQTT_USERNAME")
MQTT_PASSWORD: str | None = os.environ.get("MQTT_PASSWORD")
MQTT_USE_TLS: bool = os.environ.get("MQTT_USE_TLS", "true").lower() in {"1", "true", "yes"}

MQTT_TOPIC: str = "gait/telemetry/+"
MQTT_QOS: int = _get_int_env("MQTT_QOS", 1)


# Backoff parameters (seconds)
_BACKOFF_BASE: float = 1.0
_BACKOFF_CAP: float = 60.0
_BACKOFF_FACTOR: float = 2.0
MAX_MQTT_RETRIES: int = 5


# Shutdown coordination
_shutdown_event: asyncio.Event = asyncio.Event()


def _install_signal_handlers(loop: asyncio.AbstractEventLoop) -> None:
    # Register SIGINT / SIGTERM to trigger a clean shutdown.
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, _on_shutdown_signal, sig)


def _on_shutdown_signal(sig: signal.Signals) -> None:
    log.info("Received signal %s — initiating graceful shutdown", sig.name)
    _shutdown_event.set()


async def _interruptible_sleep(delay: float) -> bool:
    # Sleep up to *delay* seconds. Return True immediately if shutdown is requested.
    try:
        await asyncio.wait_for(_shutdown_event.wait(), timeout=delay)
        return True
    except TimeoutError:
        return False


async def _run_bridge() -> None:
    health_file = Path("/tmp/bridge_healthy")  # noqa: S108

    producer: AIOKafkaProducer | None = None
    delay = _BACKOFF_BASE
    attempt = 0
    while not _shutdown_event.is_set():
        attempt += 1
        try:
            producer = AIOKafkaProducer(
                bootstrap_servers=KAFKA_BROKER_URL,
                acks="all",  # Strong durability
                linger_ms=5,  # Small batching for throughput
            )
            await producer.start()
            log.info("Kafka producer connected (attempt %d): %s", attempt, KAFKA_BROKER_URL)
            break
        except Exception as exc:
            log.error("Kafka connection failed (attempt %d): %s — retrying in %.1fs", attempt, exc, delay)
            if await _interruptible_sleep(delay):
                return
            delay = min(delay * _BACKOFF_FACTOR, _BACKOFF_CAP)

    mqtt_reconnect_delay = _BACKOFF_BASE
    mqtt_attempt = 0

    tls_context: ssl.SSLContext | None = None
    if MQTT_USE_TLS:
        tls_context = ssl.create_default_context()

    while not _shutdown_event.is_set():
        if mqtt_attempt >= MAX_MQTT_RETRIES:
            log.error("Critical: Failed to connect to MQTT after %d attempts. Exiting.", MAX_MQTT_RETRIES)
            break

        mqtt_attempt += 1
        log.debug(
            "Connecting to MQTT broker %s:%d (attempt %d, TLS=%s)",
            MQTT_BROKER,
            MQTT_PORT,
            mqtt_attempt,
            MQTT_USE_TLS,
        )
        try:
            async with aiomqtt.Client(
                hostname=MQTT_BROKER,
                port=MQTT_PORT,
                username=MQTT_USERNAME,
                password=MQTT_PASSWORD,
                tls_context=tls_context,
                keepalive=30,
            ) as client:
                log.info("MQTT connected — subscribing to %s (QoS %d)", MQTT_TOPIC, MQTT_QOS)
                try:
                    await client.subscribe(MQTT_TOPIC, qos=MQTT_QOS)
                    log.info("Successfully subscribed to %s", MQTT_TOPIC)
                except aiomqtt.MqttError as exc:
                    log.error("Failed to subscribe to %s: %s", MQTT_TOPIC, exc)
                    break

                mqtt_reconnect_delay = _BACKOFF_BASE
                mqtt_attempt = 0
                msg_iter = client.messages.__aiter__()

                while not _shutdown_event.is_set():
                    try:
                        message = await asyncio.wait_for(msg_iter.__anext__(), timeout=1.0)
                    except TimeoutError:
                        # No message received in the last second, but connection is healthy.
                        # Touch the health file and continue.
                        health_file.touch(exist_ok=True)
                        continue
                    except StopAsyncIteration:
                        break

                    topic_str: str = str(message.topic)
                    parts = topic_str.split("/")

                    if len(parts) != 3:
                        log.warning("Skipping malformed topic: %s", topic_str)
                        continue

                    user_id = parts[2]

                    # Send raw bytes directly to Kafka
                    raw_payload: bytes = (
                        message.payload if isinstance(message.payload, bytes) else str(message.payload).encode()
                    )

                    # Fire-and-forget for lowest latency; use send_and_wait for strict durability
                    # Here, we use send_and_wait for at-least-once delivery and ordering per user
                    try:
                        await producer.send_and_wait(KAFKA_TOPIC, value=raw_payload, key=user_id.encode())
                        log.debug(
                            "Sent to Kafka: user=%s, bytes=%d",
                            user_id,
                            len(raw_payload),
                        )
                        # Touch the health file on successful processing of each message to indicate liveness.
                        health_file.touch(exist_ok=True)
                    except Exception as exc:
                        log.error("Kafka send failed for user_id=%s: %s", user_id, exc)

        except asyncio.CancelledError:
            log.info("Bridge cancelled — shutting down")
            break
        except aiomqtt.MqttError as exc:
            if _shutdown_event.is_set():
                break
            log.error(
                "MQTT error: %s — reconnecting in %.1fs",
                exc,
                mqtt_reconnect_delay,
            )
            if await _interruptible_sleep(mqtt_reconnect_delay):
                break
            mqtt_reconnect_delay = min(mqtt_reconnect_delay * _BACKOFF_FACTOR, _BACKOFF_CAP)

    log.info("Bridge coroutine exiting cleanly")

    # Graceful shutdown of Kafka producer
    if producer is not None:
        try:
            await producer.stop()
            log.info("Kafka producer stopped cleanly")
        except Exception:
            log.warning("Error while stopping Kafka producer", exc_info=True)


# Entry point
def main() -> NoReturn:
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    _install_signal_handlers(loop)
    try:
        loop.run_until_complete(_run_bridge())
    finally:
        loop.run_until_complete(loop.shutdown_asyncgens())
        loop.close()
        log.info("Event loop closed — bridge stopped")
    sys.exit(0)


if __name__ == "__main__":
    main()
