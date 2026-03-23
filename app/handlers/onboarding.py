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
from app.handlers.whatsapp_manager import (
    send_reply_buttons,
    send_text,
    send_whatsapp_flow,
)
from app.logging_config import setup_logging

load_dotenv()

setup_logging()
logger = logging.getLogger(__name__)

domain_url = os.getenv("DOMAIN_URL")
ACCESS_TOKEN = os.getenv("WHATSAPP_ACCESS_TOKEN")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
onboard_flow_id = os.getenv("ONBOARDING_FLOW_ID")

setup_logging()
logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────
# STEP 1 — Greeting button
# ─────────────────────────────────────────────


async def step_1_greeting_button(phone: str):
    logger.info("onboarding_step_1_start | phone=%s", phone)

    send_reply_buttons(
        to=phone,
        body_text=(
            "Rainy season is near. "
            "The best time to protect your shop is before anything happens.\n\n"
            "Keep your records safe on your phone and protect what you have built."
        ),
        buttons=[{"id": "start_onboarding", "title": "Show me how"}],
        header_image_url=f"{domain_url}/assets/greeting_out.png",
        footer_text="Visbl·",
    )
    state.sessions[phone] = {"step": "AWAITING_BUTTON_CLICK"}

    logger.info("onboarding_step_1_complete | phone=%s", phone)


async def step_1_greeting_interactive_flow(phone: str):
    logger.info("onboarding_step_1_flow_start | phone=%s", phone)

    flow_token = str(uuid.uuid4())
    state.sessions[phone] = {"step": "AWAITING_FLOW", "flow_token": flow_token}

    send_whatsapp_flow(
        to=phone,
        header_image_url="https://yourdomain.com/assets/greeting.jpg",
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
# STEP 2 — Ask for photo
# ─────────────────────────────────────────────


async def step_2_ask_for_photo(phone: str):
    logger.info("onboarding_step_2_start | phone=%s", phone)

    send_text(
        phone,
        "Great! Let's build your shop record. 📸\n\n"
        "Please take a clear photo of your shelves — "
        "include all your stock so we can count everything properly.\n\n"
        "Take a photo and send it here.",
    )
    state.sessions[phone] = {"step": "AWAITING_PHOTO"}
    raw = response["content"][0]["text"]

    inventory = parse_inventory(raw)

    logger.info("onboarding_step_2_complete | phone=%s", phone)


# ─────────────────────────────────────────────
# STEP 3 — Receive photo + download from Meta
# Fetches media URL, downloads image, and sends
# the acknowledgement message in parallel.
# ─────────────────────────────────────────────


async def step_3_handle_photo(phone: str, message: dict, session: dict):
    t0 = time.perf_counter()
    logger.info("onboarding_step_3_start | phone=%s", phone)

    media_id = message["image"]["id"]

    # Fetch the media download URL from Meta
    async with httpx.AsyncClient(timeout=10) as client:
        url_resp = await client.get(
            f"https://graph.facebook.com/v22.0/{media_id}",
            headers={"Authorization": f"Bearer {ACCESS_TOKEN}"},
        )

    media_url = url_resp.json().get("url")

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

    # Download image and send acknowledgement in parallel
    async with httpx.AsyncClient(timeout=15) as client:
        img_resp, _ = await asyncio.gather(
            client.get(media_url, headers={"Authorization": f"Bearer {ACCESS_TOKEN}"}),
            asyncio.to_thread(
                send_text, phone, "Got it! Counting your stock now... ⏳"
            ),
        )

    image_b64 = base64.b64encode(img_resp.content).decode("utf-8")

    logger.debug(
        "onboarding_step_3_image_downloaded | phone=%s size_kb=%.1f elapsed=%.2fs",
        phone,
        len(img_resp.content) / 1024,
        time.perf_counter() - t0,
    )

    inventory = await step_4_parse_inventory_with_claude(phone, image_b64)
    print(inventory, "what is inventory?")

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
                max_tokens=512,
                system=(
                    "You are an inventory clerk at a market in Accra, Ghana. "
                    "Look at this shop photo. List product categories and estimated quantities. "
                    "Return ONLY a valid JSON array. No explanation. No markdown. "
                    'Example: [{"item": "Sneakers", "qty": 15}, {"item": "Heels", "qty": 10}]'
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
                                "text": "What stock do you see? Return JSON only.",
                            },
                        ],
                    }
                ],
            ),
            timeout=15.0,
        )
        print("raw from claise", response.content[0].text.strip())

        raw = raw.strip()

        print("RAW CLAUDE RESPONSE:", raw)

        # remove markdown code block
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            raw = raw.replace("json", "", 1).strip()

        inventory = json.loads(raw)

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

    items_text = "\n".join([f"• {i['item']}: {i['qty']} pieces" for i in inventory])
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
            footer_text="Visbl · Your shop record",
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
                {"id": "inventory_correct", "title": "Yes, looks good ✅"},
                {"id": "inventory_edit", "title": "No, I want to change it"},
            ],
            footer_text="Visbl · Your shop record",
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
        "Reply with the amount in Ghana Cedis. Example: *50000*",
    )
    state.sessions[phone]["step"] = "AWAITING_CAPS_Q1"


