from fastapi import APIRouter, Depends, Form
from sqlalchemy.orm import Session

from app import handlers
from app.database import get_db
from app.models import Owner
from app.openrouter_client import classify_intent
from app.twilio_client import send_whatsapp

router = APIRouter()


@router.post("/webhook/whatsapp")
async def whatsapp_webhook(
    From: str = Form(...), Body: str = Form(...), db: Session = Depends(get_db)
):
    phone = From.replace("whatsapp:", "").strip()
    message = Body.strip()

    # Check if owner exists
    owner = db.query(Owner).filter(Owner.phone_number == phone).first()

    if not owner or not owner.onboarded_at:
        return await handlers.onboarding.handle(phone, message, db)

    # Classify intent
    parsed = classify_intent(message)
    intent = parsed.get("intent", "unknown")

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
        return await handler_fn(owner, parsed, message, db)
    else:
        send_whatsapp(
            phone,
            "Sorry, I did not understand that. Try: 'sold 3 shirts for GHS 90' or 'insurance status'",
        )
        return {"status": "unknown_intent"}
