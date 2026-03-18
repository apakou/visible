import logging
import re

from fastapi import APIRouter, Depends, Form
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.database import get_db
from app.handlers import claim, credit, inventory, onboarding, policy, summary
from app.models import Owner
from app.openrouter_client import classify_intent
from app.twilio_client import send_whatsapp, send_whatsapp_menu

router = APIRouter()
logger = logging.getLogger(__name__)


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


@router.post("/webhook/whatsapp")
async def whatsapp_webhook(
    From: str = Form(...), Body: str = Form(...), db: Session = Depends(get_db)
):
    phone = From.replace("whatsapp:", "").strip()
    message = Body.strip()

    logger.info(
        "Incoming WhatsApp webhook",
        extra={"phone": phone, "raw_length": len(message)},
    )

    # Check if owner exists
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

    # Fast path: if user selected from known menu options, execute directly.
    choice = _parse_menu_choice(message)
    if choice:
        logger.info(
            "Routing numeric menu choice",
            extra={"phone": phone, "choice": choice},
        )
        try:
            return await _handle_menu_choice(choice, owner, db)
        except Exception:
            logger.exception("Error while handling menu choice", extra={"phone": phone})
            send_whatsapp(
                phone,
                "I could not process that option right now. Please try again.",
            )
            return {"status": "menu_choice_error"}

    # Classify intent
    try:
        parsed = classify_intent(message)
    except Exception:
        logger.exception(
            "Intent classification failed",
            extra={"phone": phone},
        )
        send_whatsapp(
            phone,
            "Service is temporarily unavailable. Please try again in a few minutes.",
        )
        return {"status": "intent_classification_failed"}

    intent = parsed.get("intent", "unknown")

    # Prevent help questions from being misrouted to credit profile flow.
    lowered_message = message.lower()
    if intent == "profile_request" and re.search(
        r"\b(how\s+do\s+i|how\s+to|help|guide|record|log|inventory|stock)\b",
        lowered_message,
    ):
        intent = "logging_help"

    logger.info(
        "Classified incoming message intent",
        extra={"phone": phone, "intent": intent, "confidence": parsed.get("confidence")},
    )

    dispatch = {
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

    handler_fn = dispatch.get(intent)
    if handler_fn:
        logger.info(
            "Dispatching to handler",
            extra={"phone": phone, "intent": intent, "handler": handler_fn.__name__},
        )
        try:
            result = await handler_fn(owner, parsed, message, db)
            logger.info(
                "Handler completed",
                extra={"phone": phone, "intent": intent, "status": result.get("status")},
            )
            return result
        except Exception:
            logger.exception(
                "Error while handling WhatsApp webhook",
                extra={"phone": phone, "intent": intent},
            )
            send_whatsapp(
                phone,
                "Sorry, something went wrong while processing your message. Please try again.",
            )
            return {"status": "error"}
    else:
        logger.info(
            "Unknown intent from classifier",
            extra={"phone": phone, "intent": intent},
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
