# =============================================================================
# STAGE 1: Builder — install dependencies into a virtual env
# =============================================================================
FROM python:3.11-slim AS builder

WORKDIR /build

RUN apt-get update && \
    apt-get install -y --no-install-recommends gcc libpq-dev && \
    rm -rf /var/lib/apt/lists/*

# Create a virtual‑env so we can copy it cleanly into the runtime stage.
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# =============================================================================
# STAGE 2: Runtime — minimal image, non‑root user, immutable artifact
# =============================================================================
FROM python:3.11-slim AS runtime

# Metadata
LABEL maintainer="gait-telemetry-orchestrator" \
      description="FastAPI orchestrator for gait telemetry data" \
      org.opencontainers.image.source="https://github.com/Tinnawutnnr/gait-telemetry-orchestrator"

# Runtime‑only system deps (libpq for psycopg2, curl for healthchecks)
RUN apt-get update && \
    apt-get install -y --no-install-recommends libpq5 curl && \
    rm -rf /var/lib/apt/lists/*

# ---- Security: non‑root user ------------------------------------------------
RUN groupadd --gid 1000 appuser && \
    useradd  --uid 1000 --gid appuser --shell /bin/bash --create-home appuser

# Copy the pre‑built virtual‑env from the builder stage
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Copy application code
COPY --chown=appuser:appuser . .

# Make entrypoint executable
RUN chmod +x /app/docker-entrypoint.sh

USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD ["curl", "-f", "http://localhost:8000/health"]

ENTRYPOINT ["/app/docker-entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "4"]
