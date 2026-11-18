"""Response models for the JSON API.

They exist so ``/api/openapi.json`` describes every response exactly. The web client's TypeScript
types are generated from that file (``npm run types`` in ``web/``), so a field renamed here
breaks the client's build instead of breaking it silently in someone's browser.
"""

from datetime import date
from typing import Literal

from pydantic import BaseModel

Status = Literal["todo", "doing", "done"]
Mode = Literal["alert", "inbox", "off"]


class Option(BaseModel):
    """A value with the label people see for it."""

    value: str
    label: str


class NotificationKind(BaseModel):
    """One kind of notification a person can choose a mode for."""

    kind: str
    label: str
    help: str


class Meta(BaseModel):
    """Things the page needs that don't change per request, plus the firm's date today."""

    today: date
    statuses: list[Option]
    repeats: list[Option]
    notification_kinds: list[NotificationKind]
    notification_modes: list[Option]


class Person(BaseModel):
    """A person as other people see them."""

    id: int
    name: str
    username: str
    is_admin: bool


class Assignee(BaseModel):
    """Someone a task is assigned to."""

    id: int
    name: str


class Me(Person):
    """The signed-in person, with their settings and the CSRF token for cookie clients."""

    theme: Literal["system", "light", "dark"]
    must_change_password: bool
    csrf_token: str


class Session(BaseModel):
    """The result of signing in."""

    token: str
    user: Me


class PersonCreated(BaseModel):
    """A new person with their one-time temporary password."""

    person: Person
    temporary_password: str


class TemporaryPassword(BaseModel):
    """A freshly reset temporary password."""

    temporary_password: str


class Card(BaseModel):
    """A task as it appears on the board."""

    id: int
    title: str
    status: Status
    due: date
    due_label: str
    due_tone: str
    repeat: str
    repeat_label: str
    assignees: list[Assignee]
    comments: int


class Board(BaseModel):
    """The three columns."""

    todo: list[Card]
    doing: list[Card]
    done: list[Card]


class SummaryItem(BaseModel):
    """A task in the overdue / due today / coming up strip."""

    id: int
    title: str
    due: date
    due_label: str
    due_tone: str
    repeat: str


class Summary(BaseModel):
    """The deadline strip."""

    overdue: list[SummaryItem]
    today: list[SummaryItem]
    soon: list[SummaryItem]
    firm_overdue: int


class Update(BaseModel):
    """One entry in a task's thread: a comment or an automatic event."""

    id: int
    kind: Literal["comment", "event"]
    body: str
    author: Assignee | None
    created_at: str
    when: str


class SeriesEntry(BaseModel):
    """Another occurrence of a recurring task."""

    id: int
    due: date
    due_short: str
    status: Status


class Task(BaseModel):
    """A task with its assignees, thread and recurring series."""

    id: int
    title: str
    notes: str
    status: Status
    due: date
    due_label: str
    due_tone: str
    repeat: str
    repeat_label: str
    done_at: str | None
    created_at: str
    updated_at: str
    assignees: list[Assignee]
    updates: list[Update]
    series: list[SeriesEntry]


class TaskPatched(Task):
    """A task after an edit; ``next_task_id`` is set when finishing it created the next one."""

    next_task_id: int | None


class Notification(BaseModel):
    """One notification, with the text ready to show."""

    id: int
    task_id: int | None
    kind: str
    actor: str
    body: str
    title: str
    text: str
    detail: str
    read: bool
    announce: bool
    sticky: bool
    created_at: str
    when: str
    due_label: str | None
    due_tone: str


class Unread(BaseModel):
    """The bell's numbers."""

    unread: int
    newest: int
