from app.claude_client import parse_message

from app.handlers.cash_count import handle_cash_count
from app.handlers.expense import handle_expense
from app.handlers.onboarding import handle_onboarding, is_in_onboarding
from app.handlers.sales import handle_sale
from app.models import Owner


def route_message(phone: str, message: str, db) -> str:
    """Central router — decide what to do with every inbound message."""

    owner = db.query(Owner).filter(Owner.phone_number == phone).first()

    # Onboarding: new user OR mid-onboarding
    if not owner or is_in_onboarding(phone):
        return handle_onboarding(phone, message, db)

    # Parse intent with Claude
    parsed = parse_message(message)
    intent = parsed.get("intent", "unknown")

    if intent == "sale":
        return handle_sale(owner, parsed, message, db)
    elif intent == "expense":
        return handle_expense(owner, parsed, message, db)
    elif intent == "cash_count":
        return handle_cash_count(owner, parsed, message, db)
    elif intent == "summary_request":
        return "Summary coming — working on this! (M4)"
    elif intent == "profile_request":
        return "Credit profile feature coming soon! (M5)"
    else:
        return (
            "I didn't quite get that — can you try again?\n\n"
            "Examples:\n"
            "• *Sales 340 cedis*\n"
            "• *Paid 150 cedis supplier*\n"
            "• *Till 280 cedis*"
        )
