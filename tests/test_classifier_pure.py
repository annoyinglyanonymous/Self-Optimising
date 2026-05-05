"""Pure tests for the classifier label → event_type mapping."""
from app.services.classifier import label_to_event_type, VALID_LABELS


def test_known_labels_map_to_classified_event_types():
    assert label_to_event_type("positive") == "reply_classified_positive"
    assert label_to_event_type("objection") == "reply_classified_objection"
    assert label_to_event_type("ooo") == "reply_classified_ooo"
    assert label_to_event_type("unsubscribe") == "reply_classified_unsubscribe"
    assert label_to_event_type("wrong_contact") == "reply_classified_wrong_contact"


def test_neutral_falls_through_to_plain_reply():
    """A 'neutral' classification means we couldn't tell — don't fire a
    classified event, just record the raw reply."""
    assert label_to_event_type("neutral") == "reply_received"


def test_unknown_label_falls_through_to_plain_reply():
    assert label_to_event_type("garbage_value") == "reply_received"


def test_every_valid_label_has_a_mapping():
    for label in VALID_LABELS:
        result = label_to_event_type(label)
        assert result.startswith("reply_"), f"label {label!r} mapped to unexpected event type {result!r}"
