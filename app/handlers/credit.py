from datetime import date, datetime, timedelta

from sqlalchemy.orm import Session

from app.models import FinancialProfile, InventoryLog, Owner
from app.twilio_client import send_whatsapp


async def handle(owner: Owner, parsed: dict, raw_message: str, db: Session):
    """On-demand credit readiness query."""
    phone = owner.phone_number
    score, breakdown = calculate_score(owner, db)
    _save_profile(owner, score, breakdown, db)
    _send_score_reply(phone, score, breakdown)
    return {"status": "credit_score_sent", "score": score}


def calculate_score(owner: Owner, db: Session) -> tuple[int, dict]:
    """Calculate credit readiness score 0-100.
    Three components:
      40% — Consistency:  days_logged / days_since_onboarding
      30% — Completeness: % of days with all 3 entry types (stock/sale/expense)
      30% — Trend:        is gross profit improving week-on-week?
    """
    all_logs = db.query(InventoryLog).filter(InventoryLog.owner_id == owner.id).all()
    if not all_logs:
        return 0, {
            "days_logged": 0,
            "days_since_onboarding": 0,
            "consistency": 0,
            "completeness": 0,
            "trend": 0,
        }

    onboarded = owner.onboarded_at or owner.created_at
    days_since = max(1, (datetime.utcnow() - onboarded).days)
    days_logged = len(set(l.logged_at.date() for l in all_logs))

    # 1. Consistency score (40%)
    consistency = min(1.0, days_logged / days_since)

    # 2. Completeness: days where all 3 types appear (30%)
    by_day: dict = {}
    for log in all_logs:
        d = log.logged_at.date()
        by_day.setdefault(d, set()).add(log.entry_type)
    complete_days = sum(
        1
        for types in by_day.values()
        if {"sale", "expense", "stock_in"}.issubset(types)
    )
    completeness = complete_days / days_logged if days_logged else 0

    # 3. Trend: compare last 2 weeks gross profit (30%)
    now = datetime.utcnow()
    w1_start, w1_end = now - timedelta(days=14), now - timedelta(days=7)
    w2_start, w2_end = now - timedelta(days=7), now

    def profit_in(start, end):
        logs = [l for l in all_logs if start <= l.logged_at <= end]
        rev = sum((l.stock_value_pesewas or 0) for l in logs if l.entry_type == "sale")
        exp = sum(
            (l.stock_value_pesewas or 0) for l in logs if l.entry_type == "expense"
        )
        return rev - exp

    p1, p2 = profit_in(w1_start, w1_end), profit_in(w2_start, w2_end)
    trend = 1.0 if p2 > p1 else (0.5 if p2 == p1 else 0.0)

    raw_score = (consistency * 0.40) + (completeness * 0.30) + (trend * 0.30)
    score = round(raw_score * 100)

    breakdown = {
        "days_logged": days_logged,
        "days_since_onboarding": days_since,
        "consistency": round(consistency, 2),
        "completeness": round(completeness, 2),
        "trend": trend,
        "week1_profit_ghs": p1 / 100,
        "week2_profit_ghs": p2 / 100,
    }
    return score, breakdown


def _send_score_reply(phone: str, score: int, breakdown: dict):
    days = breakdown["days_logged"]
    needed = max(0, 60 - days)
    trend_label = (
        "📈 improving" if breakdown["trend"] == 1.0
        else "➡️ steady" if breakdown["trend"] == 0.5
        else "📉 declining"
    )

    if score >= 65 and days >= 60:
        msg = (
            f"🎉 *Credit Readiness Score: {score}/100* ✅\n\n"
            f"You've logged for *{days} days* — your records are consistent and your profit is growing.\n\n"
            f"🏦 *You're ready!* We will generate your lender profile now."
        )
    elif days < 30:
        msg = (
            f"📊 *Your Score: {score}/100*\n\n"
            f"You are *{days} days* in — keep going! You need *{needed} more days* to qualify.\n\n"
            f"💡 *Tip:* Log your stock arrivals too, not just sales — it strengthens your record."
        )
    else:
        msg = (
            f"📊 *Your Score: {score}/100*\n\n"
            f"You've logged *{days} days* — good progress! 👍\n\n"
            f"  • Consistency:  {int(breakdown['consistency'] * 100)}%\n"
            f"  • Complete days: {int(breakdown['completeness'] * 100)}%\n"
            f"  • Profit trend:  {trend_label}\n\n"
            f"Keep logging daily. I'll check again in 2 weeks. 🗓️"
        )
    send_whatsapp(phone, msg)


def _save_profile(owner: Owner, score: int, breakdown: dict, db: Session):
    """Upsert the financial_profiles record with the latest score."""
    from app.models import FinancialProfile

    profile = (
        db.query(FinancialProfile).filter(FinancialProfile.owner_id == owner.id).first()
    )
    if not profile:
        profile = FinancialProfile(owner_id=owner.id)
        db.add(profile)

    today = date.today()
    days = breakdown.get("days_since_onboarding") if breakdown.get("days_since_onboarding") else 1
    profile.period_start = today - timedelta(days=days)
    profile.period_end = today
    profile.credit_readiness_score = score
    profile.logging_days = breakdown["days_logged"]
    profile.generated_at = datetime.utcnow()
    db.commit()
