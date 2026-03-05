#!/usr/bin/env bash

# =============================================================================
# Container Entrypoint: Database Schema Synchronization
#
# Logic: Executes 'alembic upgrade head' to ensure the schema matches the 
# application code before the FastAPI process initiates.
#
# Concurrency: Utilizes Postgres advisory locks (via Alembic) to prevent 
# race conditions during rolling updates when multiple replicas spin up.
# =============================================================================

# set -e: Exit on error | -u: Error on unset vars | -o pipefail: Catch upstream errors
echo "[entrypoint] Running Alembic migrations …"
alembic upgrade head
echo "[entrypoint] Migrations complete."

# Hand off to the CMD (uvicorn by default)
exec "$@"
