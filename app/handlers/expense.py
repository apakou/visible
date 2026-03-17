from datetime import datetime, timedelta

from sqlalchemy import func

from app.models import Transaction


def handle_expense(owner, parsed: dict, raw_message: str, db) -> str:
    if parsed.get("confidence", 0) < 0.7:
        amount = parsed.get("amount_ghs", "?")
        return (
            f"I got GHS {amount} as an expense — is that right?\nReply *Y* to confirm."
        )

    amount_pesewas = int((parsed.get("amount_ghs") or 0) * 100)
    category = parsed.get("category") or "other"

    tx = Transaction(
        owner_id=owner.id,
        type="expense",
        amount_pesewas=amount_pesewas,
        description=parsed.get("description", "Expense"),
        raw_message=raw_message,
        category=category,
        parse_confidence=parsed.get("confidence"),
    )
    db.add(tx)
    db.commit()

    week_ago = datetime.utcnow() - timedelta(days=7)
    week_costs = (
        db.query(func.sum(Transaction.amount_pesewas))
        .filter(
            Transaction.owner_id == owner.id,
            Transaction.type == "expense",
            Transaction.logged_at >= week_ago,
        )
        .scalar()
        or 0
    )

    amount_ghs = amount_pesewas / 100
    week_ghs = week_costs / 100
    category_label = f" ({category})" if category != "other" else ""
    return f"Expense logged: GHS {amount_ghs:,.2f}{category_label} ✓\nThis week's costs: GHS {week_ghs:,.2f}"
