import logging
import os

from dotenv import load_dotenv
from twilio.rest import Client
from twilio.base.exceptions import TwilioRestException

load_dotenv()

logger = logging.getLogger(__name__)

client = Client(os.getenv("TWILIO_ACCOUNT_SID"), os.getenv("TWILIO_AUTH_TOKEN"))
FROM_NUMBER = os.getenv("TWILIO_WHATSAPP_FROM")


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
