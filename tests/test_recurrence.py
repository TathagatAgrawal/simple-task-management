"""Tests for recurring-task date arithmetic."""

from datetime import date

import pytest

from simple_task_management.recurrence import add_months, next_due


@pytest.mark.parametrize(
    ("due", "repeat", "anchor", "expected"),
    [
        (date(2026, 11, 20), "monthly", 20, date(2026, 12, 20)),
        (date(2026, 12, 20), "monthly", 20, date(2027, 1, 20)),
        (date(2027, 1, 31), "monthly", 31, date(2027, 2, 28)),
        (date(2027, 2, 28), "monthly", 31, date(2027, 3, 31)),
        (date(2028, 1, 31), "monthly", 31, date(2028, 2, 29)),
        (date(2026, 10, 31), "quarterly", 31, date(2027, 1, 31)),
        (date(2026, 11, 30), "quarterly", 30, date(2027, 2, 28)),
        (date(2028, 2, 29), "yearly", 29, date(2029, 2, 28)),
        (date(2026, 7, 31), "yearly", 31, date(2027, 7, 31)),
        (date(2026, 11, 28), "weekly", None, date(2026, 12, 5)),
        (date(2026, 12, 30), "weekly", None, date(2027, 1, 6)),
    ],
)
def test_next_due(due, repeat, anchor, expected):
    """Each repeat kind lands on the right date, including month ends and leap years."""
    assert next_due(due, repeat, anchor) == expected


def test_next_due_without_anchor_uses_due_day():
    """A missing anchor falls back to the current due date's day."""
    assert next_due(date(2026, 3, 15), "monthly", None) == date(2026, 4, 15)


def test_next_due_rejects_non_repeating():
    """Asking for the next date of a non-repeating task is a programming error."""
    with pytest.raises(ValueError):
        next_due(date(2026, 1, 1), "none", None)


def test_add_months_crosses_years():
    """Adding months rolls the year over correctly."""
    assert add_months(date(2026, 11, 15), 14, 15) == date(2028, 1, 15)
