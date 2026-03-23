import asyncio
import base64
import json
import logging
import os
import re
import time
import uuid

import anthropic
import httpx
from dotenv import load_dotenv

import state
from app.DB.database import SessionLocal, engine
from app.DB.models import Claim, InventoryDeclaration, InventoryLog, Owner, Policy
from app.handlers.report_generator import generate_report_pdf, upload_pdf_to_whatsapp
from app.handlers.whatsapp_manager import (
    send_document,
    send_list_message,
    send_reply_buttons,
    send_text,
    send_typing_indicator,
    send_whatsapp_flow,
)
from app.logging_config import setup_logging

load_dotenv()

domain_url = os.getenv("DOMAIN_URL")
ACCESS_TOKEN = os.getenv("WHATSAPP_ACCESS_TOKEN")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
onboard_flow_id = os.getenv("ONBOARDING_FLOW_ID")

setup_logging()
logger = logging.getLogger(__name__)

# Steps where typing "cancel" returns the user to IDLE
_CANCELLABLE_STEPS = {
    "DAILY_AWAITING_INPUT_TYPE",
    "DAILY_AWAITING_PHOTO",
    "DAILY_AWAITING_TEXT",
    "DAILY_AWAITING_CONFIRM",
    "AWAITING_STOCK_UPDATE",
    "AWAITING_INCIDENT_REPORT",
    "AWAITING_REPORT_PAYMENT",
    "AWAITING_CAPS_Q1",
    "AWAITING_CAPS_Q2",
    "AWAITING_FLOW",
    "AWAITING_PHOTO",
    "AWAITING_TEXT_STOCK",
    "AWAITING_INPUT_TYPE",
    "AWAITING_VOICE_STOCK",  # added so cancel works from voice step
}

# ─────────────────────────────────────────────
# STEP 1 — Greeting button
# ─────────────────────────────────────────────


async def step_1_greeting_button(phone: str):
    logger.info("onboarding_step_1_start | phone=%s", phone)

    send_reply_buttons(
        to=phone,
        body_text=(
            "Hey! 👋 Welcome to Visbl.\n\n"
            "We help market traders like you keep a daily record of your stock - "
            "so if fire or flood ever hits, you have proof of everything you lost.\n\n"
            "It takes less than 2 minutes to set up. Ready?"
        ),
        buttons=[{"id": "start_onboarding", "title": "Let's go!"}],
        header_image_url=f"{domain_url}/assets/greetings.jpg",
        footer_text="Visbl · Free to start",
    )
    state.sessions[phone] = {"step": "AWAITING_BUTTON_CLICK"}

    logger.info("onboarding_step_1_complete | phone=%s", phone)


async def step_1_greeting_interactive_flow(phone: str):
    logger.info("onboarding_step_1_flow_start | phone=%s", phone)

    flow_token = str(uuid.uuid4())
    state.sessions[phone] = {"step": "AWAITING_FLOW", "flow_token": flow_token}

    send_whatsapp_flow(
        to=phone,
        header_image_url=f"{domain_url}/assets/greetings.jpg",
        body_text=(
            "Rainy season is near. "
            "The best time to protect your shop is before anything happens.\n\n"
            "Keep your records safe on your phone. "
            "Protect what you have built."
        ),
        flow_id=onboard_flow_id,
        flow_cta="Show me how",
        flow_token=flow_token,
        screen="WELCOME",
        footer_text="Visbl·",
    )

    logger.info("onboarding_step_1_flow_complete | phone=%s", phone)


# ─────────────────────────────────────────────
# STEP 1b–1f — Profile collection
# Name → Shop name → Location → Category
# ─────────────────────────────────────────────

_CATEGORIES = [
    {"id": "cat_clothing", "title": "Clothing & Footwear"},
    {"id": "cat_food", "title": "Food & Drinks"},
    {"id": "cat_electronics", "title": "Electronics"},
    {"id": "cat_beauty", "title": "Beauty & Cosmetics"},
    {"id": "cat_general", "title": "General Goods"},
    {"id": "cat_other", "title": "Other"},
]

_CATEGORY_LABELS = {c["id"]: c["title"] for c in _CATEGORIES}


async def step_1b_ask_name(phone: str):
    send_text(
        phone,
        "Before we start building your record, let me get to know your shop. 🏪\n\n"
        "What is your name?\n\n"
        "_Type *cancel* at any time to go back to the start._",
    )
    state.sessions[phone]["step"] = "AWAITING_NAME"


async def step_1c_handle_name(phone: str, text: str, session: dict):
    name = text.strip().title()
    if not name:
        send_text(phone, "Please tell me your name so I can personalise your record.")
        return

    session["name"] = name
    state.sessions[phone] = session

    send_text(phone, f"Nice to meet you, *{name}*! 👋\n\nWhat is your shop called?")
    state.sessions[phone]["step"] = "AWAITING_SHOP"


async def step_1d_handle_shop(phone: str, text: str, session: dict):
    shop = text.strip().title()
    if not shop:
        send_text(phone, "Please type your shop name to continue.")
        return

    session["shop_name"] = shop
    state.sessions[phone] = session

    send_text(
        phone,
        f"*{shop}* - nice! 🏪\n\n"
        "Where is your shop located?\n\n"
        "Example: Makola Market, Circle, Kumasi Central Market",
    )
    state.sessions[phone]["step"] = "AWAITING_LOCATION"


async def step_1e_handle_location(phone: str, text: str, session: dict):
    location = text.strip().title()
    if not location:
        send_text(phone, "Please type your shop location to continue.")
        return

    session["location"] = location
    state.sessions[phone] = session

    send_list_message(
        to=phone,
        body_text="Last one - what type of products do you mainly sell?",
        button_label="Choose category",
        sections=[
            {
                "title": "Select your category",
                "rows": [{"id": c["id"], "title": c["title"]} for c in _CATEGORIES],
            }
        ],
        footer_text="Visbl · Shop setup",
    )
    state.sessions[phone]["step"] = "AWAITING_CATEGORY"


async def step_1f_handle_category(phone: str, row_id: str, session: dict):
    category = _CATEGORY_LABELS.get(row_id)

    if not category:
        send_list_message(
            to=phone,
            body_text="Please pick your main product category from the list.",
            button_label="Choose category",
            sections=[
                {
                    "title": "Select your category",
                    "rows": [{"id": c["id"], "title": c["title"]} for c in _CATEGORIES],
                }
            ],
        )
        return

    session["category"] = category
    state.sessions[phone] = session

    name = session.get("name", "")
    shop = session.get("shop_name", "your shop")

    send_text(
        phone,
        f"Perfect! *{shop}* is all set up. 🎉\n\n"
        f"Now let's build your stock record, {name}.",
    )

    await step_2_ask_for_photo(phone)


# ─────────────────────────────────────────────
# STEP 2 — Ask how they want to share stock
# ─────────────────────────────────────────────


async def step_2_ask_for_photo(phone: str):
    logger.info("onboarding_step_2_start | phone=%s", phone)

    send_list_message(
        to=phone,
        body_text=(
            "Great! Let's build your shop record.\n\n"
            "How would you like to share your stock?"
        ),
        button_label="Choose method",
        sections=[
            {
                "title": "Pick one",
                "rows": [
                    {
                        "id": "input_photo",
                        "title": "📸 Send a photo",
                        "description": "Take a picture of your shelves",
                    },
                    {
                        "id": "input_logbook",
                        "title": "📖 Log book page",
                        "description": "Photo of your written records",
                    },
                    {
                        "id": "input_voice",
                        "title": "🎤 Voice note",
                        "description": "Speak your stock list",
                    },
                    {
                        "id": "input_text",
                        "title": "✍️ Type it out",
                        "description": "Type your list as a message",
                    },
                ],
            }
        ],
        footer_text="Visbl·",
    )
    session = state.sessions.get(phone, {})
    session["step"] = "AWAITING_INPUT_TYPE"
    state.sessions[phone] = session

    logger.info("onboarding_step_2_complete | phone=%s", phone)


