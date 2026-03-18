from datetime import datetime
import asyncio

# In-memory session state (good enough for MVP)
SESSIONS = {}  # phone -> {"state": ..., "data": {...}}

WELCOME_EN = """\
👋 *Welcome to Visbl!*

I'm your shop's money tracker on WhatsApp. Here's how I help you:

📊 Track your *daily sales & expenses*
💳 Build a *credit profile* lenders trust
🏦 Unlock access to a *business loan*

After just 60–90 days of simple daily logs you'll have a financial record you can take to any bank.

*What's your name?* 😊"""

WELCOME_TW = """\
👋 *Akwaaba Visbl so!*

Meyɛ wo shop no akontaabufoɔ wɔ WhatsApp so. Mede woboa sɛ:

📊 Kyerɛ wo *da biara sales ne expenses*
💳 Bɔ *credit profile* a lenders bɛgye to mu
🏦 Boa wo sɛ wobɛnya *business loan*

Wɔ nnɛda 60–90 akyi a wode akyerɛ me wo sales, wɔbɛma wo financial record a wobɛtumi de kɔ bank biara.

*Wo din de sɛn?* 😊"""


def is_in_onboarding(phone: str) -> bool:
    return phone in SESSIONS


async def handle(phone: str, message: str, db) -> dict:
    from app.openrouter_client import get_onboarding_image_url
    from app.twilio_client import send_whatsapp

    session = SESSIONS.get(phone, {"state": "NEW", "data": {}})
    state = session["state"]

    if state == "NEW":
        SESSIONS[phone] = {"state": "AWAITING_NAME", "data": {}}
        # Run blocking image generation off the event loop to avoid stalling other requests.
        image_url = await asyncio.to_thread(get_onboarding_image_url)
        send_whatsapp(phone, WELCOME_EN, media_url=image_url)
        return {"status": "onboarding_started"}

    elif state == "AWAITING_NAME":
        name = message.strip()
        session["data"]["name"] = name
        session["state"] = "AWAITING_SHOP"
        SESSIONS[phone] = session
        send_whatsapp(
            phone,
            f"Great to meet you, *{name}!* 🙏\n\n"
            f"What's your *shop name* and *location*?\n\n"
            f"_(e.g. Kwame Clothing, Osu)_",
        )
        return {"status": "awaiting_shop"}

    elif state == "AWAITING_SHOP":
        session["data"]["shop"] = message.strip()
        session["state"] = "AWAITING_LANG"
        SESSIONS[phone] = session
        send_whatsapp(
            phone,
            "Almost there! 🎯\n\n"
            "Last question — do you prefer to chat in *English* or *Twi*?\n\n"
            "Reply *English* or *Twi* 👇",
        )
        return {"status": "awaiting_lang"}

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

        del SESSIONS[phone]

        name = data.get("name", "")
        send_whatsapp(
            phone,
            f"You're all set, *{name}!* ✅\n\n"
            f"Here's how to log with me:\n\n"
            f"💰 *Log a sale:*\n_Sold 3 bags for GHS 180_\n\n"
            f"📦 *Log an expense:*\n_Paid GHS 200 for stock_\n\n"
            f"📊 *Check your summary:*\n_Summary_\n\n"
            f"Just send me a message anytime — I'll handle the rest! 💪\n\n"
            f"Start logging today and you'll be *loan-ready in 60–90 days!* 🚀",
        )
        return {"status": "onboarding_complete"}

    send_whatsapp(phone, "Something went wrong. Send any message to start again.")
    return {"status": "error"}

