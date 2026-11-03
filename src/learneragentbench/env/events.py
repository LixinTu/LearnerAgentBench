"""Apply scheduled environment events to a World.

Each handler mutates state the way the real system would (a grade appears in the LMS *and*
a notification lands in the inbox) and returns a short description that the harness turns
into an observation. Handlers are deterministic.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from ..schema import (
    RECORD_TYPES,
    Actor,
    ApprovalRequest,
    ApprovalStatus,
    Assessment,
    AssessmentResult,
    Assignment,
    CalendarEvent,
    EventKind,
    MasteryState,
    MemoryEntry,
    MemoryKind,
    Message,
    Preference,
    ScheduledEvent,
    new_id,
)
from .world import World


class EventError(Exception):
    pass


def _notify(world: World, subject: str, body: str, *, channel: str = "lms_notification",
            sender: str = "system", labels: list[str] | None = None) -> Message:
    msg = Message(
        id=new_id("msg", f"{subject}|{body}|{world.now.isoformat()}"),
        created_at=world.now, updated_at=world.now,
        channel=channel, sender=sender, recipients=["student"],  # type: ignore[arg-type]
        subject=subject, body=body, sent_at=world.now, sent_by=Actor.SYSTEM,
        labels=labels or [],
    )
    return world.add(msg)


def apply_event(world: World, ev: ScheduledEvent, *, step: int | None = None) -> str:
    """Apply one event and record when it landed: virtual time, the records it touched and the
    loop step it was delivered at (verifiers use the step to tell agent writes *after* the event
    from writes before it, which timestamps alone cannot do when time does not advance)."""
    handler = _HANDLERS.get(ev.event_kind)
    if handler is None:
        raise EventError(f"no handler for event kind {ev.event_kind}")
    with world.track() as touched:
        text = handler(world, ev.payload, ev)
    world.store.kv_set(f"event_applied:{ev.id}", {"at": world.now.isoformat(), "touched": touched, "step": step})
    return text


def applied_events(world: World) -> list[str]:
    return [k.split(":", 1)[1] for k in world.store.kv_keys("event_applied:")]


# ------------------------------------------------------------------ handlers
def _assessment_result(world: World, p: dict[str, Any], ev: ScheduledEvent) -> str:
    assessment = world.require(Assessment, p["assessment_id"])
    per_skill: dict[str, float] = {k: float(v) for k, v in p.get("per_skill", {}).items()}
    score = float(p.get("score", 100.0 * (sum(per_skill.values()) / len(per_skill) if per_skill else 0.0)))
    result = AssessmentResult(
        id=new_id("res", f"{assessment.id}|{world.now.isoformat()}"),
        created_at=world.now, updated_at=world.now,
        assessment_id=assessment.id, taken_at=p.get("taken_at", world.now), posted_at=world.now,
        per_skill=per_skill, score=score, max_score=float(p.get("max_score", assessment.max_score)),
        feedback=p.get("feedback", ""),
    )
    world.add(result)
    # A posted result is new evidence about the hidden learner state.
    if p.get("update_mastery", True):
        mastery = world.mastery()
        for skill_id, value in per_skill.items():
            if skill_id in mastery:
                m = mastery[skill_id]
                world.update(m.model_copy(update={"mastery": max(0.0, min(1.0, value))}))
    if ev.notify:
        _notify(world, f"Grade posted: {assessment.title}",
                f"Your score for {assessment.title}: {score:g}/{result.max_score:g}. "
                + (f"Feedback: {result.feedback}" if result.feedback else ""),
                labels=["grade"])
    return f"Result posted for {assessment.title}: {score:g}/{result.max_score:g}"


def _exam_rescheduled(world: World, p: dict[str, Any], ev: ScheduledEvent) -> str:
    assessment = world.require(Assessment, p["assessment_id"])
    new_at = _dt(p["new_scheduled_at"])
    old_at = assessment.scheduled_at
    world.update(assessment.model_copy(update={"scheduled_at": new_at}))
    for cal in world.calendar():
        if cal.linked.get("assessment_id") == assessment.id:
            dur = cal.end - cal.start
            world.update(cal.model_copy(update={"start": new_at, "end": new_at + dur}))
    if ev.notify:
        _notify(world, f"Schedule change: {assessment.title}",
                f"{assessment.title} has been moved from {old_at:%a %b %d %H:%M} to {new_at:%a %b %d %H:%M}.",
                sender=p.get("sender", "registrar"), channel="email", labels=["schedule"])
    return f"{assessment.title} moved from {old_at.isoformat()} to {new_at.isoformat()}"


def _calendar_change(world: World, p: dict[str, Any], ev: ScheduledEvent) -> str:
    op = p.get("op", "add")
    if op == "add":
        fields = dict(p["event"])
        fields.setdefault("id", new_id("cal", f"{fields.get('title')}|{fields.get('start')}"))
        fields.setdefault("created_by", Actor.SYSTEM)
        cal = CalendarEvent(created_at=world.now, updated_at=world.now, **fields)
        world.add(cal)
        text = f"New calendar event: {cal.title} {cal.start:%a %b %d %H:%M}-{cal.end:%H:%M}"
    elif op == "update":
        cal = world.require(CalendarEvent, p["id"])
        fields = dict(p.get("fields", {}))
        for k in ("start", "end"):
            if k in fields:
                fields[k] = _dt(fields[k])
        cal = world.update(CalendarEvent.model_validate({**cal.model_dump(mode="python"), **fields}))
        text = f"Calendar event updated: {cal.title} now {cal.start:%a %b %d %H:%M}-{cal.end:%H:%M}"
    elif op == "cancel":
        cal = world.require(CalendarEvent, p["id"])
        world.update(cal.model_copy(update={"status": "cancelled"}))
        text = f"Calendar event cancelled: {cal.title}"
    else:
        raise EventError(f"unknown calendar op {op}")
    if ev.notify:
        _notify(world, "Calendar updated", text, channel="app", labels=["calendar"])
    return text


def _new_message(world: World, p: dict[str, Any], ev: ScheduledEvent) -> str:
    msg = Message(
        id=p.get("id") or new_id("msg", f"{p.get('sender')}|{p.get('subject')}|{world.now.isoformat()}"),
        created_at=world.now, updated_at=world.now,
        channel=p.get("channel", "email"), sender=p["sender"], recipients=p.get("recipients", ["student"]),
        subject=p["subject"], body=p["body"], sent_at=world.now, sent_by=Actor(p.get("sent_by", "system")),
        labels=p.get("labels", []), attachments=p.get("attachments", []),
    )
    world.add(msg)
    return f"New {msg.channel} from {msg.sender}: {msg.subject}"


def _sick_day(world: World, p: dict[str, Any], ev: ScheduledEvent) -> str:
    start = _dt(p["start"])
    end = _dt(p["end"])
    cal = CalendarEvent(
        id=new_id("cal", f"sick|{start.isoformat()}"), created_at=world.now, updated_at=world.now,
        title=p.get("title", "Sick — no study"), start=start, end=end, event_kind="personal",
        fixed=True, created_by=Actor.STUDENT, linked={"sick": True}, note=p.get("note", ""),
    )
    world.add(cal)
    if ev.notify:
        _notify(world, "Message from the student", p.get("message", "I'm sick and can't study until I recover."),
                channel="app", sender="student", labels=["student"])
    return f"Student unavailable (sick) {start:%b %d} to {end:%b %d}"


def _preference_update(world: World, p: dict[str, Any], ev: ScheduledEvent) -> str:
    key, value, scope = p["key"], p["value"], p.get("scope", "global")
    for old in world.preferences(key=key):
        if old.scope == scope:
            world.update(old.model_copy(update={"active": False}))
    pref = Preference(
        id=new_id("pref", f"{key}|{scope}|{world.now.isoformat()}"), created_at=world.now, updated_at=world.now,
        key=key, value=value, scope=scope, stated_at=world.now, source_session=p.get("session_id"),
    )
    world.add(pref)
    text = p.get("text") or f"The student updated preference {key} to {value!r} ({scope})."
    if p.get("remember", True):
        world.add(MemoryEntry(
            id=new_id("mem", f"{key}|{scope}|{world.now.isoformat()}"), created_at=world.now, updated_at=world.now,
            memory_kind=MemoryKind.UPDATE, text=text, payload={"key": key, "value": value, "scope": scope},
            session_id=p.get("session_id"), stated_at=world.now, scope=scope,
        ))
    if ev.notify:
        _notify(world, "Message from the student", text, channel="app", sender="student", labels=["student"])
    return text


def _tool_outage(world: World, p: dict[str, Any], ev: ScheduledEvent) -> str:
    world.set_tool_outage(p["tool"], True)
    return f"Tool unavailable: {p['tool']}"


def _tool_restored(world: World, p: dict[str, Any], ev: ScheduledEvent) -> str:
    world.set_tool_outage(p["tool"], False)
    return f"Tool restored: {p['tool']}"


def _approval_decision(world: World, p: dict[str, Any], ev: ScheduledEvent) -> str:
    req = world.require(ApprovalRequest, p["request_id"])
    status = ApprovalStatus(p.get("decision", "approved"))
    world.update(req.model_copy(update={"status": status, "decided_at": world.now,
                                        "decided_by": p.get("decided_by", "student"),
                                        "decision_note": p.get("note", "")}))
    return f"Approval request {req.id} ({req.tool}) {status.value}"


def _deadline_moved(world: World, p: dict[str, Any], ev: ScheduledEvent) -> str:
    a = world.require(Assignment, p["assignment_id"])
    new_due = _dt(p["new_due_at"])
    old = a.due_at
    world.update(a.model_copy(update={"due_at": new_due}))
    for cal in world.calendar():
        if cal.linked.get("assignment_id") == a.id:
            dur = cal.end - cal.start
            world.update(cal.model_copy(update={"start": new_due - dur, "end": new_due}))
    if ev.notify:
        _notify(world, f"Deadline changed: {a.title}",
                f"The due date for {a.title} moved from {old:%a %b %d %H:%M} to {new_due:%a %b %d %H:%M}.",
                sender=p.get("sender", "instructor"), channel="email", labels=["deadline"])
    return f"{a.title} due date moved from {old.isoformat()} to {new_due.isoformat()}"


def _session_boundary(world: World, p: dict[str, Any], ev: ScheduledEvent) -> str:
    hours = float(p.get("advance_hours", 0))
    if hours:
        world.advance(minutes=int(hours * 60), reason=f"session boundary {p.get('session_id', '')}")
    world.store.kv_set("session.current", p.get("session_id", "s?"))
    return f"New session {p.get('session_id', '')} starts at {world.now.isoformat()}"


def _custom(world: World, p: dict[str, Any], ev: ScheduledEvent) -> str:
    for seed in p.get("records_add", []):
        cls = RECORD_TYPES[seed["kind"]]
        fields = dict(seed["fields"])
        fields.setdefault("id", new_id(seed["kind"][:4], repr(sorted(fields.items()))))
        world.add(cls(created_at=world.now, updated_at=world.now, **fields))
    for upd in p.get("records_update", []):
        cls = RECORD_TYPES[upd["kind"]]
        rec = world.require(cls, upd["id"])
        world.patch(rec, upd["fields"])
    for rem in p.get("records_remove", []):
        world.remove(RECORD_TYPES[rem["kind"]], rem["id"])
    if p.get("mastery_set"):
        mastery = world.mastery()
        for sid, val in p["mastery_set"].items():
            if sid in mastery:
                world.update(mastery[sid].model_copy(update={"mastery": float(val)}))
            else:
                world.add(MasteryState(id=new_id("mas", sid), created_at=world.now, updated_at=world.now,
                                       skill_id=sid, mastery=float(val)))
    return p.get("description", ev.description or "custom event applied")


def _dt(v: Any) -> datetime:
    return v if isinstance(v, datetime) else datetime.fromisoformat(str(v))


_HANDLERS = {
    EventKind.GRADE_POSTED: _assessment_result,
    EventKind.ASSESSMENT_RESULT: _assessment_result,
    EventKind.EXAM_RESCHEDULED: _exam_rescheduled,
    EventKind.CALENDAR_CHANGE: _calendar_change,
    EventKind.NEW_MESSAGE: _new_message,
    EventKind.SICK_DAY: _sick_day,
    EventKind.PREFERENCE_UPDATE: _preference_update,
    EventKind.TOOL_OUTAGE: _tool_outage,
    EventKind.TOOL_RESTORED: _tool_restored,
    EventKind.APPROVAL_DECISION: _approval_decision,
    EventKind.DEADLINE_MOVED: _deadline_moved,
    EventKind.SESSION_BOUNDARY: _session_boundary,
    EventKind.CUSTOM: _custom,
}