async def step_2b_handle_input_choice(phone: str, button_id: str):
    logger.info("onboarding_step_2b | phone=%s choice=%s", phone, button_id)

    session = state.sessions.get(phone, {})

    if button_id in ("input_photo", "input_logbook"):
        label = "your shelves" if button_id == "input_photo" else "your log book page"
        send_text(
            phone,
            f"Take a clear photo of {label} and send it here. 📸\n\n"
            "Make sure everything is in the frame and well lit.",
        )
        session["step"] = "AWAITING_PHOTO"
        state.sessions[phone] = session

    elif button_id == "input_voice":
        send_text(
            phone,
            "Send me a voice note now. 🎤\n\n"
            "Say something like:\n"
            '_"Sneakers 15, Heels 10 at 120 cedis, Bags 5"_\n\n'
            "I will transcribe it and count your stock.",
        )
        session["step"] = "AWAITING_VOICE_STOCK"
        state.sessions[phone] = session

    elif button_id == "input_text":
        send_text(
            phone,
            "Type your stock list below. One item per line or comma-separated.\n\n"
            "Example:\n"
            "Sneakers: 15 @ GHS 120\n"
            "Heels: 10\n"
            "Bags: 5 @ GHS 80\n\n"
            "Add *@ GHS price* after a quantity if you know the unit price. "
            "It is optional.",
        )
        session["step"] = "AWAITING_TEXT_STOCK"
        state.sessions[phone] = session

    else:
        # Re-show the list so user can pick again
        await step_2_ask_for_photo(phone)


async def step_2c_handle_text_stock(phone: str, text: str, session: dict):
    logger.info("onboarding_step_2c_text_stock | phone=%s", phone)

    inventory = parse_text_inventory(text)

    if not inventory:
        logger.warning("onboarding_step_2c_parse_failed | phone=%s raw=%s", phone, text)
        send_text(
            phone,
            "I couldn't read that list. Please use this format:\n\n"
            "Sneakers: 15\nHeels: 10\nBags: 5\n\n"
            "Or: Sneakers 15, Heels 10, Bags 5",
        )
        return

    session["inventory"] = inventory
    state.sessions[phone] = session

    logger.info(
        "onboarding_step_2c_complete | phone=%s items=%d", phone, len(inventory)
    )

    await step_4_trigger_verification(phone, inventory)


# ─────────────────────────────────────────────
# STEP 3 — Receive photo + download from Meta
# ─────────────────────────────────────────────


async def step_3_handle_photo(phone: str, message: dict, session: dict):
    t0 = time.perf_counter()
    logger.info("onboarding_step_3_start | phone=%s", phone)

    message_id = message["id"]
    media_id = message["image"]["id"]

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            url_resp = await client.get(
                f"https://graph.facebook.com/v22.0/{media_id}",
                headers={"Authorization": f"Bearer {ACCESS_TOKEN}"},
            )
        media_url = url_resp.json().get("url")
    except Exception:
        logger.exception(
            "onboarding_step_3_media_url_error | phone=%s media_id=%s", phone, media_id
        )
        send_text(
            phone,
            "I could not reach WhatsApp to download your photo. Please try again. 📸",
        )
        return

    if not media_url:
        logger.warning(
            "onboarding_step_3_no_media_url | phone=%s media_id=%s", phone, media_id
        )
        send_text(
            phone,
            "Sorry, I could not read that photo. Please try again — "
            "make sure your shelves are well lit and in the frame. 📸",
        )
        return

    logger.debug(
        "onboarding_step_3_media_url_fetched | phone=%s elapsed=%.2fs",
        phone,
        time.perf_counter() - t0,
    )

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            img_resp, _ = await asyncio.gather(
                client.get(
                    media_url, headers={"Authorization": f"Bearer {ACCESS_TOKEN}"}
                ),
                asyncio.to_thread(
                    send_text, phone, "Got it! Counting your stock now... ⏳"
                ),
            )
    except Exception:
        logger.exception("onboarding_step_3_download_error | phone=%s", phone)
        send_text(
            phone,
            "I had trouble downloading your photo. Please send it again. 📸",
        )
        return

    image_b64 = base64.b64encode(img_resp.content).decode("utf-8")

    logger.debug(
        "onboarding_step_3_image_downloaded | phone=%s size_kb=%.1f elapsed=%.2fs",
        phone,
        len(img_resp.content) / 1024,
        time.perf_counter() - t0,
    )

    send_typing_indicator(phone, message_id)

    inventory = await step_4_parse_inventory_with_claude(phone, image_b64)

    if not inventory:
        logger.warning("onboarding_step_3_no_inventory | phone=%s", phone)
        send_text(
            phone,
            "I could not read the stock clearly from that photo. "
            "Please try again with a clearer, well-lit picture of your shelves. 📸",
        )
        return

    session["inventory"] = inventory
    state.sessions[phone] = session

    logger.info(
        "onboarding_step_3_complete | phone=%s items=%d elapsed=%.2fs",
        phone,
        len(inventory),
        time.perf_counter() - t0,
    )

    await step_4_trigger_verification(phone, inventory)


async def step_3_handle_voice(phone: str, message: dict, session: dict):
    """Onboarding: transcribe a voice note then hand off to text stock parser."""
    t0 = time.perf_counter()
    logger.info("onboarding_step_3_voice_start | phone=%s", phone)

    message_id = message["id"]
    media_id = message.get("audio", {}).get("id")

    if not media_id:
        send_reply_buttons(
            to=phone,
            body_text="I could not read that voice note. Please try again. 🎤",
            buttons=[
                {"id": "input_voice", "title": "🎤 Try again"},
                {"id": "input_text", "title": "✍️ Type instead"},
                {"id": "input_photo", "title": "📸 Send a photo"},
            ],
            footer_text="Visbl·",
        )
        session["step"] = "AWAITING_INPUT_TYPE"
        state.sessions[phone] = session
        return

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            url_resp = await client.get(
                f"https://graph.facebook.com/v22.0/{media_id}",
                headers={"Authorization": f"Bearer {ACCESS_TOKEN}"},
            )
        media_url = url_resp.json().get("url")
    except Exception:
        logger.exception("onboarding_step_3_voice_url_error | phone=%s", phone)
        send_reply_buttons(
            to=phone,
            body_text="I could not reach WhatsApp to download your voice note. Please try again. 🎤",
            buttons=[
                {"id": "input_voice", "title": "🎤 Try again"},
                {"id": "input_text", "title": "✍️ Type instead"},
                {"id": "input_photo", "title": "📸 Send a photo"},
            ],
            footer_text="Visbl·",
        )
        session["step"] = "AWAITING_INPUT_TYPE"
        state.sessions[phone] = session
        return

    if not media_url:
        send_reply_buttons(
            to=phone,
            body_text="I could not read that voice note. Please try again. 🎤",
            buttons=[
                {"id": "input_voice", "title": "🎤 Try again"},
                {"id": "input_text", "title": "✍️ Type instead"},
                {"id": "input_photo", "title": "📸 Send a photo"},
            ],
            footer_text="Visbl·",
        )
        session["step"] = "AWAITING_INPUT_TYPE"
        state.sessions[phone] = session
        return

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            audio_resp, _ = await asyncio.gather(
                client.get(
                    media_url, headers={"Authorization": f"Bearer {ACCESS_TOKEN}"}
                ),
                asyncio.to_thread(
                    send_text, phone, "Got it! Listening to your stock list... 🎤⏳"
                ),
            )
    except Exception:
        logger.exception("onboarding_step_3_voice_download_error | phone=%s", phone)
        send_reply_buttons(
            to=phone,
            body_text="I had trouble downloading your voice note. Please try again. 🎤",
            buttons=[
                {"id": "input_voice", "title": "🎤 Try again"},
                {"id": "input_text", "title": "✍️ Type instead"},
                {"id": "input_photo", "title": "📸 Send a photo"},
            ],
            footer_text="Visbl·",
        )
        session["step"] = "AWAITING_INPUT_TYPE"
        state.sessions[phone] = session
        return

    send_typing_indicator(phone, message_id)

    transcript = await _transcribe_audio(phone, audio_resp.content)

    if not transcript:
        logger.warning("onboarding_step_3_voice_transcription_failed | phone=%s", phone)
        send_reply_buttons(
            to=phone,
            body_text=(
                "I could not understand that voice note. 🎤\n\n"
                "Speak clearly and say items like:\n"
                '_"Sneakers 15, Heels 10 at 120 cedis, Bags 5"_'
            ),
            buttons=[
                {"id": "input_voice", "title": "🎤 Try again"},
                {"id": "input_text", "title": "✍️ Type instead"},
                {"id": "input_photo", "title": "📸 Send a photo"},
            ],
            footer_text="Visbl·",
        )
        session["step"] = "AWAITING_INPUT_TYPE"
        state.sessions[phone] = session
        return

    logger.info(
        "onboarding_step_3_voice_transcribed | phone=%s transcript=%s elapsed=%.2fs",
        phone,
        transcript,
        time.perf_counter() - t0,
    )

    inventory = parse_text_inventory(transcript)

    if not inventory:
        logger.warning("onboarding_step_3_voice_parse_failed | phone=%s", phone)
        send_reply_buttons(
            to=phone,
            body_text=(
                "I heard you but could not read a stock list from that. 🎤\n\n"
                'Try saying: _"Sneakers 15, Heels 10, Bags 5"_'
            ),
            buttons=[
                {"id": "input_voice", "title": "🎤 Try again"},
                {"id": "input_text", "title": "✍️ Type instead"},
                {"id": "input_photo", "title": "📸 Send a photo"},
            ],
            footer_text="Visbl·",
        )
        session["step"] = "AWAITING_INPUT_TYPE"
        state.sessions[phone] = session
        return

    session["inventory"] = inventory
    state.sessions[phone] = session

    await step_4_trigger_verification(phone, inventory)


