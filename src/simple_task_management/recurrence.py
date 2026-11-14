"""Recurring-task date arithmetic."""

import calendar
from datetime import date, timedelta

REPEATS = ("none", "weekly", "monthly", "quarterly", "yearly")
REPEAT_LABELS = {
    "none": "Never",
    "weekly": "Weekly",
    "monthly": "Monthly",
    "quarterly": "Quarterly",
    "yearly": "Yearly",
}
_MONTHS = {"monthly": 1, "quarterly": 3, "yearly": 12}


def add_months(d: date, months: int, anchor_day: int) -> date:
    """Move ``d`` forward by ``months``, landing on ``anchor_day`` or the month's last day.

    Using a remembered anchor (rather than ``d.day``) means 31 Jan -> 28 Feb -> 31 Mar
    instead of drifting to the 28th forever.
    """
    total = d.year * 12 + (d.month - 1) + months
    year, month = divmod(total, 12)
    month += 1
    last = calendar.monthrange(year, month)[1]
    return date(year, month, min(anchor_day, last))


def next_due(due: date, repeat: str, repeat_day: int | None) -> date:
    """Due date of the occurrence after one due on ``due``.

    Raises:
        ValueError: if ``repeat`` is ``none`` or unknown.
    """
    if repeat == "weekly":
        return due + timedelta(days=7)
    if repeat in _MONTHS:
        return add_months(due, _MONTHS[repeat], repeat_day or due.day)
    raise ValueError(f"task does not repeat: {repeat!r}")
