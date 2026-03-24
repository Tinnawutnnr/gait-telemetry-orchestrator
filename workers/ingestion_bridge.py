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
import httpx

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


MQTT_BROKER: str = os.environ.get("MQTT_BROKER", "localhost")
MQTT_PORT: int = _get_int_env("MQTT_PORT", 8883)
MQTT_USERNAME: str | None = os.environ.get("MQTT_USERNAME")
MQTT_PASSWORD: str | None = os.environ.get("MQTT_PASSWORD")
MQTT_USE_TLS: bool = os.environ.get("MQTT_USE_TLS", "true").lower() in {"1", "true", "yes"}

MQTT_TOPIC: str = "gait/telemetry/+"
MQTT_QOS: int = _get_int_env("MQTT_QOS", 1)

API_BASE_URL: str = os.environ.get("API_BASE_URL", "http://api:8000")

# Backoff parameters (seconds)
_BACKOFF_BASE: float = 1.0
_BACKOFF_CAP: float = 60.0
_BACKOFF_FACTOR: float = 2.0
MAX_MQTT_RETRIES: int = 5

# Cache for telemetry tokens
_TOKEN_TO_USER_CACHE: dict[str, str] = {}

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


async def get_user_id_from_token(token: str) -> str | None:
    # Check cache first to avoid high API load
    if token in _TOKEN_TO_USER_CACHE:
        return _TOKEN_TO_USER_CACHE[token]

    api_url = f"{API_BASE_URL}/api/v1/patients/me/{token}"
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(api_url, timeout=5.0)
            if response.status_code == 200:
                user_id = str(response.json())
                _TOKEN_TO_USER_CACHE[token] = user_id
                log.info("Cached patient_id %s for telemetry_token %s", user_id, token)
                return user_id
            log.warning("API returned status %d for token %s", response.status_code, token)
            return None
        except httpx.HTTPError as e:
            log.error("HTTPError fetching user_id for token %s: %s", token, e)
            return None


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

    if producer is None:
        log.warning("Kafka producer was not initialized; skipping MQTT bridge startup and exiting.")
        return

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

                    telemetry_token = parts[2]

                    user_id = await get_user_id_from_token(telemetry_token)
                    if not user_id:
                        log.debug("Unresolved telemetry_token: %s - skipping", telemetry_token)
                        continue

                    # Send raw bytes directly to Kafka
                    raw_payload: bytes = (
                        message.payload if isinstance(message.payload, bytes) else str(message.payload).encode()
                    )

                    # Use send_and_wait for at-least-once delivery and ordering per user
                    if producer is None:
                        log.error(
                            "Kafka producer is not available; dropping message for user_id=%s",
                            user_id,
                        )
                        continue

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
