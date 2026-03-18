import logging
import os
import json

from dotenv import load_dotenv
from twilio.rest import Client
from twilio.base.exceptions import TwilioRestException

load_dotenv()

logger = logging.getLogger(__name__)

client = Client(os.getenv("TWILIO_ACCOUNT_SID"), os.getenv("TWILIO_AUTH_TOKEN"))
FROM_NUMBER = os.getenv("TWILIO_WHATSAPP_FROM")
MENU_CONTENT_SID = os.getenv("TWILIO_MENU_CONTENT_SID")


def send_whatsapp(to: str, body: str):
    """Send a WhatsApp message via Twilio. to should be phone number like +233xxxxxxxxx"""
    to_number = to if to.startswith("whatsapp:") else f"whatsapp:{to}"
    if not FROM_NUMBER:
        logger.error("TWILIO_WHATSAPP_FROM is not configured")
        return None

    logger.info(
        "Sending WhatsApp message via Twilio",
        extra={"to": to_number, "body_length": len(body)},
    )
    try:
        message = client.messages.create(body=body, from_=FROM_NUMBER, to=to_number)
        logger.debug(
            "WhatsApp message sent via Twilio",
            extra={"to": to_number, "sid": message.sid},
        )
        return message.sid
    except TwilioRestException as exc:
        logger.exception(
            "Twilio send failed",
            extra={"to": to_number, "status": exc.status, "code": exc.code},
        )
        return None


def send_whatsapp_media(to: str, body: str, media_url: str):
    """Send a WhatsApp message with an image/media attachment via Twilio."""
    to_number = to if to.startswith("whatsapp:") else f"whatsapp:{to}"
    if not FROM_NUMBER:
        logger.error("TWILIO_WHATSAPP_FROM is not configured")
        return None

    logger.info(
        "Sending WhatsApp media message via Twilio",
        extra={"to": to_number, "media_url": media_url},
    )
    try:
        message = client.messages.create(
            body=body,
            from_=FROM_NUMBER,
            to=to_number,
            media_url=[media_url],
        )
        logger.debug(
            "WhatsApp media message sent via Twilio",
            extra={"to": to_number, "sid": message.sid},
        )
        return message.sid
    except TwilioRestException as exc:
        logger.exception(
            "Twilio media send failed; falling back to text-only",
            extra={"to": to_number, "status": exc.status, "code": exc.code},
        )
        return send_whatsapp(to_number, body)


def send_whatsapp_menu(to: str, fallback_body: str, variables: dict | None = None):
    """Send menu using Twilio Content Template buttons when configured.

    If TWILIO_MENU_CONTENT_SID is not set or template send fails, falls back to plain text.
    """
    to_number = to if to.startswith("whatsapp:") else f"whatsapp:{to}"

    if not FROM_NUMBER:
        logger.error("TWILIO_WHATSAPP_FROM is not configured")
        return None

    if not MENU_CONTENT_SID:
        return send_whatsapp(to_number, fallback_body)

    try:
        logger.info(
            "Sending WhatsApp menu via Twilio content template",
            extra={"to": to_number, "content_sid": MENU_CONTENT_SID},
        )
        message = client.messages.create(
            from_=FROM_NUMBER,
            to=to_number,
            content_sid=MENU_CONTENT_SID,
            content_variables=json.dumps(variables or {}),
        )
        return message.sid
    except TwilioRestException as exc:
        logger.exception(
            "Twilio content template send failed; falling back to text menu",
            extra={"to": to_number, "status": exc.status, "code": exc.code},
        )
        return send_whatsapp(to_number, fallback_body)
