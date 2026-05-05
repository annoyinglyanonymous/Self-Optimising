from dataclasses import dataclass
from sqlalchemy.ext.asyncio import AsyncSession
from app.models import Lead
from app.services.bandit import sample_best_action

AVAILABLE_CHANNELS = ["email", "linkedin"]
AVAILABLE_ANGLES = ["pain", "growth", "compliance", "cost", "speed", "credibility"]

@dataclass
class OutreachPolicy:
    channel: str
    angle: str
    template_family: str
    send_day: str
    send_hour_local: int
    max_touches: int
    touch_spacing_days: int
    is_bandit_decision: bool = False
    is_exploration: bool = False


_MANUAL_RULES: dict[str, dict] = {
    "insurance_agent": {
        "channel": "email",
        "angle": "pain",
        "template_family": "insurance_agent_pain_v1",
        "send_day": "tuesday",
        "send_hour_local": 9,
        "max_touches": 5,
        "touch_spacing_days": 3,
    },
    "insurance_agency_owner": {
        "channel": "email",
        "angle": "growth",
        "template_family": "agency_owner_growth_v1",
        "send_day": "wednesday",
        "send_hour_local": 8,
        "max_touches": 6,
        "touch_spacing_days": 4,
    },
    "default": {
        "channel": "email",
        "angle": "pain",
        "template_family": "generic_pain_v1",
        "send_day": "tuesday",
        "send_hour_local": 9,
        "max_touches": 4,
        "touch_spacing_days": 3,
    },
}


def _manual_policy(lead: Lead) -> OutreachPolicy:
    rule = _MANUAL_RULES.get(lead.persona or "default", _MANUAL_RULES["default"])
    return OutreachPolicy(**rule)


def get_pacing(persona: str | None) -> dict:
    """Pacing rule for a persona: max_touches + touch_spacing_days. Used by
    the scheduler to decide whether a lead is due for the next touch."""
    rule = _MANUAL_RULES.get(persona or "default", _MANUAL_RULES["default"])
    return {
        "max_touches": rule["max_touches"],
        "touch_spacing_days": rule["touch_spacing_days"],
    }


async def decide_policy(db: AsyncSession, lead: Lead) -> OutreachPolicy:
    if not lead.persona:
        return _manual_policy(lead)

    channel, angle, is_exploration = await sample_best_action(
        db=db,
        persona=lead.persona,
        channels=AVAILABLE_CHANNELS,
        angles=AVAILABLE_ANGLES,
    )

    base_rule = _MANUAL_RULES.get(lead.persona, _MANUAL_RULES["default"])

    return OutreachPolicy(
        channel=channel,
        angle=angle,
        template_family=f"{lead.persona}_{angle}_v1",
        send_day=base_rule["send_day"],
        send_hour_local=base_rule["send_hour_local"],
        max_touches=base_rule["max_touches"],
        touch_spacing_days=base_rule["touch_spacing_days"],
        is_bandit_decision=True,
        is_exploration=is_exploration,
    )