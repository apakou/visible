import os

import requests
from dotenv.main import load_dotenv

load_dotenv()

PHONE_NUMBER_ID = os.getenv("PHONE_NUMBER_ID")
ACCESS_TOKEN = os.getenv("WHATSAPP_ACCESS_TOKEN")
BASE_URL = f"https://graph.facebook.com/v22.0/{PHONE_NUMBER_ID}"
HEADERS = {
    "Authorization": f"Bearer {ACCESS_TOKEN}",
    "Content-Type": "application/json",
}


def _post(payload: dict) -> dict:
    """Send any message payload to the WhatsApp API."""
    url = f"{BASE_URL}/messages"
    response = requests.post(url, headers=HEADERS, json=payload)
    print("Status:", response.status_code)
    print("Response:", response.text)
    return response.json()


# ─────────────────────────────────────────────
# 1. TYPING INDICATOR
# ─────────────────────────────────────────────


def send_typing_indicator(to: str) -> dict:
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "reaction",  # WhatsApp uses a 'status' trick for typing
        "status": {
            "status": "read",
            "message_id": "typing",  # placeholder — real impl needs last message_id
        },
    }
    # NOTE: The proper way is to mark the last received message as 'read'
    # which triggers the typing indicator on the sender's side.
    # See send_read_receipt() below for the correct approach.
    return payload  # placeholder — use send_read_receipt in practice


def send_read_receipt(to: str, message_id: str) -> dict:
    """
    Mark a message as read. This shows the blue ticks AND
    triggers the typing indicator on the user's side.
    Always call this before replying so users know you received their message.

    Args:
        to: User's phone number
        message_id: The 'id' field from the incoming webhook message object
    """
    payload = {
        "messaging_product": "whatsapp",
        "status": "read",
        "message_id": message_id,
    }
    url = f"{BASE_URL}/messages"
    response = requests.post(url, headers=HEADERS, json=payload)
    print("Read receipt status:", response.status_code)
    return response.json()


# ─────────────────────────────────────────────
# 2. TEXT MESSAGE
# ─────────────────────────────────────────────


def send_text(to: str, body: str, preview_url: bool = False) -> dict:
    """
    Send a plain text message.
    Supports WhatsApp formatting: *bold*, _italic_, ~strikethrough~, `code`

    Args:
        to: Recipient phone number (e.g. "233501234567")
        body: Message text (max 4096 characters)
        preview_url: Show a link preview if the text contains a URL
    """
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {
            "body": body,
            "preview_url": preview_url,
        },
    }
    return _post(payload)


# ─────────────────────────────────────────────
# 3. TEMPLATE MESSAGE
# ─────────────────────────────────────────────


def send_template(
    to: str,
    template_name: str,
    language_code: str = "en_US",
    components: list = None,
) -> dict:
    """
    Send an approved WhatsApp template message.
    Required for first-contact messages outside the 24-hour window.

    Args:
        to: Recipient phone number
        template_name: Exact name of your approved template in Meta Business Manager
        language_code: Language of the template (e.g. "en_US", "en_GB")
        components: List of component objects to fill template variables.
                    See examples below.

    Example — template with a body variable {{1}}:
        send_template(
            to="233501234567",
            template_name="shop_onboarding_reminder",
            components=[{
                "type": "body",
                "parameters": [{"type": "text", "text": "Ruth"}]
            }]
        )

    Example — template with a header image + body text:
        send_template(
            to="233501234567",
            template_name="welcome_with_image",
            components=[
                {
                    "type": "header",
                    "parameters": [{"type": "image", "image": {"link": "https://..."}}]
                },
                {
                    "type": "body",
                    "parameters": [{"type": "text", "text": "Ruth"}]
                }
            ]
        )
    """
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "template",
        "template": {
            "name": template_name,
            "language": {"code": language_code},
        },
    }
    if components:
        payload["template"]["components"] = components

    return _post(payload)


# ─────────────────────────────────────────────
# 4. INTERACTIVE — REPLY BUTTONS
# ─────────────────────────────────────────────


