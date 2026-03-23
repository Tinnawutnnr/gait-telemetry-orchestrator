import logging

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)


async def send_password_reset_email(email: str, otp: str) -> None:
    html_content = f"""
    <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; color: #333;">
        <h2>Password Reset Request</h2>
        <p>You recently requested to reset your password. Here is your One-Time Password (OTP):</p>
        <div style="background-color: #f4f4f4; padding: 15px; text-align: center; border-radius: 5px; margin: 20px 0;">
            <strong style="font-size: 24px; letter-spacing: 4px; color: #000;">{otp}</strong>
        </div>
        <p>This code will expire in 5 minutes.</p>
        <p>If you did not request a password reset, please ignore this email or contact support.</p>
    </div>
    """

    payload = {
        "from": "Perga <noreply@contact.tinnawut.codes>",
        "to": [email],
        "subject": "Your Password Reset Code",
        "html": html_content,
    }

    headers = {"Authorization": f"Bearer {settings.RESEND_API_KEY}", "Content-Type": "application/json"}

    try:
        # Use httpx for asynchronous delivery to avoid blocking the event loop
        async with httpx.AsyncClient() as client:
            response = await client.post("https://api.resend.com/emails", json=payload, headers=headers, timeout=10.0)
            response.raise_for_status()
            logger.info(f"Password reset email successfully sent to {email}")
    except httpx.HTTPStatusError as e:
        logger.error(f"HTTP error from Resend API while sending email to {email}: {e.response.text}")
    except Exception as e:
        logger.error(f"Unexpected error occurred while sending email to {email}: {str(e)}")

async def send_anomaly_alert_email(
    email: str, 
    patient_id: str, 
    anomaly_score: float, 
    root_cause_feature: str, 
    z_score: float, 
    current_val: float, 
    normal_ref: float, 
    timestamp: datetime
) -> None:
    # Send an anomaly alert email to the caretaker.

    html_content = f"""
    <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; color: #333;">
        <h2>Anomaly Detected</h2>
        <p>An anomaly has been detected in the gait of patient {patient_id}.</p>
        <p>Anomaly Score: {anomaly_score}</p>
        <p>Root Cause feature: {root_cause_feature}</p>
        <p>Z-score deviation: {z_score}</p>
        <p>Current value: {current_val}</p>
        <p>Normal reference value: {normal_ref}</p>
        <p>Timestamp: {timestamp}</p>
    </div>
    """
    
    payload = {
        "from": "Perga <noreply@contact.tinnawut.codes>",
        "to": [email],
        "subject": "Anomaly Detected in Gait",
        "html": html_content,
    }

    headers = {"Authorization": f"Bearer {settings.RESEND_API_KEY}", "Content-Type": "application/json"}

    try:
        # Use httpx for asynchronous delivery to avoid blocking the event loop
        async with httpx.AsyncClient() as client:
            response = await client.post("https://api.resend.com/emails", json=payload, headers=headers, timeout=10.0)
            response.raise_for_status()
            logger.info(f"Anomaly alert email successfully sent to {email}")
    except httpx.HTTPStatusError as e:
        logger.error(f"HTTP error from Resend API while sending email to {email}: {e.response.text}")
    except Exception as e:
        logger.error(f"Unexpected error occurred while sending email to {email}: {str(e)}")