# ─────────────────────────────────────────────
# STEP 4 — Claude Vision parser
# Uses Haiku (~3x faster than Sonnet) with a
# 15s hard timeout to prevent hangs.
# ─────────────────────────────────────────────


async def step_4_parse_inventory_with_claude(phone: str, image_b64: str) -> list:
    t0 = time.perf_counter()
    logger.info("claude_vision_start | phone=%s", phone)
    raw = None

    try:
        client = anthropic.AsyncAnthropic(api_key=ANTHROPIC_API_KEY)

        response = await asyncio.wait_for(
            client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=2048,
                system=(
                    "You are an inventory clerk at a market in Accra, Ghana. "
                    "Look at this shop photo. List product categories, estimated quantities, "
                    "and unit price in GHS if a price tag or price list is visible. "
                    "Also include the date if any date is visible on the image (receipt, label, board). "
                    "Return ONLY a valid JSON array. No explanation. No markdown. "
                    "Omit 'price' and 'date' fields if not visible — do not guess them. "
                    'Example with price and date: [{"item": "Sneakers", "qty": 15, "price": 120, "date": "2025-03-20"}, '
                    '{"item": "Heels", "qty": 10}]'
                ),
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image",
                                "source": {
                                    "type": "base64",
                                    "media_type": "image/jpeg",
                                    "data": image_b64,
                                },
                            },
                            {
                                "type": "text",
                                "text": (
                                    "What stock do you see? "
                                    "Include price (GHS) and date only if clearly visible. "
                                    "Return JSON only."
                                ),
                            },
                        ],
                    }
                ],
            ),
            timeout=15.0,
        )
        raw = response.content[0].text.strip()

        raw = re.sub(r"```json|```", "", raw).strip()

        try:
            inventory = json.loads(raw)
        except json.JSONDecodeError:
            complete = re.findall(r'\{[^{}]*"item"[^{}]*\}', raw)
            if not complete:
                raise
            inventory = [json.loads(obj) for obj in complete]
            logger.warning(
                "claude_vision_truncated | phone=%s salvaged=%d", phone, len(inventory)
            )

        logger.info(
            "claude_vision_complete | phone=%s items=%d elapsed=%.2fs",
            phone,
            len(inventory),
            time.perf_counter() - t0,
        )
        return inventory

    except asyncio.TimeoutError:
        logger.error(
            "claude_vision_timeout | phone=%s elapsed=%.2fs",
            phone,
            time.perf_counter() - t0,
        )
        return []

    except json.JSONDecodeError as e:
        logger.error(
            "claude_vision_json_error | phone=%s error=%s raw=%s",
            phone,
            e,
            raw,
        )
        return []

    except Exception:
        logger.exception(
            "claude_vision_error | phone=%s elapsed=%.2fs",
            phone,
            time.perf_counter() - t0,
        )
        return []


async def step_4_trigger_verification(phone: str, inventory: list):
    logger.info(
        "onboarding_step_4_verification_trigger | phone=%s items=%d",
        phone,
        len(inventory),
    )

    def _fmt_item(i: dict) -> str:
        line = f"• {i['item']}: {i['qty']} pieces"
        if i.get("price"):
            line += f" @ GHS {i['price']:,.2f}"
        if i.get("date"):
            line += f" (logged {i['date']})"
        return line

    items_text = "\n".join([_fmt_item(i) for i in inventory])
    flow_id = os.getenv("WHATSAPP_FLOW_ID")

    if flow_id:
        flow_token = str(uuid.uuid4())
        state.sessions[phone]["flow_token"] = flow_token

        send_whatsapp_flow(
            to=phone,
            header_text="Your Shop Record",
            body_text=(
                f"Here is what I found in your shop:\n\n{items_text}\n\n"
                "Please open the form to correct any numbers, then confirm."
            ),
            flow_id=flow_id,
            flow_cta="Review My Records",
            flow_token=flow_token,
            screen="INVENTORY_REVIEW",
            prefill_data={"inventory": inventory},
            footer_text="Visbl·",
        )
        logger.info("onboarding_step_4_flow_sent | phone=%s", phone)

    else:
        send_reply_buttons(
            to=phone,
            header_text="Your Shop Record",
            body_text=(
                f"Here is what I found in your shop:\n\n{items_text}\n\n"
                "Does this look correct?"
            ),
            buttons=[
                {"id": "inventory_correct", "title": "Yes, correct ✅"},
                {"id": "inventory_edit", "title": "No, edit it"},
            ],
            footer_text="Visbl·",
        )
        logger.info("onboarding_step_4_buttons_sent | phone=%s", phone)

    state.sessions[phone]["step"] = "AWAITING_FLOW"


# ─────────────────────────────────────────────
# STEP 5 — Handle Flow submission or button confirm
# ─────────────────────────────────────────────


async def step_5_handle_flow_submission(phone: str, flow_response: dict, session: dict):
    logger.info("onboarding_step_5_start | phone=%s", phone)

    try:
        response_data = json.loads(flow_response.get("response_json", "{}"))
    except json.JSONDecodeError:
        logger.warning("onboarding_step_5_bad_json | phone=%s", phone)
        response_data = {}

    confirmed_inventory = response_data.get("inventory", session.get("inventory", []))
    session["inventory"] = confirmed_inventory
    state.sessions[phone] = session

    logger.info(
        "onboarding_step_5_inventory_confirmed | phone=%s items=%d",
        phone,
        len(confirmed_inventory),
    )

    await step_5b_ask_stock_value(phone)


async def step_5b_ask_stock_value(phone: str):
    logger.info("onboarding_step_5b_start | phone=%s", phone)

    send_text(
        phone,
        "Almost done! Two quick questions to match you with the right Shield. 🛡️\n\n"
        "1️⃣ What is the *total value* of all the stock in your shop right now?\n\n"
        "Reply with the amount in Ghana Cedis. Example: *50,000*\n\n"
        "Not sure? Type *estimate* and I will work it out from your stock.",
    )
    state.sessions[phone]["step"] = "AWAITING_CAPS_Q1"


