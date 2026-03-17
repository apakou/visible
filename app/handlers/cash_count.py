from datetime import date, datetime

from sqlalchemy import func

from app.models import Transaction


def handle_cash_count(owner, parsed: dict, raw_message: str, db) -> str:
    if parsed.get("confidence", 0) < 0.7:
        return "I didn't quite catch that cash amount — can you resend? e.g. *Till 280 cedis*"

    amount_pesewas = int((parsed.get("amount_ghs") or 0) * 100)

    tx = Transaction(
        owner_id=owner.id,
        type="cash_count",
        amount_pesewas=amount_pesewas,
        raw_message=raw_message,
        parse_confidence=parsed.get("confidence"),
    )
    db.add(tx)
    db.commit()

    # Compare against expected (today's sales - expenses)
    today = date.today()
    today_sales = (
        db.query(func.sum(Transaction.amount_pesewas))
        .filter(
            Transaction.owner_id == owner.id,
            Transaction.type == "sale",
            func.date(Transaction.logged_at) == today,
        )
        .scalar()
        or 0
    )

    today_expenses = (
        db.query(func.sum(Transaction.amount_pesewas))
        .filter(
            Transaction.owner_id == owner.id,
            Transaction.type == "expense",
            func.date(Transaction.logged_at) == today,
        )
        .scalar()
        or 0
    )

    expected = today_sales - today_expenses
    amount_ghs = amount_pesewas / 100
    expected_ghs = expected / 100
    diff_pct = abs(amount_pesewas - expected) / max(expected, 1)

    if diff_pct <= 0.10 or expected == 0:
        return f"Cash count logged: GHS {amount_ghs:,.2f} ✓ — matches expected."
    else:
        return (
            f"Cash count logged: GHS {amount_ghs:,.2f}\n"
            f"Note: expected around GHS {expected_ghs:,.2f} based on today's sales.\n"
            f"Check for returns or unreported expenses."
        )
