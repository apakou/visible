import logging
import os

from dotenv import load_dotenv
from twilio.rest import Client

load_dotenv()

logger = logging.getLogger(__name__)

client = Client(os.getenv("TWILIO_ACCOUNT_SID"), os.getenv("TWILIO_AUTH_TOKEN"))
FROM_NUMBER = os.getenv("TWILIO_WHATSAPP_FROM")


def send_whatsapp(to: str, body: str, media_url: str = None):
    """Send a WhatsApp message via Twilio. to should be phone number like +233xxxxxxxxx"""
    to_number = to if to.startswith("whatsapp:") else f"whatsapp:{to}"
    logger.info(
        "Sending WhatsApp message via Twilio",
        extra={"to": to_number, "body_length": len(body), "has_media": bool(media_url)},
    )
    create_kwargs = {"body": body, "from_": FROM_NUMBER, "to": to_number}
    if media_url:
        create_kwargs["media_url"] = [media_url]
    message = client.messages.create(**create_kwargs)
    logger.debug(
        "WhatsApp message sent via Twilio",
        extra={"to": to_number, "sid": message.sid},
    )
    return message.sid
