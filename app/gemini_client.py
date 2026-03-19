import base64
import logging
import os

import httpx
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")
GEMINI_API_URL = (
    f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"
)

TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")

SUPPORTED_AUDIO_TYPES = {"audio/ogg", "audio/mpeg", "audio/mp4", "audio/wav", "audio/webm"}

TRANSCRIPTION_PROMPT = (
    "Transcribe the following audio message exactly as spoken. "
    "The speaker may use English, Twi (Akan), or a mix of both. "
    "Return ONLY the transcription text, nothing else. "
    "If the audio is unclear or empty, return: [inaudible]"
)


def download_twilio_media(media_url: str) -> bytes:
    """Download media from a Twilio media URL using HTTP Basic Auth."""
    logger.info("Downloading Twilio media", extra={"media_url": media_url})
    with httpx.Client(timeout=30) as client:
        response = client.get(
            media_url,
            auth=(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN),
        )
        response.raise_for_status()
        logger.info(
            "Twilio media downloaded",
            extra={"media_url": media_url, "size_bytes": len(response.content)},
        )
        return response.content


def transcribe_audio(audio_bytes: bytes, mime_type: str) -> str:
    """Send audio to Google Gemini for transcription and return the text."""
    if not GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY is not configured")

    audio_b64 = base64.b64encode(audio_bytes).decode("utf-8")

    payload = {
        "contents": [
            {
                "parts": [
                    {"text": TRANSCRIPTION_PROMPT},
                    {
                        "inline_data": {
                            "mime_type": mime_type,
                            "data": audio_b64,
                        }
                    },
                ]
            }
        ],
        "generationConfig": {
            "temperature": 0.0,
            "maxOutputTokens": 1024,
        },
    }

    logger.info(
        "Sending audio to Gemini for transcription",
        extra={"mime_type": mime_type, "audio_size_bytes": len(audio_bytes)},
    )

    with httpx.Client(timeout=60) as client:
        response = client.post(
            GEMINI_API_URL,
            params={"key": GEMINI_API_KEY},
            json=payload,
        )
        response.raise_for_status()
        data = response.json()

    try:
        text = data["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError):
        logger.error("Unexpected Gemini response structure", extra={"response": data})
        raise ValueError("Could not extract transcription from Gemini response")

    text = text.strip()
    logger.info("Gemini transcription complete", extra={"transcription_length": len(text)})
    return text


def is_supported_audio_type(content_type: str) -> bool:
    """Check if the given MIME type is a supported audio format."""
    base_type = content_type.split(";")[0].strip().lower()
    return base_type in SUPPORTED_AUDIO_TYPES
