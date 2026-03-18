import json
import logging
import os
import re

import httpx
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
OPENROUTER_BASE_URL = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
OPENROUTER_SITE_URL = os.getenv("OPENROUTER_SITE_URL", "")
OPENROUTER_APP_NAME = os.getenv("OPENROUTER_APP_NAME", "Visbl")
MODEL_INTENT = os.getenv("MODEL_INTENT", "anthropic/claude-haiku-4-5")
MODEL_SUMMARY = os.getenv("MODEL_SUMMARY", "anthropic/claude-sonnet-4")


def _extract_amount_ghs(message: str):
    """Best-effort parser for amounts like '340', 'GHS 340', '340 cedis'."""
    m = re.search(
        r"(?:ghs|cedis|cedi|\u20b5)?\s*([0-9]+(?:[\.,][0-9]{1,2})?)\s*(?:ghs|cedis|cedi)?",
        message,
        flags=re.IGNORECASE,
    )
    if not m:
        return None
    value = m.group(1).replace(",", "")
    try:
        return float(value)
    except ValueError:
        return None


def _coerce_json_object(raw: str) -> dict:
    """Parse model output even when wrapped in markdown fences or prefixed text."""
    text = (raw or "").strip()
    if not text:
        return {}

    # Strip ```json ... ``` wrappers if present.
    fenced = re.search(r"```(?:json)?\s*(\{[\s\S]*\})\s*```", text, flags=re.IGNORECASE)
    if fenced:
        text = fenced.group(1).strip()

    try:
        parsed = json.loads(text)
        return parsed if isinstance(parsed, dict) else {}
    except json.JSONDecodeError:
        # Fallback: grab the first JSON-like object in the response.
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            candidate = text[start : end + 1]
            try:
                parsed = json.loads(candidate)
                return parsed if isinstance(parsed, dict) else {}
            except json.JSONDecodeError:
                return {}
        return {}


def _regex_fallback_intent(message: str) -> dict:
    """Deterministic fallback for common WhatsApp command styles."""
    text = (message or "").strip().lower()
    amount = _extract_amount_ghs(text)

    if re.search(r"\b(stock|received|restock|stock\s*in)\b", text):
        return {
            "intent": "stock_in",
            "amount_ghs": amount,
            "quantity": None,
            "product_name": None,
            "product_category": None,
            "description": message,
            "event_type": None,
            "confidence": 0.72,
            "original_language": "en",
        }

    if re.search(r"\b(sale|sales|sold)\b", text):
        return {
            "intent": "sale",
            "amount_ghs": amount,
            "quantity": None,
            "product_name": None,
            "product_category": None,
            "description": message,
            "event_type": None,
            "confidence": 0.78,
            "original_language": "en",
        }

    if re.search(r"\b(expense|paid|pay|cost|spent|spend)\b", text):
        return {
            "intent": "expense",
            "amount_ghs": amount,
            "quantity": None,
            "product_name": None,
            "product_category": None,
            "description": message,
            "event_type": None,
            "confidence": 0.76,
            "original_language": "en",
        }

    if re.search(r"\b(till|cash\s*count|cash\s*in\s*hand|drawer)\b", text):
        return {
            "intent": "cash_count",
            "amount_ghs": amount,
            "quantity": None,
            "product_name": None,
            "product_category": None,
            "description": message,
            "event_type": None,
            "confidence": 0.75,
            "original_language": "en",
        }

    if re.search(r"\b(summary|report|profit|p&l)\b", text):
        return {
            "intent": "summary_request",
            "amount_ghs": None,
            "quantity": None,
            "product_name": None,
            "product_category": None,
            "description": message,
            "event_type": None,
            "confidence": 0.74,
            "original_language": "en",
        }

    if re.search(r"\b(policy|insurance|cover|status)\b", text):
        return {
            "intent": "policy_query",
            "amount_ghs": None,
            "quantity": None,
            "product_name": None,
            "product_category": None,
            "description": message,
            "event_type": None,
            "confidence": 0.74,
            "original_language": "en",
        }

    return {
        "intent": "unknown",
        "amount_ghs": amount,
        "quantity": None,
        "product_name": None,
        "product_category": None,
        "description": message,
        "event_type": None,
        "confidence": 0.0,
        "original_language": "en",
    }


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
    logger.info(
        "Calling OpenRouter chat completion",
        extra={"model": model, "max_tokens": max_tokens},
    )
    with httpx.Client(timeout=30) as client:
        try:
            response = client.post(
                f"{OPENROUTER_BASE_URL}/chat/completions",
                headers=_headers(),
                json=payload,
            )
            response.raise_for_status()
            data = response.json()
            logger.debug(
                "Received response from OpenRouter",
                extra={"model": model},
            )
            return data["choices"][0]["message"]["content"]
        except httpx.HTTPError:
            logger.exception(
                "OpenRouter HTTP error",
                extra={"model": model},
            )
            raise


def classify_intent(message: str) -> dict:
    """Classify a WhatsApp message intent and extract structured data."""
    from app.prompts import INTENT_CLASSIFIER_PROMPT

    raw = chat(INTENT_CLASSIFIER_PROMPT, message, model=MODEL_INTENT)
    parsed = _coerce_json_object(raw)
    intent = parsed.get("intent") if isinstance(parsed, dict) else None

    if intent:
        return parsed

    logger.warning("Classifier returned unparseable/empty JSON; using regex fallback")
    return _regex_fallback_intent(message)


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
