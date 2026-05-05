import json
from openai import AsyncOpenAI
from app.config import settings
from app.models import Lead
from app.services.policy_engine import OutreachPolicy

client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)

ANGLE_DESCRIPTIONS = {
    "pain":        "Focus on a specific operational pain point. Be concrete.",
    "growth":      "Focus on growth opportunity they could achieve.",
    "compliance":  "Focus on regulatory or compliance risk.",
    "cost":        "Focus on cost reduction or ROI.",
    "speed":       "Focus on speed of implementation.",
    "credibility": "Lead with social proof and similar companies.",
}

SYSTEM_PROMPT = """You are an expert B2B copywriter writing cold outreach emails.

Rules:
- Write like a human, not a marketer
- Be specific to the lead's context
- First line must NOT start with I or the company name
- Subject line: 3-6 words, no clickbait, no exclamation marks
- Body: under 150 words
- One clear call to action
- No "I hope this finds you well"

Respond ONLY with JSON, no markdown:
{
  "subject": "<subject line>",
  "body": "<email body>",
  "preview_text": "<first 90 chars>"
}"""


async def generate_email(
    lead: Lead,
    policy: OutreachPolicy,
    touch_number: int = 1,
) -> dict:
    angle_instruction = ANGLE_DESCRIPTIONS.get(policy.angle, ANGLE_DESCRIPTIONS["pain"])

    lead_context = {
        "first_name": lead.first_name or "there",
        "company": lead.company or "your company",
        "title": lead.title or "unknown",
        "persona": lead.persona or "unknown",
        "company_size": lead.company_size or "unknown",
        "state": lead.state or "unknown",
        "tech_stack": lead.tech_stack or [],
    }

    user_message = f"""Lead profile:
{json.dumps(lead_context, indent=2)}

Angle: {policy.angle}
Angle instruction: {angle_instruction}
Touch number: {touch_number} ({"first touch" if touch_number == 1 else f"follow-up #{touch_number - 1}"})

Generate the email now."""

    response = await client.chat.completions.create(
        model="gpt-4o-mini",
        max_tokens=600,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_message},
        ],
    )

    raw = response.choices[0].message.content.strip()

    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {
            "subject": "Quick question",
            "body": raw,
            "preview_text": raw[:90],
        }


async def generate_linkedin_message(
    lead: Lead,
    policy: OutreachPolicy,
) -> dict:
    system = """You write LinkedIn outreach messages.
Connection note: under 300 characters, no pitch, just a human reason to connect.
Respond ONLY with JSON: {"type": "connection_note", "message": "<text>"}"""

    user_message = f"""Lead: {lead.first_name} {lead.last_name}, {lead.title} at {lead.company}
Persona: {lead.persona}, Angle: {policy.angle}
Generate a connection note."""

    response = await client.chat.completions.create(
        model="gpt-4o-mini",
        max_tokens=200,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user_message},
        ],
    )

    try:
        return json.loads(response.choices[0].message.content.strip())
    except json.JSONDecodeError:
        return {
            "type": "connection_note",
            "message": response.choices[0].message.content[:300],
        }