from fastapi import FastAPI

from app.api.v1.endpoints.auth import router as auth_router

app = FastAPI(
    title="Gait Telemetry Orchestrator",
    version="0.1.0",
)

app.include_router(auth_router, prefix="/api/v1")


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "healthy"}
