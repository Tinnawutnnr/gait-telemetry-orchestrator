from datetime import datetime
import html
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
            <strong style="font-size: 24px; letter-spacing: 4px; color: #000;">{html.escape(str(otp))}</strong>
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


FEATURE_NAME_MAP = {
    "max_gyr": "Leg Swing Speed",
    "val_gyr": "Foot Landing Force",
    "swing_time": "Time Foot is in the Air",
    "stance_time": "Time Foot is on the Ground",
    "stride_cv": "Step Consistency",
}

FEATURE_UNIT_MAP = {
    "max_gyr": " rad/s",
    "val_gyr": " rad/s",
    "swing_time": " s",
    "stance_time": " s",
    "stride_cv": "%",
}


def get_human_feature_name(feature_key: str) -> str:
    name = FEATURE_NAME_MAP.get(feature_key, feature_key)
    return html.escape(str(name))


def get_feature_unit(feature_key: str) -> str:
    unit = FEATURE_UNIT_MAP.get(feature_key, "")
    return html.escape(str(unit))


async def send_anomaly_alert_email(
    email: str,
    patient_id: str,
    root_cause_feature: str,
    anomaly_score: float,
    z_score: float,
    current_val: float,
    normal_ref: float,
    timestamp: datetime,
) -> None:

    formatted_current = round(current_val, 2)
    formatted_normal = round(normal_ref, 2)
    formatted_time = timestamp.strftime("%b %d, %Y at %I:%M %p")

    # Get human-readable feature name and unit
    human_feature_name = get_human_feature_name(root_cause_feature)
    unit_str = get_feature_unit(root_cause_feature)

    # Combine values with their units for the UI
    current_display = f"{formatted_current}{unit_str}"
    normal_display = f"{formatted_normal}{unit_str}"

    raw_diff = current_val - normal_ref
    abs_normal_ref = abs(normal_ref)

    if abs_normal_ref != 0:
        raw_percent_diff = (raw_diff / abs_normal_ref) * 100
        abs_percent_diff = abs(raw_percent_diff)
    else:
        # Avoid division by zero
        raw_percent_diff = 0
        abs_percent_diff = 0

    formatted_abs_percent = round(abs_percent_diff, 1)

    # Correct severity thresholds going from smallest to largest
    if abs_percent_diff < 5:
        badge_color = "#E9C46A"  # Yellow/Mild Warning
        severity_label = "Slight Change"
    elif abs_percent_diff < 10:
        badge_color = "#F57C00"  # Orange
        severity_label = "Noticeable Change"
    else:
        badge_color = "#D32F2F"  # Red
        severity_label = "Significant Change"

    # Determine raw direction for the sentence
    direction = "higher" if current_val > normal_ref else "lower"
    percent_text = f"This is a {formatted_abs_percent}% change ({direction} than usual)."

    # HTML Email Template (Formatted for PEP 8 / Ruff 120-char limit and stripped whitespaces)
    html_content = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <style>
            /* Data Table styles for precise spacing */
            .data-table {{ width: 100%; border-collapse: collapse; }}
            .data-table td {{ padding-bottom: 12px; vertical-align: top; }}
            .label-cell {{ font-size: 12px; color: #808080; white-space: nowrap; text-align: left; }}
            .value-cell {{ font-size: 16px; font-weight: 600; padding-top: 4px; color: #000000; text-align: left; }}
            .spacing-cell {{ width: 48px; }} /* Wider spacing between the two columns */
        </style>
    </head>
    <body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
                 background-color: #FFFFFF; margin: 0; padding: 24px;">

        <div style="max-width: 500px; margin: 0 auto; border: 1px solid #E5E5E5;
                    border-radius: 16px; overflow: hidden;">

            <div style="background-color: #4F7D81; padding: 24px; text-align: center;">
                <h2 style="color: #FFFFFF; margin: 0; font-size: 24px; font-weight: 700;">Walking Alert</h2>
            </div>

            <div style="padding: 24px; color: #000000;">
                <p style="font-size: 16px; margin-top: 0;">Hello,</p>
                <p style="font-size: 16px; color: #333333; line-height: 1.5;">
                    We detected an unusual walking pattern for <strong>Patient {html.escape(str(patient_id))}</strong>.
                </p>

                <div style="background-color: #F2F2F2; border-radius: 12px; padding: 16px; margin: 24px 0;">

                    <div style="display: inline-block; background-color: {badge_color}15; color: {badge_color};
                                padding: 4px 12px; border-radius: 12px; font-size: 12px; font-weight: 700;
                                border: 1px solid {badge_color}50; margin-bottom: 16px;">
                        {severity_label}
                    </div>

                    <p style="margin: 0 0 4px 0; font-size: 14px; color: #808080;">Primary Change</p>
                    <p style="margin: 0 0 16px 0; font-size: 18px; font-weight: 600; color: #4F7D81;">
                        {human_feature_name}
                    </p>

                    <table class="data-table" style="border-top: 1px solid #E0E0E0; padding-top: 12px; width: 100%;">
                        <tr>
                            <td class="label-cell" style="width: 40%;">Today's Value</td>
                            <td class="spacing-cell"></td>
                            <td class="label-cell">Their Normal Average</td>
                        </tr>
                        <tr>
                            <td class="value-cell">{current_display}</td>
                            <td class="spacing-cell"></td>
                            <td class="value-cell">{normal_display}</td>
                        </tr>
                    </table>

                    <p style="margin: 16px 0 0 0; font-size: 14px; color: #333333; padding-top: 12px;
                              border-top: 1px dashed #D0D0D0;">
                        <em>{percent_text}</em>
                    </p>
                </div>

                <a href="#" style="display: block; width: 100%; background-color: #4F7D81; color: #FFFFFF;
                                   text-align: center; padding: 16px 0; border-radius: 16px; text-decoration: none;
                                   font-size: 16px; font-weight: 600; margin-top: 12px;">
                    View Full Details in App
                </a>
            </div>

            <div style="background-color: #FAFAFA; padding: 16px 24px; text-align: center;
                        border-top: 1px solid #E5E5E5;">
                <p style="margin: 0; font-size: 12px; color: #808080;">
                    Recorded on {formatted_time}
                </p>
            </div>
        </div>

    </body>
    </html>
    """

    payload = {
        "from": "Perga <noreply@contact.tinnawut.codes>",
        "to": [email],
        "subject": f"Alert: {severity_label} in walking pattern for Patient {html.escape(str(patient_id))}",
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
