import json

import anthropic

from app.prompts import INTENT_CLASSIFIER_PROMPT

client = anthropic.Anthropic()


def parse_message(message: str) -> dict:
    """Parse a WhatsApp message into structured intent + data."""

    def _call(extra=""):
        return client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=256,
            temperature=0.0,
            system=INTENT_CLASSIFIER_PROMPT + extra,
            messages=[{"role": "user", "content": message}],
        )

    try:
        r = _call()
        return json.loads(r.content[0].text)
    except json.JSONDecodeError:
        try:
            r = _call("\nReturn ONLY raw JSON. No text before or after.")
            return json.loads(r.content[0].text)
        except Exception:
            return {"intent": "unknown", "confidence": 0.0}


def generate_weekly_summary(owner_name: str, week_data: dict, lang: str) -> str:
    """Generate a plain-language weekly P&L summary."""
    lang_label = "Twi" if lang == "tw" else "English"
    prompt = f"""Generate a weekly P&L summary for {owner_name}.
Data: {json.dumps(week_data)}
Language: {lang_label}
Max 5 sentences. No jargon. Be warm and encouraging."""

    r = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=512,
        temperature=0.3,
        messages=[{"role": "user", "content": prompt}],
    )
    return r.content[0].text


def generate_credit_narrative(
    owner_name: str, score: int, profile_data: dict, lang: str
) -> str:
    """Generate a credit readiness interpretation."""
    lang_label = "Twi" if lang == "tw" else "English"
    prompt = f"""Generate a credit readiness message for {owner_name}.
Score: {score}/100
Data: {json.dumps(profile_data)}
Language: {lang_label}
Keep it under 4 sentences. Be honest and encouraging."""

    r = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=512,
        temperature=0.3,
        messages=[{"role": "user", "content": prompt}],
    )
    return r.content[0].text