async def step_5b_handle_stock_value(phone: str, text: str, session: dict):
    logger.info("onboarding_step_5b_response | phone=%s raw_input=%s", phone, text)

    if text.strip().lower() == "estimate":
        inventory = session.get("inventory", [])
        estimated = (
            sum(
                i.get("qty", 0) * i.get("price", 0) for i in inventory if i.get("price")
            )
            if inventory
            else 0
        )

        if estimated > 0:
            formatted = f"GHS {estimated:,.0f}"
            session["stock_value"] = float(estimated)
            state.sessions[phone] = session
            send_text(
                phone,
                f"I will use *{formatted}* as your total stock value. ✅\n\n"
                "2️⃣ If a fire or flood hit your shop tomorrow, "
                "how much money would you need to buy stock and open again?\n\n"
                "Reply with the amount in Ghana Cedis. Example: *10,000*\n\n"
                "Not sure? Type *estimate* and I will use half your stock value.",
            )
            state.sessions[phone]["step"] = "AWAITING_CAPS_Q2"
        else:
            send_text(
                phone,
                "I do not have enough price information to estimate. "
                "Please type your best guess in Ghana Cedis. Example: *50,000*",
            )
        return

    cleaned = "".join(filter(str.isdigit, text))

    if not cleaned:
        logger.warning("onboarding_step_5b_invalid_input | phone=%s", phone)
        send_text(
            phone,
            "Please reply with a number. Example: *50,000*\n\n"
            "What is the total value of all the stock in your shop?\n\n"
            "Not sure? Type *estimate*.",
        )
        return

    session["stock_value"] = float(cleaned)
    state.sessions[phone] = session

    logger.info(
        "onboarding_step_5b_stock_value_saved | phone=%s value=%s", phone, cleaned
    )

    send_text(
        phone,
        "2️⃣ If a fire or flood hit your shop tomorrow, "
        "how much money would you need to buy stock and open again?\n\n"
        "Reply with the amount in Ghana Cedis. Example: *10,000*\n\n"
        "Not sure? Type *estimate* and I will use half your stock value.",
    )
    state.sessions[phone]["step"] = "AWAITING_CAPS_Q2"


async def step_5c_handle_restart_cap(phone: str, text: str, session: dict):
    logger.info("onboarding_step_5c_response | phone=%s raw_input=%s", phone, text)

    if text.strip().lower() == "estimate":
        stock_value = session.get("stock_value", 0)
        estimated = round(stock_value * 0.5, -3)
        if estimated <= 0:
            estimated = 5000
        formatted = f"GHS {estimated:,.0f}"
        send_text(
            phone,
            f"I will use *{formatted}* as your Restart Cap — roughly half your stock value.\n\n"
            "You can type a different amount if you prefer.",
        )
        session["restart_cap"] = float(estimated)
        state.sessions[phone] = session

        send_typing_indicator(phone, "")
        await step_6_complete_onboarding(phone, session)
        return

    cleaned = "".join(filter(str.isdigit, text))

    if not cleaned:
        logger.warning("onboarding_step_5c_invalid_input | phone=%s", phone)
        send_text(
            phone,
            "Please reply with a number. Example: *10,000*\n\n"
            "How much would you need to restock and reopen after a flood or fire?\n\n"
            "Not sure? Type *estimate*.",
        )
        return

    session["restart_cap"] = float(cleaned)
    state.sessions[phone] = session

    logger.info(
        "onboarding_step_5c_restart_cap_saved | phone=%s value=%s", phone, cleaned
    )
    send_typing_indicator(phone, "")
    await step_6_complete_onboarding(phone, session)


# ─────────────────────────────────────────────
# STEP 6 — Tier logic + confirmation
# ─────────────────────────────────────────────


# todo: alight with business
def calculate_tier(restart_cap: float) -> dict:
    if restart_cap <= 5000:
        return {"tier": "Starter Shield", "price": "GHS 60/month"}
    elif restart_cap <= 15000:
        return {"tier": "Standard Shield", "price": "GHS 120/month"}
    else:
        return {"tier": "Premium Shield", "price": "GHS 250/month"}


async def step_6_complete_onboarding(phone: str, session: dict):
    logger.info("onboarding_step_6_start | phone=%s", phone)

    tier = calculate_tier(session["restart_cap"])
    session["tier"] = tier

    _TIER_PREMIUM_PESEWAS = {
        "Starter Shield": 6000,
        "Standard Shield": 12000,
        "Premium Shield": 25000,
    }

    try:
        db = SessionLocal()
        try:
            owner = Owner(
                phone_number=phone,
                name=session.get("name"),
                shop_name=session.get("shop_name"),
                location=session.get("location"),
                category=session.get("category"),
            )
            db.add(owner)
            db.flush()

            db.add(
                InventoryDeclaration(
                    owner_id=owner.id,
                    total_stock_value_ghs=session["stock_value"],
                    item_breakdown_json=json.dumps(session["inventory"]),
                )
            )

            db.add(
                Policy(
                    owner_id=owner.id,
                    status="pending",
                    premium_pesewas=_TIER_PREMIUM_PESEWAS.get(tier["tier"], 6000),
                    payout_cap_pesewas=int(session["restart_cap"] * 100),
                )
            )

            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

        logger.info(
            "onboarding_step_6_db_write_success | phone=%s tier=%s", phone, tier["tier"]
        )

    except Exception:
        logger.exception("onboarding_step_6_db_write_error | phone=%s", phone)
        send_text(
            phone,
            "Something went wrong saving your record. Please try again in a moment.",
        )
        return

    restart_formatted = f"GHS {int(session['restart_cap']):,}"
    stock_formatted = f"GHS {int(session['stock_value']):,}"
    name = session.get("name", "")
    shop = session.get("shop_name", "your shop")

    send_text(
        phone,
        f"{'*' + name + '*, you' if name else 'You'} are now on Visbl! 🎉\n\n"
        f"*{shop}* has been registered with:\n"
        f"• Stock value: *{stock_formatted}*\n"
        f"• Restart Cap: *{restart_formatted}*\n"
        f"• Plan: *{tier['tier']}* — {tier['price']}\n\n"
        f"*Your record is not protected yet* - but it starts building from today.\n\n"
        f"Every day you log, your proof gets stronger. "
        f"When something goes wrong, that proof is what gets you paid. 📋",
    )

    send_reply_buttons(
        to=phone,
        body_text=(
            f"Here is how protection works:\n\n"
            f"1️⃣ Build your record daily for 30 days\n"
            f"2️⃣ Pay your first premium to activate\n"
            f"3️⃣ Your shop is covered 🛡️\n\n"
            f"You can activate now or wait - your record builds either way. "
            f"First premium: *{tier['price']}*"
        ),
        buttons=[
            {"id": "pay_now", "title": "Activate now 🔒"},
            {"id": "pay_later", "title": "Remind me later"},
        ],
        footer_text="Visbl · Cancel anytime",
    )

    state.sessions[phone]["step"] = "AWAITING_PAYMENT_DECISION"

    logger.info(
        "onboarding_complete | phone=%s tier=%s restart_cap=%s",
        phone,
        tier["tier"],
        session["restart_cap"],
    )


# ─────────────────────────────────────────────
# EXISTING USER HANDLER (post-onboarding)
# ─────────────────────────────────────────────


async def send_daily_checkin(phone: str):
    """Send the daily habit check-in. Call this from a scheduler each morning."""
    send_reply_buttons(
        to=phone,
        body_text=(
            "Good morning! ☀️\n\nHow is your shop today? Any changes to your stock?"
        ),
        buttons=[
            {"id": "checkin_good", "title": "All good today ✅"},
            {"id": "checkin_update", "title": "Update my stock 📦"},
            {"id": "checkin_problem", "title": "Had a problem ⚠️"},
        ],
        footer_text="Visbl · Your daily record",
    )
    state.sessions[phone] = state.sessions.get(phone, {})
    state.sessions[phone]["step"] = "DAILY_CHECKIN"


