from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.models import InventoryLog, Owner
from app.twilio_client import send_whatsapp


# ─────────────────────────────────────────────────────────────────
# STOCK IN  — owner received new goods into the shop
# Triggered by intent: "stock_in"
# Example message: "Received 20 polo shirts at GHS 15 each"
# ─────────────────────────────────────────────────────────────────
async def handle_stock_in(owner: Owner, parsed: dict, raw_message: str, db: Session):
    phone = owner.phone_number
    quantity = parsed.get("quantity") or 0
    unit_cost = int((parsed.get("amount_ghs") or 0) * 100)  # GHS → pesewas
    product = parsed.get("product_name") or "goods"
    category = parsed.get("product_category") or "other"
    stock_value = quantity * unit_cost  # pre-loss record

    entry = InventoryLog(
        owner_id=owner.id,
        entry_type="stock_in",
        product_name=product,
        product_category=category,
        quantity=quantity,
        unit_cost_pesewas=unit_cost,
        stock_value_pesewas=stock_value,
        raw_message=raw_message,
        parse_confidence=parsed.get("confidence", 0.0),
    )
    db.add(entry)
    db.commit()

    value_ghs = stock_value / 100
    send_whatsapp(
        phone,
        f"Stock logged ✓\n"
        f"{quantity}x {product} ({category}) @ GHS {unit_cost / 100:.2f} each\n"
        f"Stock value added: GHS {value_ghs:,.2f}\n"
        f"This updates your insurance record.",
    )
    return {"status": "stock_in_logged", "stock_value_ghs": value_ghs}


# ─────────────────────────────────────────────────────────────────
# SALE — owner sold goods to a customer
# Triggered by intent: "sale"
# Example message: "Sold 3 pairs of jeans for GHS 120 total"
# ─────────────────────────────────────────────────────────────────
async def handle_sale(owner: Owner, parsed: dict, raw_message: str, db: Session):
    phone = owner.phone_number
    amount_ghs = parsed.get("amount_ghs") or 0
    quantity = parsed.get("quantity")
    product = parsed.get("product_name") or parsed.get("description") or "goods"
    category = parsed.get("product_category") or "other"
    unit_price = (
        int((amount_ghs / quantity) * 100) if quantity else int(amount_ghs * 100)
    )

    entry = InventoryLog(
        owner_id=owner.id,
        entry_type="sale",
        product_name=product,
        product_category=category,
        quantity=quantity,
        unit_price_pesewas=unit_price,
        stock_value_pesewas=int(amount_ghs * 100),
        raw_message=raw_message,
        parse_confidence=parsed.get("confidence", 0.0),
    )
    db.add(entry)
    db.commit()

    # Calculate 7-day running sales total for the reply
    week_ago = datetime.utcnow() - timedelta(days=7)
    week_sales = (
        db.query(InventoryLog)
        .filter(
            InventoryLog.owner_id == owner.id,
            InventoryLog.entry_type == "sale",
            InventoryLog.logged_at >= week_ago,
        )
        .all()
    )
    week_total = sum((e.stock_value_pesewas or 0) for e in week_sales) / 100

    send_whatsapp(
        phone,
        f"Sale logged ✓\n"
        f"{quantity or ''} {product} → GHS {amount_ghs:,.2f}\n"
        f"This week so far: GHS {week_total:,.2f}",
    )
    return {"status": "sale_logged", "amount_ghs": amount_ghs}


# ─────────────────────────────────────────────────────────────────
# EXPENSE — owner paid for something (stock, transport, rent)
# Triggered by intent: "expense"
# Example message: "Paid GHS 50 for transport to Kantamanto"
# ─────────────────────────────────────────────────────────────────
async def handle_expense(owner: Owner, parsed: dict, raw_message: str, db: Session):
    phone = owner.phone_number
    amount_ghs = parsed.get("amount_ghs") or 0
    desc = parsed.get("description") or "expense"

    # Auto-classify: supplier/restock = cogs, everything else = operating
    cogs_keywords = ["supplier", "stock", "restock", "goods", "buy", "purchase"]
    category = "cogs" if any(k in desc.lower() for k in cogs_keywords) else "operating"

    entry = InventoryLog(
        owner_id=owner.id,
        entry_type="expense",
        product_name=desc,
        product_category=category,
        stock_value_pesewas=int(amount_ghs * 100),
        raw_message=raw_message,
        parse_confidence=parsed.get("confidence", 0.0),
    )
    db.add(entry)
    db.commit()

    # 7-day running expense total
    week_ago = datetime.utcnow() - timedelta(days=7)
    week_expenses = (
        db.query(InventoryLog)
        .filter(
            InventoryLog.owner_id == owner.id,
            InventoryLog.entry_type == "expense",
            InventoryLog.logged_at >= week_ago,
        )
        .all()
    )
    week_total = sum((e.stock_value_pesewas or 0) for e in week_expenses) / 100

    send_whatsapp(
        phone,
        f"Expense logged ✓\n"
        f"{desc} → GHS {amount_ghs:,.2f} ({category})\n"
        f"This week's costs so far: GHS {week_total:,.2f}",
    )
    return {"status": "expense_logged", "amount_ghs": amount_ghs, "category": category}


# ─────────────────────────────────────────────────────────────────
# CASH COUNT — end-of-day till count, validates against expected
# Triggered by intent: "cash_count"
# Example message: "Till 280 cedis" / "Sika 280 wɔ till"
# ─────────────────────────────────────────────────────────────────
async def handle_cash_count(owner: Owner, parsed: dict, raw_message: str, db: Session):
    phone = owner.phone_number
    amount_ghs = parsed.get("amount_ghs") or 0
    counted = int(amount_ghs * 100)  # pesewas

    entry = InventoryLog(
        owner_id=owner.id,
        entry_type="cash_count",
        stock_value_pesewas=counted,
        raw_message=raw_message,
        parse_confidence=parsed.get("confidence", 0.0),
    )
    db.add(entry)
    db.commit()

    # Validate: expected cash = today's sales - today's expenses
    today_start = datetime.utcnow().replace(hour=0, minute=0, second=0)
    today_logs = (
        db.query(InventoryLog)
        .filter(
            InventoryLog.owner_id == owner.id,
            InventoryLog.logged_at >= today_start,
            InventoryLog.entry_type.in_(["sale", "expense"]),
        )
        .all()
    )

    sales = sum(
        (e.stock_value_pesewas or 0) for e in today_logs if e.entry_type == "sale"
    )
    expenses = sum(
        (e.stock_value_pesewas or 0) for e in today_logs if e.entry_type == "expense"
    )
    expected = sales - expenses

    # Flag if discrepancy > 10%
    discrepancy = abs(counted - expected)
    threshold = expected * 0.10 if expected > 0 else 0

    if discrepancy <= threshold or expected == 0:
        msg = (
            f"Cash count logged: GHS {amount_ghs:,.2f} ✓\n"
            f"Matches today's expected cash."
        )
    else:
        expected_ghs = expected / 100
        msg = (
            f"Cash count logged: GHS {amount_ghs:,.2f}\n"
            f"Note: expected around GHS {expected_ghs:,.2f} based on today's sales.\n"
            f"Check for returns or unreported expenses."
        )

    send_whatsapp(phone, msg)
    return {
        "status": "cash_count_logged",
        "counted_ghs": amount_ghs,
        "expected_ghs": expected / 100,
    }
