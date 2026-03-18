import logging

from fastapi import APIRouter, Depends, Form
from sqlalchemy.orm import Session

from app import handlers
from app.database import get_db
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
    owner = db.query(Owner).filter(Owner.phone_number == phone).first()

    if not owner or not owner.onboarded_at:
        logger.info(
            "Routing message to onboarding handler",
            extra={"phone": phone, "has_owner": bool(owner)},
        )
        return await handlers.onboarding.handle(phone, message, db)

    # Classify intent
    parsed = classify_intent(message)
    intent = parsed.get("intent", "unknown")
    logger.info(
        "Classified incoming message intent",
        extra={"phone": phone, "intent": intent, "confidence": parsed.get("confidence")},
    )

    dispatch = {
        "stock_in": handlers.inventory.handle_stock_in,
        "sale": handlers.inventory.handle_sale,
        "expense": handlers.inventory.handle_expense,
        "cash_count": handlers.inventory.handle_cash_count,
        "summary_request": handlers.summary.handle,
        "claim_initiate": handlers.claim.handle_initiate,
        "policy_query": handlers.policy.handle_query,
        "profile_request": handlers.credit.handle,
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
                "⚠️ Something went wrong while processing your message.\n"
                "Please try again in a moment — if the problem continues, contact support.",
            )
            return {"status": "error"}
    else:
        logger.info(
            "Unknown intent from classifier",
            extra={"phone": phone, "intent": intent},
        )
        name = owner.name or "there"
        send_whatsapp(
            phone,
            f"🤔 Hey {name}, I didn't quite catch that.\n\n"
            "Here's what I can help you with:\n\n"
            "💰 *Log a sale* — `Sold 3 shirts for GHS 90`\n"
            "💸 *Log an expense* — `Paid GHS 50 for transport`\n"
            "📦 *Log stock* — `Received 20 polos at GHS 15 each`\n"
            "🏦 *Till count* — `Till 280 cedis`\n"
            "📊 *My score* — `What is my credit score?`\n"
            "🛡️ *Insurance* — `Insurance status`\n\n"
            "Just type your message and I'll figure it out! 😊",
        )
        return {"status": "unknown_intent"}
