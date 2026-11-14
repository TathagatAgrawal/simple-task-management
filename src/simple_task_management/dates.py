"""Date helpers: the firm's "today", summary buckets and human-friendly labels.

Everything here takes ``today`` as an argument so it can be tested without touching the clock.
"""

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

SOON_DAYS = 3


def today_in(tz: ZoneInfo, now: datetime) -> date:
    """Return the calendar date in the firm's timezone for the aware datetime ``now``."""
    return now.astimezone(tz).date()


def bucket(due: date, today: date) -> str | None:
    """Classify a due date for the "coming up" strip: overdue, today, soon, or None."""
    if due < today:
        return "overdue"
    if due == today:
        return "today"
    if due <= today + timedelta(days=SOON_DAYS):
        return "soon"
    return None


def short_date(d: date, today: date) -> str:
    """Format like ``Mon 17 Nov``, adding the year only when it isn't the current one."""
    text = f"{d:%a} {d.day} {d:%b}"
    return text if d.year == today.year else f"{text} {d.year}"


def due_label(due: date, today: date) -> tuple[str, str]:
    """Return ``(text, tone)`` for a card's due chip; tone is red, amber or plain."""
    days = (due - today).days
    if days < 0:
        late = -days
        return (f"{late} day{'s' if late != 1 else ''} late", "red")
    if days == 0:
        return ("Today", "amber")
    if days == 1:
        return ("Tomorrow", "")
    return (short_date(due, today), "")


def stamp(iso: str, tz: ZoneInfo, today: date) -> str:
    """Format a stored UTC timestamp for display, e.g. ``Today, 4:12 pm`` or ``10 Nov, 4:12 pm``."""
    local = datetime.fromisoformat(iso).astimezone(tz)
    clock = local.strftime("%I:%M %p").lstrip("0").lower()
    day = local.date()
    if day == today:
        prefix = "Today"
    elif day == today - timedelta(days=1):
        prefix = "Yesterday"
    else:
        prefix = f"{day.day} {day:%b}" + ("" if day.year == today.year else f" {day.year}")
    return f"{prefix}, {clock}"


def local_date(iso: str, tz: ZoneInfo) -> date:
    """Calendar date in the firm's timezone of a stored UTC timestamp."""
    return datetime.fromisoformat(iso).astimezone(tz).date()
