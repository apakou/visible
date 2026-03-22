import logging
import os

from dotenv.main import load_dotenv
from fastapi import Depends, FastAPI, Form, Request, Response
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session
from twilio.twiml.messaging_response import MessagingResponse

import state
from app.DB.database import SessionLocal, engine
from app.DB.models import Base, Owner
from app.handlers import onboarding
from app.handlers.flow_exchange import router as flow_router
from app.handlers.whatsapp_manager import send_typing_indicator
from app.logging_config import setup_logging

setup_logging()
logger = logging.getLogger(__name__)

Base.metadata.create_all(bind=engine)

app = FastAPI()
app.mount("/assets", StaticFiles(directory="assets"), name="assets")
app.include_router(flow_router)

load_dotenv()

WHATSAPP_SECRET_KEY = os.getenv("WHATSAPP_SECRET_KEY")


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@app.get("/")
async def root():
    return {"message": "Visbl is active!"}


@app.get("/webhook")
async def verify(req: Request):
    params = req.query_params

    verify_token = params.get("hub.verify_token")
    challenge = params.get("hub.challenge")

    if verify_token == WHATSAPP_SECRET_KEY:
        return Response(content=challenge, status_code=200)

    return Response(content="Forbidden", status_code=403)


@app.post("/webhook")
async def whatsapp_webhook(request: Request, db: Session = Depends(get_db)):
    try:
        data = await request.json()

        if "object" not in data:
            return Response(status_code=400)

        logger.debug("whatsapp_webhook_payload %s", data)

        value = data["entry"][0]["changes"][0]["value"]

        # ── Status update (delivered, read, failed, sent) ──
        if "statuses" in value and "messages" not in value:
            _log_message_status(value["statuses"][0])
            return Response(status_code=200)

        # ── No messages and no statuses — unknown payload, skip ─
        if "messages" not in value:
            logger.warning("webhook_unknown_payload | keys=%s", list(value.keys()))
            return Response(status_code=200)

        # ── Incoming message ─
        message = data["entry"][0]["changes"][0]["value"]["messages"][0]
        phone = message["from"]
        msg_type = message["type"]
        message_id = message["id"]

        logger.info(
            "webhook_message_received | phone=%s type=%s message_id=%s",
            phone,
            msg_type,
            message_id,
        )
        send_typing_indicator(phone, message_id)

        # Check if owner exists in DB
        owner = db.query(Owner).filter(Owner.phone_number == phone).first()
        if owner:
            await handle_existing_owner(phone, message, owner)
            return Response(status_code=200)

        # Session management
        session = state.sessions.get(phone, {"step": "NEW"})

        incoming_text = message.get("text", {}).get("body", "").strip().lower()

        print(session, "session is here")

        if session["step"] == "NEW" or incoming_text in ["hi", "hello", "hey", "start"]:
            await onboarding.step_1_greeting_button(phone)
            print("got here o")

        return Response(content="response is here", status_code=200)

    except Exception:
        logger.exception("Error in whatsapp_webhook")
        return Response(content="Internal server error", status_code=500)


async def handle_existing_owner(phone, message, owner):
    # TODO: Handle existing owner logic
    return "we will do this later"


def _log_message_status(status: dict) -> None:
    """
    Log all important fields from a WhatsApp status update.

    Possible statuses:
        sent      — message left Meta's servers
        delivered — message reached the user's device
        read      — user opened the message
        failed    — message could not be delivered
    """
    message_id = status.get("id")
    state = status.get("status")
    recipient = status.get("recipient_id")
    timestamp = status.get("timestamp")
    pricing = status.get("pricing", {})
    errors = status.get("errors", [])
    conversation = status.get("conversation", {})

    if state == "failed":
        # Log failures at ERROR with full error detail
        error_info = errors[0] if errors else {}
        logger.error(
            "message_status_failed | message_id=%s recipient=%s "
            "timestamp=%s error_code=%s error_title=%s error_message=%s",
            message_id,
            recipient,
            timestamp,
            error_info.get("code"),
            error_info.get("title"),
            error_info.get("message"),
        )
    else:
        # sent / delivered / read — log at INFO
        logger.info(
            "message_status | id=%s status=%s recipient=%s timestamp=%s "
            "billable=%s category=%s conversation_id=%s",
            message_id,
            state,
            recipient,
            timestamp,
            pricing.get("billable"),
            pricing.get("category"),
            conversation.get("id"),
        )


def _flow_response(screen: str, data: dict) -> dict:
    return {
        "screen": screen,
        "data": data,
    }


def _flow_error(message: str) -> dict:
    return {
        "screen": "ERROR",
        "data": {"error_message": message},
    }
