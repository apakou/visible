import json
from datetime import date, timedelta

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from app.database import SessionLocal
from app.models import InventoryDeclaration, InventoryLog, Owner, Policy
from app.openrouter_client import generate_declaration
from app.twilio_client import send_whatsapp

scheduler = BackgroundScheduler()


def generate_monthly_declarations():
    """Run on 1st of each month at 8am. Generate declarations for active policyholders."""
    db = SessionLocal()
    try:
        today = date.today()
        month_start = today.replace(day=1)
        last_month = (month_start - timedelta(days=1)).replace(day=1)

        active_policies = db.query(Policy).filter(Policy.status == "active").all()
        for policy in active_policies:
            owner = db.query(Owner).filter(Owner.id == policy.owner_id).first()
            logs = (
                db.query(InventoryLog)
                .filter(
                    InventoryLog.owner_id == owner.id,
                    InventoryLog.logged_at >= last_month,
                    InventoryLog.logged_at < month_start,
                )
                .all()
            )

            if not logs:
                continue

            total_value = sum(l.stock_value_pesewas or 0 for l in logs) / 100
            days_logged = len(set(l.logged_at.date() for l in logs))
            consistency = days_logged / 30.0

            breakdown = {}
            for log in logs:
                cat = log.product_category or "other"
                breakdown[cat] = breakdown.get(cat, 0) + (log.stock_value_pesewas or 0)
            breakdown_ghs = {k: v / 100 for k, v in breakdown.items()}

            inv_data = {
                "month": last_month.strftime("%B %Y"),
                "total_value_ghs": total_value,
                "breakdown": breakdown_ghs,
                "days_logged": days_logged,
                "consistency_score": consistency,
            }
            texts = generate_declaration(inv_data, owner.name or "Shop Owner")

            decl = InventoryDeclaration(
                owner_id=owner.id,
                declaration_month=last_month,
                total_stock_value_ghs=total_value,
                item_breakdown_json=json.dumps(breakdown_ghs),
                days_logged=days_logged,
                consistency_score=consistency,
                declaration_text_en=texts["en"],
                declaration_text_tw=texts["tw"],
            )
            db.add(decl)
            db.commit()

            # Notify owner
            msg = (
                f"Your monthly inventory declaration for {last_month.strftime('%B %Y')} is ready.\n"
                f"Total stock value: GHS {total_value:,.2f}\n"
                + "\n".join(
                    f"- {k.capitalize()}: GHS {v:,.2f}"
                    for k, v in breakdown_ghs.items()
                )
                + "\n\nReply CONFIRM to submit to your insurer or EDIT to make changes."
            )
            send_whatsapp(owner.phone_number, msg)
    finally:
        db.close()


scheduler.add_job(generate_monthly_declarations, CronTrigger(day=1, hour=8))


def start_scheduler():
    scheduler.start()