async def handle_existing_user(phone: str, message: dict, owner):
    """Route messages from onboarded users based on session step."""
    logger.info("existing_user_message | phone=%s", phone)

    session = state.sessions.get(phone, {})
    step = session.get("step", "IDLE")
    msg_type = message.get("type", "")
    text = message.get("text", {}).get("body", "").strip()
    text_lower = text.lower()

    message_id = message.get("id", "")
    interactive = message.get("interactive", {})
    button_id = interactive.get("button_reply", {}).get("id", "") or interactive.get(
        "list_reply", {}
    ).get("id", "")

    name = (owner.name if owner and owner.name else "").strip()
    greeting = f"Hi {name}!" if name else "Hey!"

    # ── Unsupported message types ──
    if msg_type not in ("text", "interactive", "image", "audio"):
        send_text(
            phone,
            "I can only read text messages, photos, and voice notes. "
            "Please send one of those.",
        )
        return

    # ── Global: cancel from any active step ──
    if text_lower == "cancel" and step in _CANCELLABLE_STEPS:
        logger.info("user_cancelled | phone=%s step=%s", phone, step)
        session["step"] = "IDLE"
        session.pop("daily_inventory", None)
        state.sessions[phone] = session
        _send_main_menu(phone, "Cancelled. ✅")
        return

    # ── Global keyword: delete data ──
    if text_lower in ("delete my data", "reset", "start over"):
        send_reply_buttons(
            to=phone,
            body_text=(
                "⚠️ This will permanently delete your shop record and all your data.\n\n"
                "Are you sure? This cannot be undone."
            ),
            buttons=[
                {"id": "confirm_delete", "title": "Yes, delete it"},
                {"id": "cancel_delete", "title": "No, keep my data"},
            ],
        )
        session["step"] = "AWAITING_DELETE_CONFIRM"
        state.sessions[phone] = session
        return

    # ── Step: delete confirmation ──
    if step == "AWAITING_DELETE_CONFIRM":
        if button_id == "confirm_delete":
            await _delete_user_data(phone, owner)
        elif button_id == "cancel_delete":
            _send_main_menu(phone, "Your data is safe. 👍")
            session["step"] = "IDLE"
            state.sessions[phone] = session
        else:
            send_reply_buttons(
                to=phone,
                body_text="Please tap one of the buttons to confirm.",
                buttons=[
                    {"id": "confirm_delete", "title": "Yes, delete it"},
                    {"id": "cancel_delete", "title": "No, keep my data"},
                ],
            )
        return

    # ── Step: payment decision ──
    if step == "AWAITING_PAYMENT_DECISION":
        if button_id == "pay_now":
            _send_payment_instructions(phone)
            session["step"] = "AWAITING_PAYMENT_CONFIRM"
            state.sessions[phone] = session
        elif button_id == "pay_later":
            send_text(
                phone,
                "No problem. Your record keeps building every day. 📋\n\n"
                "Type *ACTIVATE* anytime when you are ready.",
            )
            session["step"] = "IDLE"
            state.sessions[phone] = session
        else:
            tier = session.get("tier", {})
            price = tier.get("price", "") if isinstance(tier, dict) else ""
            send_reply_buttons(
                to=phone,
                body_text=(
                    f"Ready to activate your Shield? 🛡️\n\nFirst premium: *{price}*"
                    if price
                    else "Ready to activate your Shield? 🛡️"
                ),
                buttons=[
                    {"id": "pay_now", "title": "Activate now 🔒"},
                    {"id": "pay_later", "title": "Remind me later"},
                ],
                footer_text="Visbl · Cancel anytime",
            )
        return

    # ── Step: waiting for payment confirmation ──
    if step == "AWAITING_PAYMENT_CONFIRM":
        if text_lower == "paid":
            send_text(
                phone,
                "Thank you! 🎉 Checking your payment now.\n\n"
                "Your Shield will be active within a few minutes.",
            )
            session["step"] = "IDLE"
            state.sessions[phone] = session
        elif text_lower == "cancel":
            send_text(phone, "Cancelled. Type *ACTIVATE* anytime when you are ready.")
            session["step"] = "IDLE"
            state.sessions[phone] = session
        else:
            send_text(
                phone,
                "Reply *PAID* once you have sent the premium.\n\n"
                "Type *CANCEL* to go back.",
            )
        return

    # ── Step: daily check-in ──
    if step == "DAILY_CHECKIN":
        if button_id == "checkin_good":
            send_text(phone, "Logged ✅ Keep it up!")
            session["step"] = "IDLE"
            state.sessions[phone] = session
        elif button_id == "checkin_update":
            await _daily_ask_input_type(phone)
        elif button_id == "checkin_problem":
            send_text(
                phone,
                "What happened? Describe it briefly and I will log it.\n\n"
                "For fire or flood, type *CLAIM*.",
            )
            session["step"] = "AWAITING_INCIDENT_REPORT"
            state.sessions[phone] = session
        else:
            await send_daily_checkin(phone)
        return

    # ── Daily update steps ──
    if step in ("DAILY_AWAITING_INPUT_TYPE", "AWAITING_STOCK_UPDATE"):
        send_typing_indicator(phone, message_id)
        if not button_id:
            await _daily_ask_input_type(phone)
            return
        await _daily_handle_input_choice(phone, button_id)
        return

    if step == "DAILY_AWAITING_TEXT":
        if msg_type == "text" and text:
            # Covers both typed text AND transcribed voice notes (webhook converts audio→text)
            await _daily_handle_text(phone, text, session)
        elif msg_type == "audio":
            # Fallback in case webhook didn't transcribe (e.g. user in DAILY_AWAITING_TEXT
            # and webhook skipped transcription for some reason)
            await _daily_handle_voice(phone, message, session)
        else:
            send_reply_buttons(
                to=phone,
                body_text=(
                    "Please type your stock list or send a voice note. 🎤\n\n"
                    "Example: Sneakers: 15, Heels: 10, Bags: 5"
                ),
                buttons=[
                    {"id": "daily_voice", "title": "🎤 Try voice again"},
                    {"id": "daily_text", "title": "✍️ Type instead"},
                ],
                footer_text="Visbl · Type *cancel* to stop",
            )
        return

    if step == "DAILY_AWAITING_PHOTO":
        if msg_type == "image":
            await _daily_handle_photo(phone, message, session)
        else:
            send_text(
                phone,
                "Please send a photo of your shelves or log book. 📸\n\n"
                "Type *cancel* to go back.",
            )
        return

    if step == "DAILY_AWAITING_CONFIRM":
        if button_id == "daily_confirm":
            inventory = session.get("daily_inventory", [])
            await _daily_save_inventory(phone, owner, inventory)
        elif button_id == "daily_edit":
            send_text(
                phone,
                "No problem — type your corrected list below.\n\n"
                "Example: Sneakers: 20, Heels: 5, Bags: 3\n\n"
                "Type *cancel* to go back.",
            )
            session["step"] = "DAILY_AWAITING_TEXT"
            state.sessions[phone] = session
        else:
            inventory = session.get("daily_inventory", [])
            await _daily_confirm_inventory(phone, inventory)
        return

    # ── Main menu button shortcuts ──
    if button_id == "menu_log":
        await _daily_ask_input_type(phone)
        return

    if button_id == "menu_report":
        send_text(
            phone,
            "📄 *Your Shop Record — GHS 2*\n\n"
            "Send *GHS 2* via Mobile Money:\n"
            "*0XX XXX XXXX* (Visbl) · Reference: REPORT\n\n"
            "Reply *PAID* once done, or *CANCEL* to go back.",
        )
        session["step"] = "AWAITING_REPORT_PAYMENT"
        state.sessions[phone] = session
        return

    if button_id == "menu_activate":
        send_reply_buttons(
            to=phone,
            body_text="Ready to activate your Shield? 🛡️\n\nYour first premium locks in your protection.",
            buttons=[
                {"id": "pay_now", "title": "Activate now 🔒"},
                {"id": "pay_later", "title": "Not yet"},
            ],
        )
        session["step"] = "AWAITING_PAYMENT_DECISION"
        state.sessions[phone] = session
        return

    if button_id == "menu_delete":
        send_reply_buttons(
            to=phone,
            body_text=(
                "⚠️ This will permanently delete your shop record and all your data.\n\n"
                "Are you sure? This cannot be undone."
            ),
            buttons=[
                {"id": "confirm_delete", "title": "Yes, delete it"},
                {"id": "cancel_delete", "title": "No, keep my data"},
            ],
        )
        session["step"] = "AWAITING_DELETE_CONFIRM"
        state.sessions[phone] = session
        return

    # ── Global keyword: log / update ──
    if text_lower in ("log", "update", "update stock"):
        await _daily_ask_input_type(phone)
        return

    # ── Global keyword: activate ──
    if text_lower == "activate":
        send_reply_buttons(
            to=phone,
            body_text="Ready to activate your Shield? 🛡️\n\nYour first premium locks in your protection.",
            buttons=[
                {"id": "pay_now", "title": "Activate now 🔒"},
                {"id": "pay_later", "title": "Not yet"},
            ],
        )
        session["step"] = "AWAITING_PAYMENT_DECISION"
        state.sessions[phone] = session
        return

    if button_id == "pay_now":
        _send_payment_instructions(phone)
        session["step"] = "AWAITING_PAYMENT_CONFIRM"
        state.sessions[phone] = session
        return

    if button_id == "pay_later":
        send_text(phone, "Got it. Type *ACTIVATE* anytime when you are ready. 👍")
        session["step"] = "IDLE"
        state.sessions[phone] = session
        return

    # ── Global keyword: report ──
    if text_lower == "report":
        send_text(
            phone,
            "📄 *Your Shop Record — GHS 2*\n\n"
            "Send *GHS 2* via Mobile Money:\n"
            "*0XX XXX XXXX* (Visbl) · Reference: REPORT\n\n"
            "Reply *PAID* once done, or *CANCEL* to go back.",
        )
        session["step"] = "AWAITING_REPORT_PAYMENT"
        state.sessions[phone] = session
        return

    # ── Step: waiting for report payment ──
    if step == "AWAITING_REPORT_PAYMENT":
        if text_lower == "paid":
            send_typing_indicator(phone, message_id)
            send_text(phone, "Checking payment... generating your report now. 📄")
            await _send_shop_report(phone, owner)
            session["step"] = "IDLE"
            state.sessions[phone] = session
        elif text_lower == "cancel":
            send_text(phone, "Cancelled. Type *REPORT* anytime when you are ready.")
            session["step"] = "IDLE"
            state.sessions[phone] = session
        else:
            send_text(
                phone,
                "Send *GHS 2* to *0XX XXX XXXX* (Visbl) · Reference: REPORT\n\n"
                "Reply *PAID* once done, or *CANCEL* to go back.",
            )
        return

    # ── IDLE / fallback ──
    _send_main_menu(phone, f"{greeting} Good to hear from you. 👋")


