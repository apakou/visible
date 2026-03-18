from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.models import InventoryLog, Owner
from app.openrouter_client import generate_summary
from app.twilio_client import send_whatsapp


async def handle(owner: Owner, parsed: dict, raw_message: str, db: Session):
    """On-demand summary: owner sends "summary", "profit this week", etc."""
    phone = owner.phone_number
    summary_text = _build_summary(owner, db, period="weekly")
    send_whatsapp(phone, summary_text)
    return {"status": "summary_sent"}


def send_scheduled_summary(owner: Owner, db: Session):
    """Called by APScheduler every Sunday at 7pm for all active owners."""
    summary_text = _build_summary(owner, db, period="weekly")
    send_whatsapp(owner.phone_number, summary_text)


def _build_summary(owner: Owner, db: Session, period: str = "weekly") -> str:
    """Aggregate inventory_log data and generate AI summary via OpenRouter."""
    days = 7 if period == "weekly" else 30
    since = datetime.utcnow() - timedelta(days=days)

    logs = (
        db.query(InventoryLog)
        .filter(
            InventoryLog.owner_id == owner.id,
            InventoryLog.logged_at >= since,
        )
        .all()
    )

    if not logs:
        return f"No entries found in the last {days} days. Start logging your sales and stock!"

    revenue = (
        sum((e.stock_value_pesewas or 0) for e in logs if e.entry_type == "sale") / 100
    )
    expenses = (
        sum((e.stock_value_pesewas or 0) for e in logs if e.entry_type == "expense")
        / 100
    )
    profit = revenue - expenses
    days_logged = len(set(e.logged_at.date() for e in logs))

    owner_data = {
        "owner_name": owner.name or "Trader",
        "shop_name": owner.shop_name or "your shop",
        "period": period,
        "days": days,
        "days_logged": days_logged,
        "revenue_ghs": revenue,
        "expenses_ghs": expenses,
        "profit_ghs": profit,
        "language": owner.language_pref or "en",
    }
    return generate_summary(owner_data, period=period)
