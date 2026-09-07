from datetime import timedelta

from app.models import Impact, Urgency
from app.sla import (
    calculate_priority,
    is_business_time,
    add_business_time,
    business_time_between,
    local_to_utc,
)


def test_organisation_wide_critical_is_p1():
    assert calculate_priority(Impact.ORGANISATION, Urgency.CRITICAL) == 1


def test_individual_low_is_p4():
    assert calculate_priority(Impact.INDIVIDUAL, Urgency.LOW) == 4


def test_single_user_outage_outranks_department_request():
    """One person completely blocked beats a whole team's nice-to-have."""
    assert calculate_priority(Impact.INDIVIDUAL, Urgency.CRITICAL) < \
           calculate_priority(Impact.DEPARTMENT, Urgency.LOW)


def test_weekday_midday_is_business_time():
    assert is_business_time(local_to_utc(2026, 9, 7, 12, 0)) is True


def test_saturday_is_not_business_time():
    assert is_business_time(local_to_utc(2026, 9, 5, 12, 0)) is False


def test_evening_is_not_business_time():
    assert is_business_time(local_to_utc(2026, 9, 7, 20, 0)) is False


def test_sla_clock_pauses_overnight():
    """Friday 5pm + 4 business hours lands Monday 11am, not Friday 9pm."""
    start = local_to_utc(2026, 9, 4, 17, 0)
    due = add_business_time(start, timedelta(hours=4))
    assert due == local_to_utc(2026, 9, 7, 11, 0)


def test_ticket_raised_out_of_hours_starts_next_morning():
    """Raised Saturday, the 2-hour clock starts Monday 8am."""
    start = local_to_utc(2026, 9, 5, 22, 0)
    due = add_business_time(start, timedelta(hours=2))
    assert due == local_to_utc(2026, 9, 7, 10, 0)


def test_business_time_between_excludes_weekend():
    friday_4pm = local_to_utc(2026, 9, 4, 16, 0)
    monday_10am = local_to_utc(2026, 9, 7, 10, 0)
    # 2 hours Friday afternoon + 2 hours Monday morning
    assert business_time_between(friday_4pm, monday_10am) == timedelta(hours=4)


def test_business_time_between_is_zero_for_reversed_range():
    later = local_to_utc(2026, 9, 7, 12, 0)
    earlier = local_to_utc(2026, 9, 7, 10, 0)
    assert business_time_between(later, earlier) == timedelta(0)
    