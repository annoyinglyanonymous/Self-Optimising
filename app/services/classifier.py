from openai import AsyncOpenAI
import json
from app.config import settings

client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)

VALID_LABELS = {"positive", "objection", "ooo", "unsubscribe", "wrong_contact", "neutral"}

SYSTEM_PROMPT = """You are a reply classifier for B2B outreach.

Classify the reply into exactly one label:
- positive: genuine buying interest
- objection: not interested
- ooo: out of office auto-reply
- unsubscribe: wants to stop contact
- wrong_contact: wrong person or company
- neutral: unclear

Respond ONLY with JSON, no explanation:
{
  "label": "<label>",
  "confidence": <0.0-1.0>,
  "reasoning": "<one sentence>"
}"""


async def classify_reply(
    reply_text: str,
    original_subject: str | None = None,
    persona: str | None = None,
) -> dict:
    context_parts = []
    if persona:
        context_parts.append(f"Prospect persona: {persona}")
    if original_subject:
        context_parts.append(f"Original subject: {original_subject}")
    context_parts.append(f"Reply:\n{reply_text}")

    user_message = "\n".join(context_parts)

    response = await client.chat.completions.create(
        model="gpt-4o-mini",
        max_tokens=200,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_message},
        ],
    )

    raw = response.choices[0].message.content.strip()

    try:
        result = json.loads(raw)
    except json.JSONDecodeError:
        return {"label": "neutral", "confidence": 0.0, "reasoning": "Parse error"}

    if result.get("label") not in VALID_LABELS:
        result["label"] = "neutral"

    return result


def label_to_event_type(label: str) -> str:
    mapping = {
        "positive":      "reply_classified_positive",
        "objection":     "reply_classified_objection",
        "ooo":           "reply_classified_ooo",
        "unsubscribe":   "reply_classified_unsubscribe",
        "wrong_contact": "reply_classified_wrong_contact",
        "neutral":       "reply_received",
    }
    return mapping.get(label, "reply_received")