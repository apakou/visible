import logging

from fastapi import APIRouter, Depends, Form
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.database import get_db
from app.handlers import claim, credit, inventory, onboarding, policy, summary
from app.models import Owner
from app.openrouter_client import classify_intent
from app.twilio_client import send_whatsapp

router = APIRouter()
logger = logging.getLogger(__name__)


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
        send_whatsapp(phone, reply_text)
        return {"status": "onboarding_reply_sent"}

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
        send_whatsapp(
            phone,
            "Sorry, I did not understand that. Try: 'sold 3 shirts for GHS 90' or 'insurance status'",
        )
        return {"status": "unknown_intent"}
