import json
from datetime import date, datetime, timedelta

from sqlalchemy.orm import Session

from app.models import InventoryDeclaration, InventoryLog, Owner
from app.openrouter_client import generate_declaration
from app.twilio_client import send_whatsapp


async def handle(owner: Owner, parsed: dict, raw_message: str, db: Session):
    """Handle CONFIRM or EDIT replies to a pending declaration notification."""
    phone = owner.phone_number
    body = raw_message.strip().upper()

    # Find the most recent unconfirmed declaration for this owner
    decl = (
        db.query(InventoryDeclaration)
        .filter(
            InventoryDeclaration.owner_id == owner.id,
            InventoryDeclaration.submitted_to_insurer == False,
        )
        .order_by(InventoryDeclaration.generated_at.desc())
        .first()
    )

    if not decl:
        send_whatsapp(
            phone,
            "No pending declaration found. Your next one will be generated on the 1st of next month.",
        )
        return {"status": "no_pending_declaration"}

    if body == "CONFIRM":
        decl.submitted_to_insurer = True
        decl.submitted_at = datetime.utcnow()
        db.commit()
        send_whatsapp(
            phone,
            f"Declaration confirmed ✓\n"
            f"Your {decl.declaration_month.strftime('%B %Y')} inventory record has been submitted to your insurer.\n"
            f"Total stock value: GHS {decl.total_stock_value_ghs:,.2f}",
        )
        return {"status": "declaration_confirmed"}

    elif body == "EDIT":
        send_whatsapp(
            phone,
            "To update your declaration, please log any missing stock entries now.\n"
            "Reply CONFIRM when you are done and I will regenerate your declaration.",
        )
        return {"status": "declaration_edit_requested"}

    else:
        send_whatsapp(
            phone, "Reply CONFIRM to submit your declaration or EDIT to make changes."
        )
        return {"status": "awaiting_confirm_edit"}


def generate_for_owner(owner: Owner, target_month: date, db: Session):
    """Generate and save a monthly inventory declaration for one owner.
    Called by the APScheduler cron on the 1st of each month.
    """
    month_start = target_month.replace(day=1)
    if target_month.month == 1:
        prev_month_start = target_month.replace(
            year=target_month.year - 1, month=12, day=1
        )
    else:
        prev_month_start = target_month.replace(month=target_month.month - 1, day=1)

    logs = (
        db.query(InventoryLog)
        .filter(
            InventoryLog.owner_id == owner.id,
            InventoryLog.logged_at >= prev_month_start,
            InventoryLog.logged_at < month_start,
        )
        .all()
    )

    if not logs:
        return None  # No entries this month, skip

    total_pesewas = sum(e.stock_value_pesewas or 0 for e in logs)
    total_ghs = total_pesewas / 100
    days_logged = len(set(e.logged_at.date() for e in logs))
    consistency = round(days_logged / 30.0, 2)

    # Category breakdown
    breakdown: dict = {}
    for log in logs:
        cat = log.product_category or "other"
        breakdown[cat] = breakdown.get(cat, 0) + (log.stock_value_pesewas or 0)
    breakdown_ghs = {k: round(v / 100, 2) for k, v in breakdown.items()}

    inv_data = {
        "month": prev_month_start.strftime("%B %Y"),
        "total_value_ghs": total_ghs,
        "breakdown": breakdown_ghs,
        "days_logged": days_logged,
        "consistency_score": consistency,
        "shop_name": owner.shop_name or "Shop",
    }
    texts = generate_declaration(inv_data, owner.name or "Trader")

    decl = InventoryDeclaration(
        owner_id=owner.id,
        declaration_month=prev_month_start,
        total_stock_value_ghs=total_ghs,
        item_breakdown_json=json.dumps(breakdown_ghs),
        days_logged=days_logged,
        consistency_score=consistency,
        declaration_text_en=texts["en"],
        declaration_text_tw=texts["tw"],
    )
    db.add(decl)
    db.commit()
    db.refresh(decl)

    # Notify owner
    breakdown_lines = "\n".join(
        f"  - {cat.capitalize()}: GHS {val:,.2f}" for cat, val in breakdown_ghs.items()
    )
    send_whatsapp(
        owner.phone_number,
        f"Your {prev_month_start.strftime('%B %Y')} inventory declaration is ready:\n"
        f"Total stock value: GHS {total_ghs:,.2f}\n"
        f"{breakdown_lines}\n\n"
        f"This has been sent to your insurer. Reply CONFIRM to approve or EDIT to make changes.",
    )
    return decl