def send_reply_buttons(
    to: str,
    body_text: str,
    buttons: list[dict],
    header_text: str = None,
    footer_text: str = None,
) -> dict:
    """
    Send a message with up to 3 tappable reply buttons.
    Best for yes/no choices or short option sets.

    Args:
        to: Recipient phone number
        body_text: Main message text
        buttons: List of dicts with 'id' and 'title' keys (max 3 buttons, title max 20 chars)
        header_text: Optional bold text above the body
        footer_text: Optional small grey text below the buttons

    Example:
        send_reply_buttons(
            to="233501234567",
            body_text="Does this stock list look correct?",
            buttons=[
                {"id": "confirm_yes", "title": "Yes, looks good ✅"},
                {"id": "confirm_no",  "title": "No, I want to edit"},
            ],
            footer_text="Visbl · Your shop record"
        )
    """
    formatted_buttons = [
        {
            "type": "reply",
            "reply": {"id": btn["id"], "title": btn["title"]},
        }
        for btn in buttons[:3]  # WhatsApp max is 3
    ]

    interactive = {
        "type": "button",
        "body": {"text": body_text},
        "action": {"buttons": formatted_buttons},
    }
    if header_text:
        interactive["header"] = {"type": "text", "text": header_text}
    if footer_text:
        interactive["footer"] = {"text": footer_text}

    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "interactive",
        "interactive": interactive,
    }
    return _post(payload)


# ─────────────────────────────────────────────
# 5. INTERACTIVE — LIST MESSAGE
# ─────────────────────────────────────────────


def send_list_message(
    to: str,
    body_text: str,
    button_label: str,
    sections: list[dict],
    header_text: str = None,
    footer_text: str = None,
) -> dict:
    """
    Send a message with a scrollable list of options (up to 10 items total).
    Better than buttons when there are more than 3 choices.

    Args:
        to: Recipient phone number
        body_text: Main message text
        button_label: Label on the button that opens the list (max 20 chars)
        sections: List of section dicts. Each section has a 'title' and 'rows'.
                  Each row has 'id', 'title', and optional 'description'.
        header_text: Optional bold text above the body
        footer_text: Optional small grey text below

    Example:
        send_list_message(
            to="233501234567",
            body_text="What type of stock do you mainly sell?",
            button_label="Choose category",
            sections=[{
                "title": "Clothing & Footwear",
                "rows": [
                    {"id": "cat_footwear",  "title": "Shoes & Sandals",    "description": "All types of footwear"},
                    {"id": "cat_clothing",  "title": "Tops & Bottoms",     "description": "Shirts, trousers, dresses"},
                    {"id": "cat_bags",      "title": "Bags & Accessories", "description": "Handbags, jewellery"},
                ]
            }, {
                "title": "Food & Goods",
                "rows": [
                    {"id": "cat_food",      "title": "Food Items",         "description": "Grains, packaged goods"},
                    {"id": "cat_household", "title": "Household Items",    "description": "Cleaning, kitchenware"},
                ]
            }]
        )
    """
    formatted_sections = []
    for section in sections:
        formatted_rows = [
            {
                "id": row["id"],
                "title": row["title"],
                **(
                    {"description": row["description"]}
                    if row.get("description")
                    else {}
                ),
            }
            for row in section.get("rows", [])
        ]
        formatted_sections.append(
            {
                "title": section.get("title", ""),
                "rows": formatted_rows,
            }
        )

    interactive = {
        "type": "list",
        "body": {"text": body_text},
        "action": {
            "button": button_label,
            "sections": formatted_sections,
        },
    }
    if header_text:
        interactive["header"] = {"type": "text", "text": header_text}
    if footer_text:
        interactive["footer"] = {"text": footer_text}

    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "interactive",
        "interactive": interactive,
    }
    return _post(payload)


# ─────────────────────────────────────────────
# 6. IMAGE MESSAGE
# ─────────────────────────────────────────────


def send_image(
    to: str, image_url: str = None, media_id: str = None, caption: str = None
) -> dict:
    """
    Send an image. Use either a public URL or a pre-uploaded Meta media_id.
    For production, upload images first with the Media API and use media_id
    (faster, more reliable than URLs).

    Args:
        to: Recipient phone number
        image_url: Publicly accessible URL of the image (JPEG, PNG, WebP — max 5MB)
        media_id: Meta media ID from a prior upload (preferred for production)
        caption: Optional text shown below the image (max 1024 chars)

    Example with URL:
        send_image(
            to="233501234567",
            image_url="https://yourdomain.com/visbl-shield-tiers.png",
            caption="Your Shield tier options 🛡️"
        )

    Example with media_id:
        send_image(to="233501234567", media_id="1234567890", caption="Receipt saved ✅")
    """
    if not image_url and not media_id:
        raise ValueError("Provide either image_url or media_id")

    image_obj = {}
    if media_id:
        image_obj["id"] = media_id
    else:
        image_obj["link"] = image_url
    if caption:
        image_obj["caption"] = caption

    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "image",
        "image": image_obj,
    }
    return _post(payload)


