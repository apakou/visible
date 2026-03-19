import asyncio
import logging
import re

from fastapi import APIRouter, BackgroundTasks, Depends, Form
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.database import SessionLocal, get_db
from app.gemini_client import (
    download_twilio_media,
    is_supported_audio_type,
    transcribe_audio,
)
from app.handlers import claim, credit, inventory, onboarding, policy, summary
from app.models import Owner
from app.openrouter_client import classify_intent
from app.twilio_client import send_whatsapp, send_whatsapp_menu

router = APIRouter()
logger = logging.getLogger(__name__)

# ── Intent dispatch map ──

_DISPATCH = {
    "stock_in": inventory.handle_stock_in,
    "sale": inventory.handle_sale,
    "expense": inventory.handle_expense,
    "cash_count": inventory.handle_cash_count,
    "summary_request": summary.handle,
    "claim_initiate": claim.handle_initiate,
    "policy_query": policy.handle_query,
    "profile_request": credit.handle,
    "logging_help": inventory.handle_logging_help,
}


# ── Helpers ──


def _menu_text(language_pref: str = "en") -> str:
    if (language_pref or "en").lower() == "tw":
        return (
            "Paw baako (fa namba no to me):\n"
            "1. Log sale\n"
            "2. Log expense\n"
            "3. Log stock in\n"
            "4. Log cash count\n"
            "5. Insurance status\n"
            "6. Weekly summary\n"
            "7. Credit score"
        )
    return (
        "Choose one option (reply with a number):\n"
        "1. Log sale\n"
        "2. Log expense\n"
        "3. Log stock in\n"
        "4. Log cash count\n"
        "5. Insurance status\n"
        "6. Weekly summary\n"
        "7. Credit score"
    )


def _parse_menu_choice(message: str) -> str | None:
    normalized = (message or "").strip().lower()
    normalized = re.sub(r"\s+", " ", normalized)

    direct = {
        "1",
        "2",
        "3",
        "4",
        "5",
        "6",
        "7",
        "option 1",
        "option 2",
        "option 3",
        "option 4",
        "option 5",
        "option 6",
        "option 7",
    }
    if normalized in direct:
        return normalized[-1]

    return None


async def _handle_menu_choice(choice: str, owner: Owner, db: Session):
    phone = owner.phone_number

    if choice == "1":
        send_whatsapp(phone, "Great. Send your sale like: 'sales 340 cedis'")
        return {"status": "menu_choice_sale"}
    if choice == "2":
        send_whatsapp(phone, "Good. Send your expense like: 'paid 50 cedis transport'")
        return {"status": "menu_choice_expense"}
    if choice == "3":
        send_whatsapp(
            phone,
            "Perfect. Send stock-in like: 'received 20 shirts at GHS 15 each'",
        )
        return {"status": "menu_choice_stock_in"}
    if choice == "4":
        send_whatsapp(phone, "Okay. Send cash count like: 'till 280 cedis'")
        return {"status": "menu_choice_cash_count"}
    if choice == "5":
        return await policy.handle_query(owner, {"intent": "policy_query"}, "", db)
    if choice == "6":
        return await summary.handle(owner, {"intent": "summary_request"}, "", db)
    if choice == "7":
        return await credit.handle(owner, {"intent": "profile_request"}, "", db)

    send_whatsapp_menu(phone, _menu_text(owner.language_pref or "en"))
    return {"status": "menu_choice_unknown"}


async def _classify_and_dispatch(
    owner: Owner, message: str, db: Session
) -> dict:
    """Shared logic: classify intent and dispatch to the appropriate handler.

    Used by both the main webhook (text) and background voice note processing.
    Returns the handler result dict, or None for unknown intent.
    """
    phone = owner.phone_number

    # Fast path: menu choice
    choice = _parse_menu_choice(message)
    if choice:
        logger.info(
            "Routing numeric menu choice",
            extra={"phone": phone, "choice": choice},
        )
        return await _handle_menu_choice(choice, owner, db)

    # Classify intent
    parsed = classify_intent(message)
    intent = parsed.get("intent", "unknown")

    # Prevent help questions from being misrouted to credit profile flow.
    lowered_message = message.lower()
    if intent == "profile_request" and re.search(
        r"\b(how\s+do\s+i|how\s+to|help|guide|record|log|inventory|stock)\b",
        lowered_message,
    ):
        intent = "logging_help"

    logger.info(
        "Classified message intent",
        extra={"phone": phone, "intent": intent, "confidence": parsed.get("confidence")},
    )

    handler_fn = _DISPATCH.get(intent)
    if handler_fn:
        logger.info(
            "Dispatching to handler",
            extra={"phone": phone, "intent": intent, "handler": handler_fn.__name__},
        )
        result = await handler_fn(owner, parsed, message, db)
        logger.info(
            "Handler completed",
            extra={"phone": phone, "intent": intent, "status": result.get("status")},
        )
        return result

    # Unknown intent — caller handles the fallback
    return None


# ── Voice note background processing ──


