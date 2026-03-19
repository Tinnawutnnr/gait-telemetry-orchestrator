import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.core.dependencies import require_role
from app.models.orm import Patient, User
from app.schemas.mqtt_credential import MqttCredential

router = APIRouter(prefix="/mqtt-credential", tags=["mqtt-credential"])
logger = logging.getLogger(__name__)


@router.get("/me", response_model=MqttCredential)
async def get_mqtt_credential_for_patient(
    # This endpoint is only for patients.
    # The mobile app will use these credentials to publish telemetry data on behalf of the patient.
    current_user: User = Depends(require_role("patient")),
    db: AsyncSession = Depends(get_db),
) -> MqttCredential:
    logger.info("Generating MQTT credentials for user %s", current_user.username)
    patient = await db.scalar(select(Patient).where(Patient.user_id == current_user.id))

    if patient.telemetry_token is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Telemetry configuration not found. Please contact support or re-calibrate.",
        )

    return MqttCredential(
        broker_url=settings.MQTT_BROKER,
        username=settings.MQTT_PUB_USERNAME,
        password=settings.MQTT_PUB_PASSWORD,
        telemetry_token=patient.telemetry_token,
    )
