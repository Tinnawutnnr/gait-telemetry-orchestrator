from fastapi import FastAPI

from app.api.v1.endpoints.auth import router as auth_router
from app.api.v1.endpoints.caretaker_patients import router as caretaker_patients_router
from app.api.v1.endpoints.patients import router as patients_router
from app.api.v1.endpoints.profiles import router as profiles_router

app = FastAPI(
    title="Gait Telemetry Orchestrator",
    version="0.1.0",
)

app.include_router(auth_router, prefix="/api/v1")
app.include_router(profiles_router, prefix="/api/v1")
app.include_router(patients_router, prefix="/api/v1")
app.include_router(caretaker_patients_router, prefix="/api/v1")


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "healthy"}
