import json
import os

import httpx
from dotenv import load_dotenv

load_dotenv()

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
OPENROUTER_BASE_URL = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
OPENROUTER_SITE_URL = os.getenv("OPENROUTER_SITE_URL", "")
OPENROUTER_APP_NAME = os.getenv("OPENROUTER_APP_NAME", "Visbl")
MODEL_INTENT = os.getenv("MODEL_INTENT", "anthropic/claude-haiku-4-5")
MODEL_SUMMARY = os.getenv("MODEL_SUMMARY", "anthropic/claude-sonnet-4")


def _headers():
    return {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "HTTP-Referer": OPENROUTER_SITE_URL,
        "X-Title": OPENROUTER_APP_NAME,
        "Content-Type": "application/json",
    }


def chat(
    system_prompt: str, user_message: str, model: str = None, max_tokens: int = 512
) -> str:
    """Send a chat completion request to OpenRouter."""
    model = model or MODEL_INTENT
    payload = {
        "model": model,
        "max_tokens": max_tokens,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ],
    }
    with httpx.Client(timeout=30) as client:
        response = client.post(
            f"{OPENROUTER_BASE_URL}/chat/completions",
            headers=_headers(),
            json=payload,
        )
        response.raise_for_status()
        data = response.json()
        return data["choices"][0]["message"]["content"]


def classify_intent(message: str) -> dict:
    """Classify a WhatsApp message intent and extract structured data."""
    from app.prompts import INTENT_CLASSIFIER_PROMPT

    raw = chat(INTENT_CLASSIFIER_PROMPT, message, model=MODEL_INTENT)
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {"intent": "unknown", "confidence": 0.0}


def generate_summary(owner_data: dict, period: str = "weekly") -> str:
    """Generate a plain-language P&L summary for the owner."""
    from app.prompts import SUMMARY_PROMPT

    prompt = SUMMARY_PROMPT.format(period=period)
    message = f"Owner data: {json.dumps(owner_data)}"
    return chat(prompt, message, model=MODEL_SUMMARY, max_tokens=1024)


def generate_declaration(
    inventory_data: dict, owner_name: str, language: str = "en"
) -> dict:
    """Generate a monthly inventory declaration in English and Twi."""
    from app.prompts import DECLARATION_PROMPT

    message = f"Generate a monthly inventory declaration for {owner_name}. Data: {json.dumps(inventory_data)}"
    result_en = chat(DECLARATION_PROMPT, message, model=MODEL_SUMMARY, max_tokens=800)
    result_tw = chat(
        DECLARATION_PROMPT + " Respond in Twi (Akan).",
        message,
        model=MODEL_SUMMARY,
        max_tokens=800,
    )
    return {"en": result_en, "tw": result_tw}
