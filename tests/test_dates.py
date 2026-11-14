"""Tests for the firm-timezone date helpers."""

from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

from simple_task_management import dates

IST = ZoneInfo("Asia/Kolkata")
TODAY = date(2026, 11, 14)


def test_today_uses_ist_not_utc():
    """At 20:00 UTC it is already the next day in India."""
    assert dates.today_in(IST, datetime(2026, 11, 14, 20, 0, tzinfo=UTC)) == date(2026, 11, 15)
    assert dates.today_in(IST, datetime(2026, 11, 14, 18, 0, tzinfo=UTC)) == date(2026, 11, 14)


def test_buckets():
    """Overdue, today, the next three days, and beyond."""
    assert dates.bucket(date(2026, 11, 13), TODAY) == "overdue"
    assert dates.bucket(TODAY, TODAY) == "today"
    assert dates.bucket(date(2026, 11, 17), TODAY) == "soon"
    assert dates.bucket(date(2026, 11, 18), TODAY) is None


def test_due_labels():
    """Card chips read naturally."""
    assert dates.due_label(date(2026, 11, 12), TODAY) == ("2 days late", "red")
    assert dates.due_label(date(2026, 11, 13), TODAY) == ("1 day late", "red")
    assert dates.due_label(TODAY, TODAY) == ("Today", "amber")
    assert dates.due_label(date(2026, 11, 15), TODAY) == ("Tomorrow", "")
    assert dates.due_label(date(2026, 11, 17), TODAY) == ("Tue 17 Nov", "")
    assert dates.due_label(date(2027, 1, 5), TODAY) == ("Tue 5 Jan 2027", "")


def test_stamp():
    """Timestamps are shown in IST relative to today."""
    assert dates.stamp("2026-11-14T10:42:00+00:00", IST, TODAY) == "Today, 4:12 pm"
    assert dates.stamp("2026-11-13T05:33:00+00:00", IST, TODAY) == "Yesterday, 11:03 am"
    assert dates.stamp("2026-11-10T05:33:00+00:00", IST, TODAY) == "10 Nov, 11:03 am"
