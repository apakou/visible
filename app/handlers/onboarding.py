from datetime import datetime

# In-memory session state (good enough for MVP)
SESSIONS = {}  # phone -> {"state": ..., "data": {...}}

WELCOME_EN = """Hi! Welcome to Visbl 👋

I help you track your shop's sales and build a financial record that can help you access a loan.

It takes 60–90 days of daily logging. After that, I generate a credit profile you can take to a lender.

To get started — what's your name?"""

WELCOME_TW = """Akwaaba! Me din de Visbl 👋

Mede wo shop no akontaabu ma wo na mebɔ hɔ sɛ wobɛnya loan.

Wohia nnɛda 60-90 bio a wode akyerɛ me wo sales. Afei no, mebɛma wo krataa a wobɛtumi de kɔ bank.

Sɛ yɛresɔ ase — wo din de sɛn?"""


def is_in_onboarding(phone: str) -> bool:
    return phone in SESSIONS


def handle_onboarding(phone: str, message: str, db) -> str:
    session = SESSIONS.get(phone, {"state": "NEW", "data": {}})
    state = session["state"]

    if state == "NEW":
        SESSIONS[phone] = {"state": "AWAITING_NAME", "data": {}}
        return WELCOME_EN

    elif state == "AWAITING_NAME":
        session["data"]["name"] = message.strip()
        session["state"] = "AWAITING_SHOP"
        SESSIONS[phone] = session
        return f"Nice to meet you, {message.strip()}! 🙏\n\nWhat's your shop name and where is it? (e.g. 'Kwaku Clothing, Osu')"

    elif state == "AWAITING_SHOP":
        session["data"]["shop"] = message.strip()
        session["state"] = "AWAITING_LANG"
        SESSIONS[phone] = session
        return "Last one — do you prefer English or Twi?\n\nReply *English* or *Twi*"

    elif state == "AWAITING_LANG":
        lang = "tw" if "twi" in message.lower() else "en"
        data = session["data"]

        from app.models import Owner

        owner = Owner(
            phone_number=phone,
            name=data.get("name"),
            shop_name=data.get("shop"),
            language_pref=lang,
            onboarded_at=datetime.utcnow(),
        )
        db.add(owner)
        db.commit()

        # Clear session
        del SESSIONS[phone]

        return (
            f"You're registered! ✓\n\n"
            f"Each day, just send me your sales like:\n"
            f"*Sales 340 cedis*\n\n"
            f"Or expenses like:\n"
            f"*Paid 150 cedis supplier*\n\n"
            f"I'll handle the rest. Let's go! 💪"
        )

    return "Something went wrong. Send any message to start again."
