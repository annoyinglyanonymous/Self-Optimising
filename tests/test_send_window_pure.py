"""Pure tests for is_in_send_window — no DB, no scheduler running."""
from datetime import datetime, timezone

from app.services.scheduler import is_in_send_window


# A fixed UTC moment we can shift around. Tuesday 2026-05-05 17:30 UTC.
# That's:
#   17:30 UTC               → weekday 1 (Tue)
#   10:30 America/Los_Angeles (UTC-7 during DST) → weekday 1 (Tue)
#   13:30 America/New_York (UTC-4 during DST)    → weekday 1 (Tue)
TUE_UTC = datetime(2026, 5, 5, 17, 30, tzinfo=timezone.utc)


def test_all_empty_is_always_true():
    """Legacy behavior: no window configured → always in window."""
    assert is_in_send_window(TUE_UTC, "", "", "", "") is True


def test_inside_window_basic_utc():
    # Tue at 17:30 UTC, allowed Tue, 09-23 → in
    assert is_in_send_window(TUE_UTC, "1", "9", "23", "UTC") is True


def test_outside_hours_too_early_in_local_tz():
    # Tue 17:30 UTC = Tue 10:30 LA. Window 14-17 LA → 10:30 is before start.
    assert is_in_send_window(TUE_UTC, "0,1,2,3,4", "14", "17", "America/Los_Angeles") is False


def test_outside_hours_too_late_in_local_tz():
    # Tue 17:30 UTC = Tue 10:30 LA. Window 7-10 LA → 10:30 is past end (exclusive).
    assert is_in_send_window(TUE_UTC, "0,1,2,3,4", "7", "10", "America/Los_Angeles") is False


def test_inside_window_in_specified_tz():
    # Tue 17:30 UTC = Tue 13:30 NY. Window 9-17 NY weekdays → in.
    assert is_in_send_window(TUE_UTC, "0,1,2,3,4", "9", "17", "America/New_York") is True


def test_excluded_day():
    # Make it a Saturday: 2026-05-09 17:30 UTC is a Saturday.
    sat_utc = datetime(2026, 5, 9, 17, 30, tzinfo=timezone.utc)
    # Window: weekdays only.
    assert is_in_send_window(sat_utc, "0,1,2,3,4", "9", "23", "UTC") is False
    # Window: weekends only → in.
    assert is_in_send_window(sat_utc, "5,6", "9", "23", "UTC") is True


def test_end_hour_exclusivity():
    # noon UTC, window 9-12 → excluded (12 is exclusive).
    noon = datetime(2026, 5, 5, 12, 0, tzinfo=timezone.utc)
    assert is_in_send_window(noon, "1", "9", "12", "UTC") is False
    # 11:59:59 UTC → in
    almost = datetime(2026, 5, 5, 11, 59, 59, tzinfo=timezone.utc)
    assert is_in_send_window(almost, "1", "9", "12", "UTC") is True


def test_start_hour_inclusivity():
    # 09:00:00 UTC, window 9-17 → in (start is inclusive).
    nine = datetime(2026, 5, 5, 9, 0, tzinfo=timezone.utc)
    assert is_in_send_window(nine, "1", "9", "17", "UTC") is True


def test_only_days_set_no_hour_constraint():
    # Days only — any hour is fine. Tuesday at 03:00 UTC.
    early = datetime(2026, 5, 5, 3, 0, tzinfo=timezone.utc)
    assert is_in_send_window(early, "0,1,2,3,4", "", "", "UTC") is True
    # Saturday at 03:00 UTC, weekday-only filter → out.
    sat = datetime(2026, 5, 9, 3, 0, tzinfo=timezone.utc)
    assert is_in_send_window(sat, "0,1,2,3,4", "", "", "UTC") is False


def test_only_hours_set_no_day_constraint():
    # Hours only — Saturday but during the window → in.
    sat_noon = datetime(2026, 5, 9, 12, 0, tzinfo=timezone.utc)
    assert is_in_send_window(sat_noon, "", "9", "17", "UTC") is True


def test_invalid_timezone_falls_back_to_utc():
    # If they fat-finger the TZ string, behavior should fall back to UTC and
    # the window check should still work, not crash.
    assert is_in_send_window(TUE_UTC, "1", "9", "23", "Mars/Phobos") is True


def test_garbage_day_csv_treated_as_no_day_filter():
    """A non-numeric day CSV becomes no-day-filter (same as empty)."""
    # Saturday — should be out if "0,1,2,3,4" applied.
    sat_noon = datetime(2026, 5, 9, 12, 0, tzinfo=timezone.utc)
    assert is_in_send_window(sat_noon, "garbage,more-garbage", "9", "17", "UTC") is True


def test_dst_aware_los_angeles():
    # 2026-05-05 is well inside DST in LA. UTC-7 expected.
    # 17:30 UTC -> 10:30 LA (DST). Window 10-11 → in.
    assert is_in_send_window(TUE_UTC, "1", "10", "11", "America/Los_Angeles") is True
    # 17:30 UTC -> 10:30 LA. Window 9-10 → out (10 is exclusive end).
    assert is_in_send_window(TUE_UTC, "1", "9", "10", "America/Los_Angeles") is False
