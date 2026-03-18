from datetime import date

from sqlalchemy.orm import Session

from app.models import InventoryDeclaration, Owner, Policy
from app.twilio_client import send_whatsapp


async def handle_query(owner: Owner, parsed: dict, raw_message: str, db: Session):
    """Reply with the owner's current policy status and key details."""
    phone = owner.phone_number

    policy = (
        db.query(Policy)
        .filter(
            Policy.owner_id == owner.id,
        )
        .order_by(Policy.created_at.desc())
        .first()
    )

    if not policy:
        send_whatsapp(
            phone,
            "You do not have a Visbl Shield policy yet.\n"
            "Keep logging your inventory for 30 days and you will be eligible.\n"
            "Type 'how many days' to see your progress.",
        )
        return {"status": "no_policy"}

    # Next declaration due = 1st of next month
    today = date.today()
    if today.month == 12:
        next_decl = date(today.year + 1, 1, 1)
    else:
        next_decl = date(today.year, today.month + 1, 1)

    status_emoji = {
        "active": "✅",
        "pending": "⏳",
        "lapsed": "❌",
        "claimed": "💰",
        "cancelled": "⛔",
    }.get(policy.status, "")

    if policy.status == "pending":
        # Count how many days the owner has logged so far
        from datetime import datetime

        from app.models import InventoryLog

        logs = db.query(InventoryLog).filter(InventoryLog.owner_id == owner.id).all()
        days_logged = len(set(l.logged_at.date() for l in logs))
        days_needed = max(0, 30 - days_logged)
        send_whatsapp(
            phone,
            f"Your Visbl Shield policy is pending activation. {status_emoji}\n"
            f"You need {days_needed} more days of logging before your policy activates.\n"
            f"Keep logging daily — you're building your insurance record!",
        )
        return {"status": "pending", "days_needed": days_needed}

    send_whatsapp(
        phone,
        f"Your Visbl Shield policy {status_emoji}\n"
        f"Status:          {policy.status.capitalize()}\n"
        f"Policy number:   {policy.policy_number}\n"
        f"Monthly premium: GHS {policy.premium_pesewas / 100:,.2f}\n"
        f"Max payout:      GHS {policy.payout_cap_pesewas / 100:,.2f}\n"
        f"Coverage:        Fire, flood, theft on goods\n"
        f"Cover until:     {policy.cover_end_date or 'Not set'}\n"
        f"Next declaration due: {next_decl.strftime('%d %B %Y')}\n"
        f"Insurer:         {policy.insurer_partner or 'Pending assignment'}",
    )
    return {"status": "policy_query_answered", "policy_status": policy.status}