async def _send_shop_report(phone: str, owner):
    """Generate a PDF shop record and send it to the user as a WhatsApp document."""
    logger.info("report_generate_start | phone=%s", phone)

    if not owner:
        send_text(phone, "I could not find your shop record. Please try again.")
        return

    send_text(phone, "Generating your shop record... 📄")
    send_typing_indicator(phone, "")

    db = SessionLocal()
    try:
        owner_id = int(owner.id)
        fresh_owner = db.query(Owner).filter(Owner.id == owner_id).first()
        declaration = (
            db.query(InventoryDeclaration)
            .filter(InventoryDeclaration.owner_id == owner_id)
            .order_by(InventoryDeclaration.generated_at.desc())
            .first()
        )
        policy = (
            db.query(Policy)
            .filter(Policy.owner_id == owner_id)
            .order_by(Policy.id.desc())
            .first()
        )

        owner_data = {
            "name": fresh_owner.name if fresh_owner else None,
            "shop_name": fresh_owner.shop_name if fresh_owner else None,
            "location": fresh_owner.location if fresh_owner else None,
            "category": fresh_owner.category if fresh_owner else None,
            "phone_number": phone,
            "created_at": fresh_owner.created_at if fresh_owner else None,
        }
        declaration_data = (
            {
                "total_stock_value_ghs": float(declaration.total_stock_value_ghs or 0),
                "item_breakdown_json": declaration.item_breakdown_json,
                "generated_at": declaration.generated_at,
            }
            if declaration
            else None
        )
        policy_data = (
            {
                "status": policy.status,
                "premium_pesewas": policy.premium_pesewas,
                "payout_cap_pesewas": policy.payout_cap_pesewas,
                "cover_start_date": policy.cover_start_date,
                "last_premium_paid_at": policy.last_premium_paid_at,
            }
            if policy
            else None
        )

    except Exception as e:
        logger.exception("report_db_fetch_error | phone=%s error=%s", phone, e)
        send_text(
            phone, "Something went wrong generating your report. Please try again."
        )
        return
    finally:
        db.close()

    try:
        pdf_bytes = await asyncio.to_thread(
            generate_report_pdf, owner_data, declaration_data, policy_data
        )
    except Exception as e:
        logger.exception("report_pdf_build_error | phone=%s error=%s", phone, e)
        send_text(
            phone, "Something went wrong generating your report. Please try again."
        )
        return

    media_id = await asyncio.to_thread(upload_pdf_to_whatsapp, pdf_bytes)

    if not media_id:
        logger.error("report_upload_failed | phone=%s", phone)
        send_text(
            phone, "I could not send the report right now. Please try again later."
        )
        return

    shop_name = (owner_data.get("shop_name") or "Shop").replace(" ", "_")
    filename = f"Visbl_{shop_name}_Record.pdf"

    send_document(
        to=phone,
        media_id=media_id,
        filename=filename,
        caption=(
            "Here is your Visbl shop record. 📋\n\n"
            "Keep this document safe - it is your proof of stock."
        ),
    )
    logger.info("report_sent | phone=%s filename=%s", phone, filename)


# ─────────────────────────────────────────────
# DAILY UPDATE HELPERS
# ─────────────────────────────────────────────


async def _daily_ask_input_type(phone: str):
    send_list_message(
        to=phone,
        body_text="How would you like to update your stock today? 📦",
        button_label="Choose method",
        sections=[
            {
                "title": "Pick one",
                "rows": [
                    {
                        "id": "daily_photo",
                        "title": "📸 Send a photo",
                        "description": "Take a picture of your shelves",
                    },
                    {
                        "id": "daily_logbook",
                        "title": "📖 Log book page",
                        "description": "Photo of your written records",
                    },
                    {
                        "id": "daily_voice",
                        "title": "🎤 Voice note",
                        "description": "Speak your stock list",
                    },
                    {
                        "id": "daily_text",
                        "title": "✍️ Type it out",
                        "description": "Type your list as a message",
                    },
                ],
            }
        ],
        footer_text="Visbl · Daily record · Type *cancel* to stop",
    )
    session = state.sessions.get(phone, {})
    session["step"] = "DAILY_AWAITING_INPUT_TYPE"
    state.sessions[phone] = session


