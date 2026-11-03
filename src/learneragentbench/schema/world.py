"""Calendar, inbox, task manager, scheduled events and the tool audit log."""
from __future__ import annotations

from datetime import datetime
from typing import Any, ClassVar, Literal

from pydantic import Field, model_validator

from .common import Actor, EventKind, LABModel, PermissionLevel, Record

CalendarKind = Literal["class", "exam", "study", "personal", "work", "appointment", "deadline", "other"]


class CalendarEvent(Record):
    kind: ClassVar[str] = "calendar_event"

    title: str
    start: datetime
    end: datetime
    event_kind: CalendarKind = "other"
    location: str = ""
    fixed: bool = False
    created_by: Actor = Actor.STUDENT
    status: Literal["confirmed", "tentative", "cancelled"] = "confirmed"
    linked: dict[str, Any] = Field(default_factory=dict)
    note: str = ""

    @model_validator(mode="after")
    def _ordered(self) -> CalendarEvent:
        if self.end <= self.start:
            raise ValueError("event end must be after start")
        return self

    def overlaps(self, other: CalendarEvent) -> bool:
        return self.start < other.end and other.start < self.end


class Message(Record):
    kind: ClassVar[str] = "message"

    channel: Literal["email", "lms_notification", "sms", "app"] = "email"
    sender: str
    recipients: list[str]
    subject: str
    body: str
    sent_at: datetime
    read: bool = False
    labels: list[str] = Field(default_factory=list)
    sent_by: Actor = Actor.SYSTEM
    in_reply_to: str | None = None
    attachments: list[str] = Field(default_factory=list)


class TodoItem(Record):
    kind: ClassVar[str] = "todo"

    title: str
    due_at: datetime | None = None
    status: Literal["open", "done", "cancelled"] = "open"
    priority: Literal["low", "normal", "high"] = "normal"
    linked_assignment_id: str | None = None
    created_by: Actor = Actor.STUDENT
    note: str = ""


class ScheduledEvent(LABModel):
    """An environment event the harness injects at a virtual time, after an agent step, or once the
    scripted student has said a given number of lines. In a conversation the last is the one to use:
    how many loop steps a line takes depends on how many tools the agent calls in between."""

    id: str
    event_kind: EventKind
    at: datetime | None = None
    after_step: int | None = None
    after_student_lines: int | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    description: str = ""
    notify: bool = True

    @model_validator(mode="after")
    def _trigger(self) -> ScheduledEvent:
        if self.at is None and self.after_step is None and self.after_student_lines is None:
            raise ValueError("scheduled event needs `at`, `after_step` or `after_student_lines`")
        return self


class ToolCallRecord(Record):
    """One row per tool invocation, written by the tool layer, never by the agent."""

    kind: ClassVar[str] = "tool_call"

    run_id: str
    step: int
    tool: str
    args: dict[str, Any]
    ok: bool
    result: Any = None
    error: str | None = None
    error_type: Literal["none", "validation", "permission", "not_found", "conflict", "outage", "internal"] = "none"
    permission: PermissionLevel = PermissionLevel.ALLOWED
    approval_request_id: str | None = None
    virtual_time: datetime
    wall_time: datetime
    duration_ms: float = 0.0
    idempotency_key: str | None = None
    idempotent_replay: bool = False
    mutated: bool = False
    records_touched: list[str] = Field(default_factory=list)
