import os
from datetime import datetime

from app.twilio_client import send_whatsapp, send_whatsapp_media

# In-memory session state (good enough for MVP)
SESSIONS = {}  # phone -> {"state": ..., "data": {...}}

# Publicly accessible base URL for serving static assets.
# Set BASE_URL in .env to your deployment URL (e.g. https://yourdomain.com)
BASE_URL = os.getenv("BASE_URL", "http://localhost:8000")
ONBOARDING_IMAGE = f"{BASE_URL}/static/images/onboarding_sellers.svg"

# ── Welcome messages ──

WELCOME_EN = (
    "Welcome to *Visbl*!\n"
    "\n"
    "We help shop owners like you build a financial record "
    "that opens the door to loans and credit.\n"
    "\n"
    "Here's how it works:\n"
    "\n"
    "1. You text us your daily sales and expenses\n"
    "2. We keep track of everything for you\n"
    "3. After 60-90 days, you get a credit profile\n"
    "4. Take that profile to a lender and access a loan\n"
    "\n"
    "Let's set you up! What is your *name*?"
)

WELCOME_TW = (
    "Akwaaba *Visbl*!\n"
    "\n"
    "Yede wo shop no akontaabu bedi wo ho adwuma "
    "na wobetumi anya loan.\n"
    "\n"
    "Sɛnea yɛyɛ no:\n"
    "\n"
    "1. Fa wo sales ne expenses brɛ me da biara\n"
    "2. Yɛde sie ma wo\n"
    "3. Nnɛda 60-90 akyi, wobɛnya wo credit profile\n"
    "4. Fa kɔ bank na wobɛnya loan\n"
    "\n"
    "Ma yensɔ ase! Wo *din* de sɛn?"
)


def is_in_onboarding(phone: str) -> bool:
    return phone in SESSIONS


def handle_onboarding(phone: str, message: str, db) -> str:
    """Drive the onboarding state machine.

    Returns a text reply for most states. The NEW state sends the
    welcome image + message directly via Twilio and returns the
    text portion so the webhook can still log it.
    """
    session = SESSIONS.get(phone, {"state": "NEW", "data": {}})
    state = session["state"]

    if state == "NEW":
        SESSIONS[phone] = {"state": "AWAITING_NAME", "data": {}}

        # Send the welcome image with the message
        send_whatsapp_media(phone, WELCOME_EN, ONBOARDING_IMAGE)

        # Return None so webhook knows we already sent the message
        return None

    elif state == "AWAITING_NAME":
        name = message.strip().title()
        session["data"]["name"] = name
        session["state"] = "AWAITING_SHOP"
        SESSIONS[phone] = session
        return (
            f"Great to meet you, *{name}*!\n"
            f"\n"
            f"Now, what's your *shop name* and *location*?\n"
            f"\n"
            f"For example: _Kwaku Clothing, Osu_"
        )

    elif state == "AWAITING_SHOP":
        session["data"]["shop"] = message.strip()
        session["state"] = "AWAITING_LANG"
        SESSIONS[phone] = session
        return (
            "Almost done!\n"
            "\n"
            "Which language do you prefer?\n"
            "\n"
            "Reply with:\n"
            "  *1* - English\n"
            "  *2* - Twi"
        )

    elif state == "AWAITING_LANG":
        lang = "tw" if ("twi" in message.lower() or message.strip() == "2") else "en"
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

        if lang == "tw":
            return (
                "Wo ho registration no ayɛ! ✓\n"
                "\n"
                "Sɛnea wobɛyɛ da biara:\n"
                "\n"
                "  *Log sale:*\n"
                "  _Sales 340 cedis_\n"
                "\n"
                "  *Log expense:*\n"
                "  _Paid 150 cedis supplier_\n"
                "\n"
                "  *Log stock:*\n"
                "  _Received 20 shirts at GHS 15 each_\n"
                "\n"
                "Fa wo bɛn me message biara bere — yɛn nkɔ!"
            )

        return (
            "You're all set! ✓\n"
            "\n"
            "Here's what you can text me each day:\n"
            "\n"
            "  *Log a sale:*\n"
            "  _Sales 340 cedis_\n"
            "\n"
            "  *Log an expense:*\n"
            "  _Paid 150 cedis supplier_\n"
            "\n"
            "  *Log stock received:*\n"
            "  _Received 20 shirts at GHS 15 each_\n"
            "\n"
            "Just send a message anytime — I'll handle the rest!"
        )

    return "Something went wrong. Send any message to start again."
