from __future__ import annotations

import asyncio
import logging
import os
import signal
import ssl
import sys
from typing import NoReturn

import aiomqtt
from redis.asyncio import Redis
from redis.exceptions import RedisError

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
    
REDIS_URL: str = os.environ.get("REDIS_URL", "redis://localhost:6379/0")

MQTT_BROKER: str = os.environ.get("MQTT_BROKER", "localhost")
MQTT_PORT: int = _get_int_env("MQTT_PORT", 8883)
MQTT_USERNAME: str | None = os.environ.get("MQTT_USERNAME")
MQTT_PASSWORD: str | None = os.environ.get("MQTT_PASSWORD")
MQTT_USE_TLS: bool = os.environ.get("MQTT_USE_TLS", "true").lower() in {"1", "true", "yes"}

MQTT_TOPIC: str = "gait/telemetry/+"
MQTT_QOS: int = _get_int_env("MQTT_QOS", 1)

# Redis Stream tuning
STREAM_MAXLEN: int = _get_int_env("STREAM_MAXLEN", 1000)
# Approximate trimming (~) trades strict accuracy for much better write throughput
STREAM_MAXLEN_APPROX: bool = True

# Backoff parameters (seconds)
_BACKOFF_BASE: float = 1.0
_BACKOFF_CAP: float = 60.0
_BACKOFF_FACTOR: float = 2.0


# Shutdown coordination
_shutdown_event: asyncio.Event = asyncio.Event()


def _install_signal_handlers(loop: asyncio.AbstractEventLoop) -> None:
    # Register SIGINT / SIGTERM to trigger a clean shutdown.
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, _on_shutdown_signal, sig)


def _on_shutdown_signal(sig: signal.Signals) -> None:
    log.info("Received signal %s — initiating graceful shutdown", sig.name)
    _shutdown_event.set()


# Redis helper
async def _connect_redis() -> Redis:
    # Return a connected Redis client, retrying with exponential backoff.
    delay = _BACKOFF_BASE
    attempt = 0
    while True:
        attempt += 1
        try:
            client: Redis = Redis.from_url(REDIS_URL, decode_responses=False)
            await client.ping()
            log.info("Redis connected (attempt %d): %s", attempt, REDIS_URL)
            return client
        except RedisError as exc:
            log.error("Redis connection failed (attempt %d): %s — retrying in %.1fs", attempt, exc, delay)
        await asyncio.sleep(delay)
        delay = min(delay * _BACKOFF_FACTOR, _BACKOFF_CAP)


async def _xadd(redis: Redis, user_id: str, raw_payload: bytes) -> None:
    # Append a telemetry record to the user's Redis Stream.
    stream_key = f"telemetry:stream:{user_id}"
    await redis.xadd(
        stream_key,
        {"payload": raw_payload},
        maxlen=STREAM_MAXLEN,
        approximate=STREAM_MAXLEN_APPROX,
    )


# Core bridge coroutine
async def _run_bridge() -> None:
    redis: Redis = await _connect_redis()
    redis_reconnect_delay = _BACKOFF_BASE

    mqtt_reconnect_delay = _BACKOFF_BASE
    mqtt_attempt = 0

    tls_context: ssl.SSLContext | None = None
    if MQTT_USE_TLS:
        tls_context = ssl.create_default_context()

    while not _shutdown_event.is_set():
        mqtt_attempt += 1
        log.info(
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
                # Keep-alive lets the broker detect stale connections quickly
                keepalive=30,
            ) as client:
                log.info("MQTT connected — subscribing to %s (QoS %d)", MQTT_TOPIC, MQTT_QOS)
                await client.subscribe(MQTT_TOPIC, qos=MQTT_QOS)
                mqtt_reconnect_delay = _BACKOFF_BASE  # reset on success

                async for message in client.messages:
                    if _shutdown_event.is_set():
                        break

                    topic_str: str = str(message.topic)
                    parts = topic_str.split("/")

                    # topic format: gait/telemetry/<user_id>
                    if len(parts) != 3:  # noqa: PLR2004
                        log.warning("Skipping malformed topic: %s", topic_str)
                        continue

                    user_id = parts[2]
                    raw_payload: bytes = (
                        message.payload if isinstance(message.payload, bytes) else message.payload.encode()
                    )

                    # --- Redis write with inline reconnect ---
                    redis_attempt = 0
                    while True:
                        redis_attempt += 1
                        try:
                            await _xadd(redis, user_id, raw_payload)
                            redis_reconnect_delay = _BACKOFF_BASE  # reset on success
                            log.debug(
                                "XADD telemetry:stream:%s (%d bytes)",
                                user_id,
                                len(raw_payload),
                            )
                            break
                        except RedisError as exc:
                            log.error(
                                "Redis write failed (attempt %d): %s — reconnecting in %.1fs",
                                redis_attempt,
                                exc,
                                redis_reconnect_delay,
                            )
                            await asyncio.sleep(redis_reconnect_delay)
                            redis_reconnect_delay = min(redis_reconnect_delay * _BACKOFF_FACTOR, _BACKOFF_CAP)
                            try:
                                await redis.aclose()
                            except Exception:  # noqa: BLE001, S110
                                pass
                            redis = await _connect_redis()

        except aiomqtt.MqttError as exc:
            if _shutdown_event.is_set():
                break
            log.error(
                "MQTT error: %s — reconnecting in %.1fs",
                exc,
                mqtt_reconnect_delay,
            )
            await asyncio.sleep(mqtt_reconnect_delay)
            mqtt_reconnect_delay = min(mqtt_reconnect_delay * _BACKOFF_FACTOR, _BACKOFF_CAP)

    log.info("Bridge coroutine exiting cleanly")
    try:
        await redis.aclose()
    except Exception:  # noqa: BLE001, S110
        pass


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
