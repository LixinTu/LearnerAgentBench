"""Student-facing records: profile, contacts, availability, preferences, memory, authorization."""
from __future__ import annotations

from datetime import datetime
from typing import Any, ClassVar, Literal

from pydantic import Field, field_validator

from .common import ApprovalStatus, LABModel, MemoryKind, PermissionLevel, Record

ContactRole = Literal["parent", "guardian", "instructor", "tutor", "advisor", "peer", "other"]


class Contact(LABModel):
    id: str
    name: str
    role: ContactRole
    email: str
    course_ids: list[str] = Field(default_factory=list)
    note: str = ""


class TimeWindow(LABModel):
    """A daily window, ``"18:00"``–``"21:00"`` style."""

    start: str
    end: str

    @field_validator("start", "end")
    @classmethod
    def _hhmm(cls, v: str) -> str:
        h, m = v.split(":")
        if not (0 <= int(h) <= 23 and 0 <= int(m) <= 59):
            raise ValueError(f"bad time {v!r}")
        return f"{int(h):02d}:{int(m):02d}"


class Availability(LABModel):
    """Recurring free windows per weekday (0 = Monday)."""

    windows: dict[int, list[TimeWindow]] = Field(default_factory=dict)

    @field_validator("windows")
    @classmethod
    def _weekdays(cls, v: dict[int, list[TimeWindow]]) -> dict[int, list[TimeWindow]]:
        for k in v:
            if not 0 <= int(k) <= 6:
                raise ValueError(f"weekday {k} out of range")
        return v


class StudentProfile(Record):
    kind: ClassVar[str] = "student_profile"

    name: str
    pronouns: str = "they/them"
    level: str
    program: str
    timezone: str = "America/New_York"
    course_ids: list[str] = Field(default_factory=list)
    goals: list[str] = Field(default_factory=list)
    contacts: list[Contact] = Field(default_factory=list)
    availability: Availability = Field(default_factory=Availability)
    traits: dict[str, Any] = Field(default_factory=dict)
    notes: str = ""

    def contact(self, contact_id: str) -> Contact | None:
        for c in self.contacts:
            if c.id == contact_id:
                return c
        return None


class Preference(Record):
    """A structured, scoped preference. Known keys are documented in docs/DATASET.md."""

    kind: ClassVar[str] = "preference"

    key: str
    value: Any
    scope: str = "global"
    stated_at: datetime
    source_session: str | None = None
    active: bool = True
    superseded_by: str | None = None
    note: str = ""


class MemoryEntry(Record):
    """What the student said in earlier sessions, as the agent's memory store sees it."""

    kind: ClassVar[str] = "memory"

    memory_kind: MemoryKind
    text: str
    payload: dict[str, Any] = Field(default_factory=dict)
    session_id: str | None = None
    stated_at: datetime
    scope: str = "global"
    active: bool = True
    superseded_by: str | None = None
    confidence: float = 1.0


class AuthorizationPolicy(Record):
    """What the agent may do. ``scope`` narrows the rule (e.g. recipient role, amount cap)."""

    kind: ClassVar[str] = "auth_policy"

    action: str
    level: PermissionLevel
    scope: dict[str, Any] = Field(default_factory=dict)
    granted_by: str = "student"
    granted_at: datetime
    expires_at: datetime | None = None
    note: str = ""


class ApprovalRequest(Record):
    kind: ClassVar[str] = "approval_request"

    tool: str
    args: dict[str, Any]
    reason: str
    requested_at: datetime
    status: ApprovalStatus = ApprovalStatus.PENDING
    decided_at: datetime | None = None
    decided_by: str | None = None
    decision_note: str = ""
    step: int | None = None


class SessionTurn(LABModel):
    role: Literal["student", "agent"]
    text: str
    at: datetime | None = None


class SessionTranscript(LABModel):
    """A prior session shown to memory-enabled agents (and used to derive MemoryEntry rows)."""

    session_id: str
    started_at: datetime
    summary: str = ""
    turns: list[SessionTurn] = Field(default_factory=list)