# ─────────────────────────────────────────────
# 7. DOCUMENT MESSAGE
# ─────────────────────────────────────────────


def send_document(
    to: str,
    document_url: str = None,
    media_id: str = None,
    filename: str = "document.pdf",
    caption: str = None,
) -> dict:
    """
    Send a document file (PDF, DOCX, XLSX, etc.).
    Great for sending inventory reports, policy documents, or receipts.

    Args:
        to: Recipient phone number
        document_url: Publicly accessible URL of the document (max 100MB)
        media_id: Meta media ID from a prior upload (preferred)
        filename: The display name shown in the chat (e.g. "Visbl_Report_June.pdf")
        caption: Optional text shown below the document

    Example:
        send_document(
            to="233501234567",
            document_url="https://yourdomain.com/reports/ruth_inventory.pdf",
            filename="Ruth_Shop_Record.pdf",
            caption="Here is your shop record for June 2025 📄"
        )
    """
    if not document_url and not media_id:
        raise ValueError("Provide either document_url or media_id")

    doc_obj = {"filename": filename}
    if media_id:
        doc_obj["id"] = media_id
    else:
        doc_obj["link"] = document_url
    if caption:
        doc_obj["caption"] = caption

    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "document",
        "document": doc_obj,
    }
    return _post(payload)


# ─────────────────────────────────────────────
# 8. WHATSAPP FLOW
# ─────────────────────────────────────────────


def send_whatsapp_flow(
    to: str,
    body_text: str,
    flow_id: str,
    flow_cta: str,
    flow_token: str,
    screen: str = None,
    prefill_data: dict = None,
    header_text: str = None,
    footer_text: str = None,
    mode: str = "published",
) -> dict:
    """
    Send a WhatsApp Flow — a native multi-screen form inside WhatsApp.
    Use this for inventory verification, restart cap questions, and onboarding steps.

    Args:
        to: Recipient phone number
        body_text: Message shown before the user opens the Flow
        flow_id: Your Flow ID from Meta Business Manager
        flow_cta: Button label that opens the Flow (e.g. "Review My Records")
        flow_token: A unique token you generate per send (use uuid4)
        screen: The screen to open first (must match a screen ID in your Flow JSON)
        prefill_data: Dict of data to pre-fill form fields (e.g. inventory items from Claude)
        header_text: Optional bold header above body
        footer_text: Optional footer below CTA button
        mode: "published" for live, "draft" for testing

    Example — inventory verification flow pre-filled from Claude:
        import uuid
        send_whatsapp_flow(
            to="233501234567",
            body_text="Here is what I found in your shop. Please check and correct if needed.",
            flow_id="1234567890123456",
            flow_cta="Review My Records",
            flow_token=str(uuid.uuid4()),
            screen="INVENTORY_REVIEW",
            prefill_data={
                "items": [
                    {"name": "Sneakers", "qty": 15},
                    {"name": "Heels",    "qty": 10},
                ]
            },
            footer_text="Visbl · Your shop record"
        )
    """
    action_payload = (
        {
            "screen": screen,
            "data": prefill_data or {},
        }
        if screen
        else {}
    )

    flow_params = {
        "flow_message_version": "3",
        "flow_token": flow_token,
        "flow_id": flow_id,
        "flow_cta": flow_cta,
        "flow_action": "navigate" if screen else "data_exchange",
        "mode": mode,
    }
    if action_payload:
        flow_params["flow_action_payload"] = action_payload

    interactive = {
        "type": "flow",
        "body": {"text": body_text},
        "action": {
            "name": "flow",
            "parameters": flow_params,
        },
    }
    if header_text:
        interactive["header"] = {"type": "text", "text": header_text}
    if footer_text:
        interactive["footer"] = {"text": footer_text}

    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "interactive",
        "interactive": interactive,
    }
    return _post(payload)
