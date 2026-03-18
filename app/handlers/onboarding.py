import logging
import os
from datetime import datetime

from app.twilio_client import send_whatsapp

logger = logging.getLogger(__name__)

# In-memory session state (good enough for MVP)
SESSIONS = {}  # phone -> {"state": ..., "data": {...}}

# ── Redesigned onboarding messages ────────────────────────────────

WELCOME_EN = """\
👋 *Hi! Welcome to Visbl.*

I help market traders like you:
  📦 Track daily sales & expenses
  📈 Build a credit record for loans
  🛡️ Protect your stock with insurance

It takes just *60–90 days* of daily logging — then I generate a credit profile you can take to a lender.

👇 *Let's start — what's your name?*"""

WELCOME_TW = """\
👋 *Akwaaba! Visbl de no mo.*

Mede wo shop no akontaabu ma wo:
  📦 Siesie wo sales & expenses
  📈 Bɔ ho sɛ wobɛnya loan
  🛡️ Bɔ wo stock ho ban

Wohia nnɛda *60-90* bio — na mebɛma wo krataa a wobɛtumi de kɔ bank.

👇 *Yɛresɔ ase — wo din de sɛn?*"""

def _onboarding_image_url() -> str:
    """Build the onboarding image URL at call time to pick up APP_BASE_URL correctly."""
    base = os.getenv("APP_BASE_URL", "").rstrip("/")
    return f"{base}/static/onboarding.png" if base else ""


def is_in_onboarding(phone: str) -> bool:
    return phone in SESSIONS


async def handle(phone: str, message: str, db) -> dict:
    """Async entry point used by the webhook dispatcher."""
    # Capture state before processing to decide if this is the very first contact
    is_first_contact = phone not in SESSIONS

    reply = handle_onboarding(phone, message, db)

    # On first contact, send the welcome image alongside the message (when APP_BASE_URL is configured)
    image_url = _onboarding_image_url()
    if is_first_contact and image_url:
        send_whatsapp(phone, reply, media_url=image_url)
    else:
        send_whatsapp(phone, reply)

    return {"status": "onboarding", "reply": reply}


def handle_onboarding(phone: str, message: str, db) -> str:
    session = SESSIONS.get(phone, {"state": "NEW", "data": {}})
    state = session["state"]

    if state == "NEW":
        SESSIONS[phone] = {"state": "AWAITING_NAME", "data": {}}
        return WELCOME_EN

    elif state == "AWAITING_NAME":
        name = message.strip()
        session["data"]["name"] = name
        session["state"] = "AWAITING_SHOP"
        SESSIONS[phone] = session
        return (
            f"Great to meet you, *{name}*! 🙏\n\n"
            "What's your *shop name* and where is it?\n"
            "_e.g. Kwaku Clothing, Osu_"
        )

    elif state == "AWAITING_SHOP":
        session["data"]["shop"] = message.strip()
        session["state"] = "AWAITING_LANG"
        SESSIONS[phone] = session
        return (
            "Almost there! 🎉\n\n"
            "Do you prefer *English* or *Twi*?\n\n"
            "Reply *1* for English  🇬🇧\n"
            "Reply *2* for Twi  🇬🇭"
        )

    elif state == "AWAITING_LANG":
        lang = "tw" if message.strip() in ("2", "twi", "Twi") else "en"
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

        del SESSIONS[phone]

        return (
            f"✅ *You're all set, {data.get('name')}!*\n\n"
            "Here's how to log your day:\n\n"
            "💰 *Sales* — `Sales 340 cedis`\n"
            "💸 *Expenses* — `Paid 150 cedis supplier`\n"
            "📦 *Stock in* — `Received 20 shirts at GHS 15 each`\n"
            "🏦 *Till count* — `Till 280 cedis`\n\n"
            "That's it — I handle the rest. *Let's go!* 💪"
        )

    return "Something went wrong. Send any message to start again."