async def _daily_handle_input_choice(phone: str, button_id: str):
    session = state.sessions.get(phone, {})

    if button_id in ("daily_photo", "daily_logbook"):
        label = "your shelves" if button_id == "daily_photo" else "your log book page"
        send_text(
            phone,
            "Take a clear photo of your shelves or log book page and send it here. 📸\n\n"
            "Make sure everything is in the frame and well lit.\n\n"
            "Type *cancel* to go back.",
        )
        session["step"] = "DAILY_AWAITING_PHOTO"
        state.sessions[phone] = session

    elif button_id == "daily_voice":
        send_text(
            phone,
            "Send me a voice note now. 🎤\n\n"
            "Say something like:\n"
            '_"Sneakers 15, Heels 10 at 120 cedis, Bags 5"_\n\n'
            "I will transcribe it and count your stock.\n\n"
            "Type *cancel* to go back.",
        )
        session["step"] = "DAILY_AWAITING_TEXT"
        state.sessions[phone] = session

    elif button_id == "daily_text":
        send_text(
            phone,
            "Type your stock list below.\n\n"
            "Example:\n"
            "Sneakers: 15 @ GHS 120\n"
            "Heels: 10\n"
            "Bags: 5 @ GHS 80\n\n"
            "Add *@ GHS price* after a quantity if you know the unit price.\n\n"
            "Type *cancel* to go back.",
        )
        session["step"] = "DAILY_AWAITING_TEXT"
        state.sessions[phone] = session

    else:
        session["step"] = "IDLE"
        state.sessions[phone] = session
        await _daily_ask_input_type(phone)


# ─────────────────────────────────────────────
# VOICE NOTE HANDLER
# Downloads audio from Meta → Whisper → parse
# ─────────────────────────────────────────────


async def _daily_handle_voice(phone: str, message: dict, session: dict):
    """Download a WhatsApp voice note, transcribe via Whisper, then parse as inventory."""
    t0 = time.perf_counter()
    logger.info("daily_voice_start | phone=%s", phone)

    message_id = message["id"]
    media_id = message.get("audio", {}).get("id")

    if not media_id:
        logger.warning("daily_voice_no_media_id | phone=%s", phone)
        send_reply_buttons(
            to=phone,
            body_text="I could not read that voice note. Please try again. 🎤",
            buttons=[
                {"id": "daily_voice", "title": "🎤 Try again"},
                {"id": "daily_text", "title": "✍️ Type instead"},
            ],
            footer_text="Visbl · Type *cancel* to stop",
        )
        session["step"] = "DAILY_AWAITING_INPUT_TYPE"
        state.sessions[phone] = session
        return

    # Fetch download URL
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            url_resp = await client.get(
                f"https://graph.facebook.com/v22.0/{media_id}",
                headers={"Authorization": f"Bearer {ACCESS_TOKEN}"},
            )
        media_url = url_resp.json().get("url")
    except Exception:
        logger.exception("daily_voice_url_error | phone=%s", phone)
        send_reply_buttons(
            to=phone,
            body_text="I could not reach WhatsApp to download your voice note. Please try again. 🎤",
            buttons=[
                {"id": "daily_voice", "title": "🎤 Try again"},
                {"id": "daily_text", "title": "✍️ Type instead"},
            ],
            footer_text="Visbl · Type *cancel* to stop",
        )
        session["step"] = "DAILY_AWAITING_INPUT_TYPE"
        state.sessions[phone] = session
        return

    if not media_url:
        send_reply_buttons(
            to=phone,
            body_text="I could not read that voice note. Please try again. 🎤",
            buttons=[
                {"id": "daily_voice", "title": "🎤 Try again"},
                {"id": "daily_text", "title": "✍️ Type instead"},
            ],
            footer_text="Visbl · Type *cancel* to stop",
        )
        session["step"] = "DAILY_AWAITING_INPUT_TYPE"
        state.sessions[phone] = session
        return

    # Download audio + send acknowledgement in parallel
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            audio_resp, _ = await asyncio.gather(
                client.get(
                    media_url, headers={"Authorization": f"Bearer {ACCESS_TOKEN}"}
                ),
                asyncio.to_thread(
                    send_text, phone, "Got it! Listening to your voice note... 🎤⏳"
                ),
            )
    except Exception:
        logger.exception("daily_voice_download_error | phone=%s", phone)
        send_reply_buttons(
            to=phone,
            body_text="I had trouble downloading your voice note. Please try again. 🎤",
            buttons=[
                {"id": "daily_voice", "title": "🎤 Try again"},
                {"id": "daily_text", "title": "✍️ Type instead"},
            ],
            footer_text="Visbl · Type *cancel* to stop",
        )
        session["step"] = "DAILY_AWAITING_INPUT_TYPE"
        state.sessions[phone] = session
        return

    send_typing_indicator(phone, message_id)

    transcript = await _transcribe_audio(phone, audio_resp.content)

    if not transcript:
        logger.warning("daily_voice_transcription_failed | phone=%s", phone)
        send_reply_buttons(
            to=phone,
            body_text=(
                "I could not understand that voice note. 🎤\n\n"
                'Speak clearly: _"Sneakers 15, Heels 10, Bags 5"_'
            ),
            buttons=[
                {"id": "daily_voice", "title": "🎤 Try again"},
                {"id": "daily_text", "title": "✍️ Type instead"},
            ],
            footer_text="Visbl · Type *cancel* to stop",
        )
        session["step"] = "DAILY_AWAITING_INPUT_TYPE"
        state.sessions[phone] = session
        return

    logger.info(
        "daily_voice_transcribed | phone=%s transcript=%s elapsed=%.2fs",
        phone,
        transcript,
        time.perf_counter() - t0,
    )

    # Hand the transcript straight to the text parser
    await _daily_handle_text(phone, transcript, session)


async def _transcribe_audio(phone: str, audio_bytes: bytes) -> str | None:
    """Transcribe audio bytes using OpenAI Whisper API."""
    t0 = time.perf_counter()
    logger.info("whisper_start | phone=%s size_kb=%.1f", phone, len(audio_bytes) / 1024)

    openai_api_key = os.getenv("OPENAI_API_KEY")
    if not openai_api_key:
        logger.error("whisper_no_api_key | phone=%s", phone)
        return None

    try:
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.post(
                "https://api.openai.com/v1/audio/transcriptions",
                headers={"Authorization": f"Bearer {openai_api_key}"},
                data={"model": "whisper-1", "language": "en"},
                files={"file": ("audio.ogg", audio_bytes, "audio/ogg")},
            )
            response.raise_for_status()
            transcript = response.json().get("text", "").strip()

        logger.info(
            "whisper_complete | phone=%s elapsed=%.2fs transcript_len=%d",
            phone,
            time.perf_counter() - t0,
            len(transcript),
        )
        return transcript or None

    except Exception:
        logger.exception(
            "whisper_error | phone=%s elapsed=%.2fs", phone, time.perf_counter() - t0
        )
        return None


async def _daily_handle_text(phone: str, text: str, session: dict):
    inventory = parse_text_inventory(text)
    if not inventory:
        send_text(
            phone,
            "I couldn't read that list. Please use this format:\n\n"
            "Sneakers: 15\nHeels: 10\nBags: 5\n\n"
            "Or: Sneakers 15, Heels 10, Bags 5\n\n"
            "Type *cancel* to go back.",
        )
        return
    session["daily_inventory"] = inventory
    state.sessions[phone] = session
    await _daily_confirm_inventory(phone, inventory)


async def _daily_handle_photo(phone: str, message: dict, session: dict):
    t0 = time.perf_counter()
    logger.info("daily_photo_start | phone=%s", phone)

    message_id = message["id"]
    media_id = message["image"]["id"]

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            url_resp = await client.get(
                f"https://graph.facebook.com/v22.0/{media_id}",
                headers={"Authorization": f"Bearer {ACCESS_TOKEN}"},
            )
        media_url = url_resp.json().get("url")
    except Exception as e:
        logger.exception("daily_photo_url_error | phone=%s error=%s", phone, e)
        send_text(
            phone,
            "I could not reach WhatsApp to download your photo. Please try again. 📸",
        )
        return

    if not media_url:
        send_text(phone, "Sorry, I could not read that photo. Please try again. 📸")
        return

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            img_resp, _ = await asyncio.gather(
                client.get(
                    media_url, headers={"Authorization": f"Bearer {ACCESS_TOKEN}"}
                ),
                asyncio.to_thread(
                    send_text, phone, "Got it! Counting your stock now... ⏳"
                ),
            )
    except Exception as e:
        logger.exception("daily_photo_download_error | phone=%s error=%s", phone, e)
        send_text(
            phone, "I had trouble downloading your photo. Please send it again. 📸"
        )
        return

    image_b64 = base64.b64encode(img_resp.content).decode("utf-8")
    send_typing_indicator(phone, message_id)

    inventory = await step_4_parse_inventory_with_claude(phone, image_b64)

    if not inventory:
        send_text(
            phone,
            "I could not read the stock clearly from that photo. "
            "Please try again with a clearer, well-lit picture. 📸\n\n"
            "Type *cancel* to go back.",
        )
        return

    logger.info(
        "daily_photo_complete | phone=%s items=%d elapsed=%.2fs",
        phone,
        len(inventory),
        time.perf_counter() - t0,
    )

    session["daily_inventory"] = inventory
    state.sessions[phone] = session
    await _daily_confirm_inventory(phone, inventory)


