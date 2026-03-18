import json
import logging
import os
import threading
import time

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
IMAGE_GENERATION_MODEL = os.getenv("IMAGE_GENERATION_MODEL", "openai/dall-e-3")

ONBOARDING_IMAGE_PROMPT = (
    "Two African market traders — a man and a woman — sitting together at a colourful "
    "market stall, happily counting paper money (Ghana cedis). Vibrant, warm colours, "
    "photorealistic style, optimistic and successful mood, clean composition, high quality."
)

# Module-level cache for the generated image URL (DALL-E URLs expire after ~1 hour)
_cached_image_url: str | None = None
_cached_image_expiry: float = 0.0
_image_cache_lock = threading.Lock()


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


def generate_image(prompt: str, model: str = None) -> str:
    """Generate an image via OpenRouter and return the URL."""
    model = model or IMAGE_GENERATION_MODEL
    payload = {"model": model, "prompt": prompt, "n": 1, "size": "1024x1024"}
    logger.info("Generating image via OpenRouter", extra={"model": model})
    with httpx.Client(timeout=60) as http:
        response = http.post(
            f"{OPENROUTER_BASE_URL}/images/generations",
            headers=_headers(),
            json=payload,
        )
        response.raise_for_status()
        data = response.json()
        url = data["data"][0]["url"]
        logger.info("Image generated successfully", extra={"model": model})
        return url


def get_onboarding_image_url() -> str | None:
    """Return the onboarding welcome image URL.

    Priority:
    1. ``ONBOARDING_IMAGE_URL`` env var (static, pre-generated URL).
    2. Cached in-memory URL (refreshed every 50 minutes because DALL-E
       temporary URLs expire after ~1 hour).
    3. Freshly generated via the image API; failures are swallowed so that
       a missing image never blocks the onboarding flow.

    Thread-safe: cache reads and writes are protected by ``_image_cache_lock``.
    """
    global _cached_image_url, _cached_image_expiry

    # Static override — useful for production where the image is pre-hosted.
    static_url = os.getenv("ONBOARDING_IMAGE_URL")
    if static_url:
        return static_url

    with _image_cache_lock:
        # Re-check inside the lock to avoid duplicate generation.
        if _cached_image_url and time.time() < _cached_image_expiry:
            return _cached_image_url

        # Generate a new image and cache it for 50 minutes.
        try:
            url = generate_image(ONBOARDING_IMAGE_PROMPT)
            _cached_image_url = url
            _cached_image_expiry = time.time() + 50 * 60
            return _cached_image_url
        except Exception:
            logger.exception("Failed to generate onboarding image; proceeding without it")
            return None
