import os
import uuid

from dotenv import load_dotenv

import state
from app.handlers.whatsapp_manager import send_reply_buttons, send_whatsapp_flow

load_dotenv()
domain_url = os.getenv("DOMAIN_URL")

onboard_flow_id = os.getenv("ONBOARDING_FLOW_ID")


async def step_1_greeting_button(phone: str):
    send_reply_buttons(
        to=phone,
        body_text=(
            "Rainy season is near. "
            "The best time to protect your shop is before anything happens.\n\n"
            "Keep your records safe on your phone. "
            "Protect what you have built."
        ),
        buttons=[{"id": "start_onboarding", "title": "Show me how"}],
        header_image_url=f"{domain_url}/assets/greeting.png",
        footer_text="Visbl·",
    )
    state.sessions[phone] = {"step": "AWAITING_BUTTON_CLICK"}


async def step_1_greeting_buttoeen(phone: str):
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
        flow_cta="See how my shop can be protected",
        flow_token=flow_token,
        screen="WELCOME",
        footer_text="Visbl·",
    )