async def _daily_confirm_inventory(phone: str, inventory: list):
    def _fmt(i: dict) -> str:
        line = f"• {i['item']}: {i['qty']} pieces"
        if i.get("price"):
            line += f" @ GHS {i['price']:,.0f}"
        if i.get("date"):
            line += f" (logged {i['date']})"
        return line

    items_text = "\n".join(_fmt(i) for i in inventory)

    send_reply_buttons(
        to=phone,
        header_text="Today's Stock Update",
        body_text=(
            f"Here is what I counted:\n\n{items_text}\n\nDoes this look correct?"
        ),
        buttons=[
            {"id": "daily_confirm", "title": "Yes, save it ✅"},
            {"id": "daily_edit", "title": "No, edit it"},
        ],
        footer_text="Visbl · Daily record · Type *cancel* to stop",
    )
    session = state.sessions.get(phone, {})
    session["step"] = "DAILY_AWAITING_CONFIRM"
    state.sessions[phone] = session


async def _daily_save_inventory(phone: str, owner, inventory: list):
    logger.info("daily_save_start | phone=%s items=%d", phone, len(inventory))

    owner_id = int(owner.id) if owner else None
    if not owner_id:
        send_text(phone, "Something went wrong saving your update. Please try again.")
        return

    total_value = sum(
        i.get("qty", 0) * i.get("price", 0) for i in inventory if i.get("price")
    )

    send_typing_indicator(phone, "")

    db = SessionLocal()
    db_error = False
    try:
        db.add(
            InventoryDeclaration(
                owner_id=owner_id,
                total_stock_value_ghs=total_value if total_value > 0 else None,
                item_breakdown_json=json.dumps(inventory),
            )
        )
        for item in inventory:
            price_pesewas = int(item["price"] * 100) if item.get("price") else None
            db.add(
                InventoryLog(
                    owner_id=owner_id,
                    entry_type="daily_snapshot",
                    product_name=item.get("item"),
                    quantity=item.get("qty"),
                    unit_price_pesewas=price_pesewas,
                    raw_message=json.dumps(item),
                )
            )
        db.commit()
        logger.info("daily_save_complete | phone=%s", phone)
    except Exception as e:
        db.rollback()
        db_error = True
        logger.exception("daily_save_error | phone=%s error=%s", phone, e)
    finally:
        db.close()

    session = state.sessions.get(phone, {})
    session["step"] = "IDLE"
    session.pop("daily_inventory", None)
    state.sessions[phone] = session

    if db_error:
        send_text(phone, "Something went wrong saving your update. Please try again.")
    else:
        send_text(
            phone,
            "Stock saved! ✅\n\n"
            "Your record is building - see you tomorrow. 📋\n\n"
            "*LOG* anytime to update again.",
        )


def _send_payment_instructions(phone: str):
    send_text(
        phone,
        "Here is how to pay your first premium:\n\n"
        "*Mobile Money:* Send to *0XX XXX XXXX* (Visbl)\n"
        "Reference: your phone number\n\n"
        "Reply *PAID* once done.",
    )


async def _delete_user_data(phone: str, owner):
    """Delete all records for this user and clear their session."""
    logger.info("user_data_delete_start | phone=%s", phone)

    owner_id = int(owner.id) if owner else None

    db_error = False
    db = SessionLocal()
    try:
        if owner_id:
            policy_ids = [
                r[0]
                for r in db.query(Policy.id).filter(Policy.owner_id == owner_id).all()
            ]
            if policy_ids:
                db.query(Claim).filter(Claim.policy_id.in_(policy_ids)).delete(
                    synchronize_session=False
                )
            db.query(Policy).filter(Policy.owner_id == owner_id).delete(
                synchronize_session=False
            )
            db.query(InventoryLog).filter(InventoryLog.owner_id == owner_id).delete(
                synchronize_session=False
            )
            db.query(InventoryDeclaration).filter(
                InventoryDeclaration.owner_id == owner_id
            ).delete(synchronize_session=False)
            db.query(Owner).filter(Owner.id == owner_id).delete(
                synchronize_session=False
            )
        db.commit()
        logger.info("user_data_delete_complete | phone=%s", phone)
    except Exception:
        db.rollback()
        db_error = True
        logger.exception("user_data_delete_error | phone=%s", phone)
    finally:
        db.close()

    state.sessions.pop(phone, None)

    if db_error:
        send_text(phone, "Something went wrong deleting your data. Please try again.")
    else:
        send_text(
            phone,
            "Done. Your account has been deleted. 🗑️\n\nSend *Hi* to start fresh.",
        )


def _send_main_menu(phone: str, greeting: str = ""):
    body = (f"{greeting}\n\n" if greeting else "") + "What would you like to do?"
    send_list_message(
        to=phone,
        body_text=body,
        button_label="Choose an option",
        sections=[
            {
                "title": "Your shop",
                "rows": [
                    {
                        "id": "menu_log",
                        "title": "Update stock 📦",
                        "description": "Log today's stock",
                    },
                    {
                        "id": "menu_report",
                        "title": "My record 📄",
                        "description": "Download your shop record",
                    },
                    {
                        "id": "menu_activate",
                        "title": "Activate Shield 🛡️",
                        "description": "Start your protection",
                    },
                    {
                        "id": "menu_delete",
                        "title": "Delete my account 🗑️",
                        "description": "Remove all your data",
                    },
                ],
            }
        ],
        footer_text="Visbl · Your shop record",
    )


def parse_inventory(raw: str):
    try:
        cleaned = re.sub(r"```json|```", "", raw).strip()
        data = json.loads(cleaned)
        if isinstance(data, list):
            return data
        return None
    except Exception as e:
        print("PARSE ERROR:", e)
        print("RAW:", raw)
        return None


def parse_text_inventory(text: str) -> list:
    """
    Parse a free-text stock list into inventory format.
    Handles patterns like:
      "Sneakers: 15"  /  "Sneakers 15"  /  "15 Sneakers"
      "Sneakers: 15 @ 120"  /  "Sneakers: 15 @ GHS 120"
    Price field is optional; date is not parsed from free text.
    """
    items = []
    pattern = re.compile(
        r"(?:(\d+)\s+([A-Za-z][A-Za-z\s&/'\-]+?))"
        r"|(?:([A-Za-z][A-Za-z\s&/'\-]+?)\s*[:\-]?\s*(\d+))",
        re.IGNORECASE,
    )
    price_pattern = re.compile(r"@\s*(?:GHS\s*)?(\d+(?:\.\d+)?)", re.IGNORECASE)

    for line in re.split(r"[,\n]+", text):
        line = line.strip()
        if not line:
            continue
        m = pattern.search(line)
        if not m:
            continue
        if m.group(1) and m.group(2):
            qty, name = int(m.group(1)), m.group(2).strip().rstrip(",").strip()
        else:
            name, qty = m.group(3).strip().rstrip(",").strip(), int(m.group(4))
        if not name:
            continue
        entry: dict = {"item": name.title(), "qty": qty}
        pm = price_pattern.search(line)
        if pm:
            entry["price"] = float(pm.group(1))
        items.append(entry)
    return items
