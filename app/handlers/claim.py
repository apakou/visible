import uuid
from datetime import date

from sqlalchemy.orm import Session

from app.models import Claim, InventoryDeclaration, Owner, Policy
from app.twilio_client import send_whatsapp


async def handle_initiate(owner: Owner, parsed: dict, raw_message: str, db: Session):
    phone = owner.phone_number
    event_type = parsed.get("event_type", "unknown")

    # Get active policy
    policy = (
        db.query(Policy)
        .filter(Policy.owner_id == owner.id, Policy.status == "active")
        .first()
    )

    if not policy:
        send_whatsapp(
            phone,
            "You do not have an active Visbl Shield policy. Type 'insurance' to learn more.",
        )
        return {"status": "no_policy"}

    # Get most recent declaration as pre-loss baseline
    declaration = (
        db.query(InventoryDeclaration)
        .filter(InventoryDeclaration.owner_id == owner.id)
        .order_by(InventoryDeclaration.declaration_month.desc())
        .first()
    )

    declared_value = float(declaration.total_stock_value_ghs) if declaration else 0
    verified_loss = int(declared_value * 100)  # Convert GHS to pesewas
    payout = min(verified_loss, policy.payout_cap_pesewas)

    # Create claim record
    claim_ref = f"VBL-{date.today().year}-{str(uuid.uuid4())[:5].upper()}"
    claim = Claim(
        policy_id=policy.id,
        owner_id=owner.id,
        claim_reference=claim_ref,
        event_type=event_type,
        event_date=date.today(),
        declared_loss_pesewas=verified_loss,
        verified_loss_pesewas=verified_loss,
        payout_pesewas=payout,
        status="initiated",
        supporting_declaration_id=declaration.id if declaration else None,
    )
    db.add(claim)
    db.commit()

    payout_ghs = payout / 100
    stock_ghs = declared_value
    msg = (
        f"Claim initiated. Reference: {claim_ref}\n"
        f"Event: {event_type.capitalize()} - {date.today().strftime('%d %B %Y')}\n"
        f"Last declared stock value: GHS {stock_ghs:,.2f}\n"
        f"Maximum payout under your policy: GHS {payout_ghs:,.2f}\n"
        f"We are reviewing your claim. You will hear from us within 5 business days."
    )
    send_whatsapp(phone, msg)
    return {"status": "claim_initiated", "claim_ref": claim_ref}
