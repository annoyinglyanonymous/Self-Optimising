"""Pure tests for policy engine pacing rules."""
from app.services.policy_engine import get_pacing


def test_known_persona_returns_its_pacing():
    rule = get_pacing("insurance_agent")
    assert rule["max_touches"] >= 1
    assert rule["touch_spacing_days"] >= 1


def test_unknown_persona_falls_back_to_default():
    unknown = get_pacing("nonexistent_persona_xyz")
    default = get_pacing("default")
    assert unknown == default


def test_none_persona_falls_back_to_default():
    assert get_pacing(None) == get_pacing("default")


def test_pacing_is_serializable():
    """The dict shape is what the scheduler reads — assert no surprises."""
    rule = get_pacing("insurance_agent")
    assert set(rule.keys()) == {"max_touches", "touch_spacing_days"}
    assert isinstance(rule["max_touches"], int)
    assert isinstance(rule["touch_spacing_days"], int)