def _process_voice_note(phone: str, media_url: str, media_content_type: str):
    """Background task: download, transcribe, classify, and dispatch a voice note.

    Runs after the webhook has returned 200 OK to Twilio.
    """
    logger.info("Processing voice note in background", extra={"phone": phone})

    # Step 1: Download audio from Twilio
    try:
        audio_bytes = download_twilio_media(media_url)
    except Exception:
        logger.exception("Failed to download voice note", extra={"phone": phone})
        send_whatsapp(
            phone,
            "Sorry, I couldn't download your voice note. Please try again.",
        )
        return

    # Step 2: Transcribe via Gemini
    try:
        mime_type = media_content_type.split(";")[0].strip()
        transcription = transcribe_audio(audio_bytes, mime_type)
    except Exception:
        logger.exception("Voice note transcription failed", extra={"phone": phone})
        send_whatsapp(
            phone,
            "Sorry, I couldn't understand that voice note. "
            "Please try again or type your message.",
        )
        return

    # Step 3: Handle inaudible audio
    if not transcription or transcription.strip() == "[inaudible]":
        logger.info("Voice note was inaudible", extra={"phone": phone})
        send_whatsapp(
            phone,
            "I couldn't make out what you said. "
            "Please try sending another voice note or type your message.",
        )
        return

    logger.info(
        "Voice note transcribed",
        extra={"phone": phone, "transcription_length": len(transcription)},
    )

    # Step 4: Feed transcription into the standard text pipeline
    db = SessionLocal()
    try:
        _dispatch_transcription(phone, transcription, db)
    finally:
        db.close()


def _dispatch_transcription(phone: str, message: str, db: Session):
    """Process a transcribed voice note through the standard text pipeline."""
    try:
        owner = db.query(Owner).filter(Owner.phone_number == phone).first()
    except SQLAlchemyError:
        logger.exception("DB error in voice note processing", extra={"phone": phone})
        send_whatsapp(phone, "Service is temporarily unavailable. Please try again.")
        return

    if not owner or not owner.onboarded_at:
        send_whatsapp(
            phone,
            "Please complete your setup by typing your responses. "
            "Voice notes will work after you're registered!",
        )
        return

    try:
        loop = asyncio.new_event_loop()
        try:
            result = loop.run_until_complete(
                _classify_and_dispatch(owner, message, db)
            )
        finally:
            loop.close()
    except Exception:
        logger.exception(
            "Error dispatching transcribed voice note",
            extra={"phone": phone},
        )
        send_whatsapp(
            phone,
            "Sorry, something went wrong processing your voice note. Please try again.",
        )
        return

    if result is None:
        # Unknown intent
        lang = (owner.language_pref or "en").lower()
        if lang == "tw":
            send_whatsapp(
                phone,
                "Me te wo voice note no, nanso mente aseɛ. "
                "Yɛ sɛ ka sɛ: 'sales 340 cedis' anaa 'paid 50 cedis transport'.",
            )
        else:
            send_whatsapp(
                phone,
                "I heard your voice note but couldn't match it to an action.\n\n"
                "Try saying something like:\n"
                "  'sales 340 cedis'\n"
                "  'paid 50 cedis transport'",
            )


# ── Main webhook ──


@router.post("/webhook/whatsapp")
async def whatsapp_webhook(
    background_tasks: BackgroundTasks,
    From: str = Form(...),
    Body: str = Form(""),
    NumMedia: int = Form(0),
    MediaUrl0: str | None = Form(None),
    MediaContentType0: str | None = Form(None),
    db: Session = Depends(get_db),
):
    phone = From.replace("whatsapp:", "").strip()
    message = Body.strip()

    logger.info(
        "Incoming WhatsApp webhook",
        extra={"phone": phone, "raw_length": len(message), "num_media": NumMedia},
    )

    # ── Voice note / media handling ──
    if NumMedia > 0 and MediaUrl0 and MediaContentType0:
        if not is_supported_audio_type(MediaContentType0):
            logger.info(
                "Unsupported media type received",
                extra={"phone": phone, "media_type": MediaContentType0},
            )
            send_whatsapp(
                phone,
                "I can only process voice notes right now. "
                "Please send a voice message or type your request.",
            )
            return {"status": "unsupported_media_type"}

        send_whatsapp(phone, "Got your voice note, processing...")
        background_tasks.add_task(
            _process_voice_note,
            phone=phone,
            media_url=MediaUrl0,
            media_content_type=MediaContentType0,
        )
        return {"status": "voice_note_accepted"}

    # ── Check if owner exists ──
    try:
        owner = db.query(Owner).filter(Owner.phone_number == phone).first()
    except SQLAlchemyError:
        logger.exception("Database error while loading owner", extra={"phone": phone})
        send_whatsapp(
            phone,
            "Service is temporarily unavailable. Please try again in a few minutes.",
        )
        return {"status": "db_unavailable"}

    if not owner or not owner.onboarded_at:
        logger.info(
            "Routing message to onboarding handler",
            extra={"phone": phone, "has_owner": bool(owner)},
        )
        reply_text = onboarding.handle_onboarding(phone, message, db)
        if reply_text:
            send_whatsapp(phone, reply_text)
        return {"status": "onboarding_reply_sent"}

    # ── Text message processing ──
    try:
        result = await _classify_and_dispatch(owner, message, db)
    except Exception:
        logger.exception(
            "Error while handling WhatsApp webhook",
            extra={"phone": phone},
        )
        send_whatsapp(
            phone,
            "Sorry, something went wrong while processing your message. Please try again.",
        )
        return {"status": "error"}

    if result is not None:
        return result

    # Unknown intent fallback
    logger.info(
        "Unknown intent from classifier",
        extra={"phone": phone},
    )
    if (owner.language_pref or "en").lower() == "tw":
        fallback_msg = (
            "Me werɛ aho a kakra, nanso mɛboa wo.\n\n"
            f"{_menu_text(owner.language_pref or 'en')}\n\n"
            "Anaa kyerɛw no tee, sɛ: 'sales 340 cedis'."
        )
    else:
        fallback_msg = (
            "I didn't catch that yet, but I'm here to help.\n\n"
            f"{_menu_text(owner.language_pref or 'en')}\n\n"
            "Or type it directly, for example: 'sales 340 cedis'."
        )

    send_whatsapp_menu(phone, fallback_msg)
    return {"status": "unknown_intent"}
