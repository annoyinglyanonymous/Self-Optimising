"""Pure (no-DB) tests for bandit helpers and reward configuration."""
from app.services.bandit import make_segment_key
from app.routers.webhooks import EVENT_REWARDS


def test_segment_key_format():
    assert make_segment_key("agent", "email", "pain") == "agent|email|pain"


def test_segment_key_round_trips_components():
    key = make_segment_key("insurance_agent", "linkedin", "growth")
    persona, channel, angle = key.split("|")
    assert persona == "insurance_agent"
    assert channel == "linkedin"
    assert angle == "growth"


def test_positive_reply_outranks_objection():
    """Sanity check: a positive reply should be a stronger reward than a
    soft objection. If this ever flips, the bandit will learn the wrong thing."""
    assert EVENT_REWARDS["reply_classified_positive"] > EVENT_REWARDS["reply_classified_objection"]


def test_unsubscribe_is_strongly_negative():
    """Unsubscribe should outrank bounce as a 'never email this segment' signal."""
    assert EVENT_REWARDS["reply_classified_unsubscribe"] <= EVENT_REWARDS["bounce"]
    assert EVENT_REWARDS["reply_classified_unsubscribe"] < 0


def test_open_and_click_give_small_positive_reward():
    """Engagement events should be small-positive — not zero (they carry
    information) but not large (they're not commitments)."""
    assert 0 < EVENT_REWARDS["email_opened"] < 1
    assert 0 < EVENT_REWARDS["email_clicked"] < 1
    assert EVENT_REWARDS["email_clicked"] > EVENT_REWARDS["email_opened"]


def test_ooo_is_neutral():
    """Out-of-office is not the lead's choice — shouldn't penalize the segment."""
    assert EVENT_REWARDS["reply_classified_ooo"] == 0.0
