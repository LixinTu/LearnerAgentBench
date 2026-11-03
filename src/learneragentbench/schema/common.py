"""Base model, identifiers, time helpers and enumerations shared by every record."""
from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Any, ClassVar

from pydantic import BaseModel, ConfigDict, Field


class LABModel(BaseModel):
    """Strict base: unknown fields are errors, assignments are validated."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)


def new_id(prefix: str, seed_text: str | None = None) -> str:
    """Return ``<prefix>_<10 hex>``; deterministic when ``seed_text`` is given."""
    if seed_text is not None:
        digest = hashlib.sha1(seed_text.encode("utf-8")).hexdigest()[:10]
    else:
        digest = uuid.uuid4().hex[:10]
    return f"{prefix}_{digest}"


def parse_dt(value: str | datetime) -> datetime:
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(value)


def minutes_between(a: datetime, b: datetime) -> int:
    return int((b - a) / timedelta(minutes=1))


class Record(LABModel):
    """A persisted row. ``kind`` names the store table; ``version`` increments on update."""

    kind: ClassVar[str] = "record"

    id: str
    created_at: datetime
    updated_at: datetime
    version: int = 1
    deleted: bool = False


class Capability(StrEnum):
    LONG_TERM_MEMORY = "long_term_memory"
    PERSONALIZED_PLANNING = "personalized_planning"
    EDUCATIONAL_DECISION_MAKING = "educational_decision_making"
    TOOL_USE_AND_EXECUTION = "tool_use_and_execution"
    PROACTIVE_BEHAVIOR = "proactive_behavior"
    CROSS_SESSION_CONSISTENCY = "cross_session_consistency"
    EVENT_DRIVEN_REPLANNING = "event_driven_replanning"
    SAFETY_AND_AUTHORIZATION = "safety_and_authorization"
    LONG_HORIZON_TASK_COMPLETION = "long_horizon_task_completion"


class TaskFamily(StrEnum):
    A_EXAM_PREP = "A_personalized_exam_preparation"
    B_PROGRESS_MONITORING = "B_learning_progress_monitoring"
    C_ADAPTIVE_TUTORING = "C_adaptive_tutoring_and_intervention"
    D_MULTI_SESSION_PLANNING = "D_multi_session_study_planning"
    E_EVENT_REPLANNING = "E_event_driven_replanning_and_follow_up"
    F_AUTHORIZATION_SAFETY = "F_privacy_authorization_and_educational_safety"


class PermissionLevel(StrEnum):
    ALLOWED = "allowed"
    REQUIRES_APPROVAL = "requires_approval"
    FORBIDDEN = "forbidden"


class ApprovalStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    DENIED = "denied"
    EXPIRED = "expired"


class MemoryKind(StrEnum):
    """Mirrors the memory types used by PersonalAgentEval, plus the ones this benchmark adds."""

    SAID_IN_PASSING = "said_in_passing"
    STANDING_RULE = "standing_rule"
    UPDATE = "update"
    ONE_OFF = "one_off"
    CONFIDENCE = "confidence"
    FOLLOW_UP = "follow_up"
    WHO_IS_WHO = "who_is_who"
    TRANSFER = "transfer"
    FALSE_PREMISE = "false_premise"
    RESTRAINT = "restraint"
    UNRELATED = "unrelated"
    FACT = "fact"


class EventKind(StrEnum):
    GRADE_POSTED = "grade_posted"
    ASSESSMENT_RESULT = "assessment_result"
    EXAM_RESCHEDULED = "exam_rescheduled"
    CALENDAR_CHANGE = "calendar_change"
    NEW_MESSAGE = "new_message"
    SICK_DAY = "sick_day"
    PREFERENCE_UPDATE = "preference_update"
    TOOL_OUTAGE = "tool_outage"
    TOOL_RESTORED = "tool_restored"
    APPROVAL_DECISION = "approval_decision"
    DEADLINE_MOVED = "deadline_moved"
    SESSION_BOUNDARY = "session_boundary"
    CUSTOM = "custom"


class CounterfactualCondition(StrEnum):
    BASE = "base"
    NO_MEMORY = "no_memory"
    CORRECT_MEMORY = "correct_memory"
    OUTDATED_MEMORY = "outdated_memory"
    CONFLICTING_PREFERENCES = "conflicting_preferences"
    DIFFERENT_PERSONA = "different_persona"
    MISSING_TOOL_ACCESS = "missing_tool_access"
    UPDATED_CALENDAR_EVENT = "updated_calendar_event"
    NEW_ASSESSMENT_RESULT = "new_assessment_result"


class Actor(StrEnum):
    STUDENT = "student"
    AGENT = "agent"
    SYSTEM = "system"
    INSTRUCTOR = "instructor"
    GUARDIAN = "guardian"
    TUTOR = "tutor"


class JsonDict(LABModel):
    """Free-form JSON payload holder (kept separate so records stay strict)."""

    data: dict[str, Any] = Field(default_factory=dict)
