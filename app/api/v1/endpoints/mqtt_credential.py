import logging

from fastapi import APIRouter, Depends

from app.core.config import settings
from app.core.dependencies import require_role
from app.models.orm import User
from app.schemas.mqtt_credential import MqttCredential

router = APIRouter(prefix="/mqtt-credential", tags=["mqtt-credential"])
logger = logging.getLogger(__name__)


@router.get("/me", response_model=MqttCredential)
async def get_mqtt_credential_for_patient(
    # This endpoint is only for patients.
    # The mobile app will use these credentials to publish telemetry data on behalf of the patient.
    current_user: User = Depends(require_role("patient")),
) -> MqttCredential:
    logger.info("Generating MQTT credentials for user %s", current_user.username)
    return MqttCredential(
        broker_url=settings.MQTT_BROKER,
        username=settings.MQTT_PUB_USERNAME,
        password=settings.MQTT_PUB_PASSWORD,
    )