async def step_5b_handle_stock_value(phone: str, text: str, session: dict):
    logger.info("onboarding_step_5b_response | phone=%s raw_input=%s", phone, text)

    cleaned = "".join(filter(str.isdigit, text))

    if not cleaned:
        logger.warning("onboarding_step_5b_invalid_input | phone=%s", phone)
        send_text(
            phone,
            "Please reply with just the number. Example: *50000*\n\n"
            "What is the total value of all the stock in your shop?",
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
        "Reply with the amount in Ghana Cedis. Example: *10000*",
    )
    state.sessions[phone]["step"] = "AWAITING_CAPS_Q2"


async def step_5c_handle_restart_cap(phone: str, text: str, session: dict):
    logger.info("onboarding_step_5c_response | phone=%s raw_input=%s", phone, text)

    cleaned = "".join(filter(str.isdigit, text))

    if not cleaned:
        logger.warning("onboarding_step_5c_invalid_input | phone=%s", phone)
        send_text(
            phone,
            "Please reply with just the number. Example: *10000*\n\n"
            "How much would you need to restock and reopen after a flood or fire?",
        )
        return

    session["restart_cap"] = float(cleaned)
    state.sessions[phone] = session

    logger.info(
        "onboarding_step_5c_restart_cap_saved | phone=%s value=%s", phone, cleaned
    )

    await step_6_complete_onboarding(phone, session)


# ─────────────────────────────────────────────
# STEP 6 — Tier logic + confirmation
# ─────────────────────────────────────────────


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

    try:
        await app.DB.execute(
            """
            INSERT INTO owners (phone, inventory, stock_value, restart_cap, tier, status)
            VALUES (?, ?, ?, ?, ?, 'pending')
            """,
            [
                phone,
                json.dumps(session["inventory"]),
                session["stock_value"],
                session["restart_cap"],
                tier["tier"],
            ],
        )
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

    send_text(
        phone,
        f"Record Secured! 🛡️\n\n"
        f"Based on your Restart Cap of *{restart_formatted}*, you qualify for the "
        f"*{tier['tier']}* at *{tier['price']}*.\n\n"
        f"Your 30-day verification period starts now. "
        f"We will be in touch shortly to confirm your shop details.",
    )

    state.sessions[phone]["step"] = "COMPLETE"

    logger.info(
        "onboarding_complete | phone=%s tier=%s restart_cap=%s",
        phone,
        tier["tier"],
        session["restart_cap"],
    )


# ─────────────────────────────────────────────
# EXISTING USER HANDLER (post-onboarding)
# ─────────────────────────────────────────────


async def handle_existing_user(phone: str, message: dict, owner: dict):
    logger.info("existing_user_message | phone=%s", phone)
    send_text(phone, "Welcome back! How can I help you today?")


def parse_inventory(raw: str):
    try:
        cleaned = re.sub(r"```json|```", "", raw).strip()
        data = json.loads(cleaned)

        # validate structure
        if isinstance(data, list):
            return data

        return None

    except Exception as e:
        print("PARSE ERROR:", e)
        print("RAW:", raw)
        return None
