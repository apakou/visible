from datetime import datetime, timedelta

from sqlalchemy import func

from app.models import Transaction


def handle_sale(owner, parsed: dict, raw_message: str, db) -> str:
    if parsed.get("confidence", 0) < 0.7:
        amount = parsed.get("amount_ghs", "?")
        return f"I got GHS {amount} in sales — is that right?\nReply *Y* to confirm or send the correct amount."

    amount_pesewas = int((parsed.get("amount_ghs") or 0) * 100)

    tx = Transaction(
        owner_id=owner.id,
        type="sale",
        amount_pesewas=amount_pesewas,
        description=parsed.get("description", "Sale"),
        raw_message=raw_message,
        units_sold=parsed.get("units"),
        parse_confidence=parsed.get("confidence"),
    )
    db.add(tx)
    db.commit()

    # 7-day running total
    week_ago = datetime.utcnow() - timedelta(days=7)
    week_total = (
        db.query(func.sum(Transaction.amount_pesewas))
        .filter(
            Transaction.owner_id == owner.id,
            Transaction.type == "sale",
            Transaction.logged_at >= week_ago,
        )
        .scalar()
        or 0
    )

    amount_ghs = amount_pesewas / 100
    week_ghs = week_total / 100
    return (
        f"Sales logged: GHS {amount_ghs:,.2f} ✓\nThis week so far: GHS {week_ghs:,.2f}"
    )
