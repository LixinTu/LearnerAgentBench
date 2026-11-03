from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from learneragentbench.env import EventError, World, applied_events, apply_event
from learneragentbench.schema import (
    ApprovalRequest,
    Assessment,
    Assignment,
    CalendarEvent,
    EventKind,
    MasteryState,
    Preference,
    ScheduledEvent,
)

T0 = datetime(2026, 11, 2, 9, 0)


def _world_with_exam() -> tuple[World, Assessment, CalendarEvent]:
    w = World.new(T0)
    exam = w.add(Assessment(id="exam1", created_at=T0, updated_at=T0, course_id="c1", title="Midterm",
                            assessment_kind="exam", scheduled_at=T0 + timedelta(days=10),
                            skill_ids=["a", "b"]))
    cal = w.add(CalendarEvent(id="cal_exam", created_at=T0, updated_at=T0, title="Midterm",
                              start=exam.scheduled_at, end=exam.scheduled_at + timedelta(hours=2),
                              event_kind="exam", fixed=True, linked={"assessment_id": "exam1"}))
    w.add(MasteryState(id="ma", created_at=T0, updated_at=T0, skill_id="a", mastery=0.5))
    w.add(MasteryState(id="mb", created_at=T0, updated_at=T0, skill_id="b", mastery=0.5))
    return w, exam, cal


def test_assessment_result_updates_lms_mastery_and_inbox() -> None:
    w, _exam, _ = _world_with_exam()
    ev = ScheduledEvent(id="e1", event_kind=EventKind.ASSESSMENT_RESULT, at=T0,
                        payload={"assessment_id": "exam1", "per_skill": {"a": 0.9, "b": 0.2}, "score": 55})
    text = apply_event(w, ev)
    assert "55" in text
    assert w.results()[0].per_skill == {"a": 0.9, "b": 0.2}
    assert w.mastery()["a"].mastery == 0.9 and w.mastery()["b"].mastery == 0.2
    msgs = w.messages(unread_only=True)
    assert len(msgs) == 1 and "grade" in msgs[0].labels
    assert applied_events(w) == ["e1"]


def test_exam_rescheduled_moves_linked_calendar_event_and_emails() -> None:
    w, _exam, _cal = _world_with_exam()
    new_at = T0 + timedelta(days=5)
    apply_event(w, ScheduledEvent(id="e2", event_kind=EventKind.EXAM_RESCHEDULED, after_step=3,
                                  payload={"assessment_id": "exam1", "new_scheduled_at": new_at.isoformat()}))
    assert w.require(Assessment, "exam1").scheduled_at == new_at
    moved = w.require(CalendarEvent, "cal_exam")
    assert moved.start == new_at and moved.end == new_at + timedelta(hours=2)
    assert w.messages()[0].channel == "email"


def test_calendar_change_add_update_cancel() -> None:
    w = World.new(T0)
    apply_event(w, ScheduledEvent(id="a", event_kind=EventKind.CALENDAR_CHANGE, at=T0, notify=False,
                                  payload={"op": "add", "event": {"id": "shift", "title": "Work shift",
                                           "start": (T0 + timedelta(days=1)).isoformat(),
                                           "end": (T0 + timedelta(days=1, hours=4)).isoformat(),
                                           "event_kind": "work", "fixed": True}}))
    assert w.require(CalendarEvent, "shift").fixed
    apply_event(w, ScheduledEvent(id="b", event_kind=EventKind.CALENDAR_CHANGE, at=T0, notify=False,
                                  payload={"op": "update", "id": "shift", "fields": {"title": "Late shift"}}))
    assert w.require(CalendarEvent, "shift").title == "Late shift"
    apply_event(w, ScheduledEvent(id="c", event_kind=EventKind.CALENDAR_CHANGE, at=T0, notify=False,
                                  payload={"op": "cancel", "id": "shift"}))
    assert w.calendar() == [] and w.messages() == []


def test_sick_day_blocks_calendar() -> None:
    w = World.new(T0)
    apply_event(w, ScheduledEvent(id="s", event_kind=EventKind.SICK_DAY, at=T0,
                                  payload={"start": (T0 + timedelta(days=1)).isoformat(),
                                           "end": (T0 + timedelta(days=3)).isoformat()}))
    busy = w.calendar_conflicts(T0 + timedelta(days=2), T0 + timedelta(days=2, hours=1))
    assert len(busy) == 1 and busy[0].linked.get("sick") is True


def test_preference_update_supersedes_and_remembers() -> None:
    w = World.new(T0)
    w.add(Preference(id="p0", created_at=T0, updated_at=T0, key="no_study_after", value="22:00", stated_at=T0))
    w.advance(days=1)
    apply_event(w, ScheduledEvent(id="p", event_kind=EventKind.PREFERENCE_UPDATE, at=w.now,
                                  payload={"key": "no_study_after", "value": "21:00", "session_id": "s3"}))
    assert w.preference("no_study_after") == "21:00"
    assert len(w.preferences(active_only=False)) == 2 and len(w.preferences()) == 1
    assert w.memory()[0].payload["value"] == "21:00"


def test_tool_outage_and_restore() -> None:
    w = World.new(T0)
    apply_event(w, ScheduledEvent(id="o", event_kind=EventKind.TOOL_OUTAGE, at=T0, payload={"tool": "get_calendar_events"}))
    assert not w.tool_available("get_calendar_events")
    apply_event(w, ScheduledEvent(id="r", event_kind=EventKind.TOOL_RESTORED, at=T0, payload={"tool": "get_calendar_events"}))
    assert w.tool_available("get_calendar_events")


def test_approval_decision_and_deadline_moved() -> None:
    w = World.new(T0)
    req = w.add(ApprovalRequest(id="req1", created_at=T0, updated_at=T0, tool="send_message", args={}, reason="r", requested_at=T0))
    apply_event(w, ScheduledEvent(id="d", event_kind=EventKind.APPROVAL_DECISION, at=T0,
                                  payload={"request_id": req.id, "decision": "denied", "note": "no"}))
    assert w.require(ApprovalRequest, "req1").status.value == "denied"
    a = w.add(Assignment(id="hw1", created_at=T0, updated_at=T0, course_id="c1", title="HW 1", due_at=T0 + timedelta(days=3)))
    apply_event(w, ScheduledEvent(id="m", event_kind=EventKind.DEADLINE_MOVED, at=T0,
                                  payload={"assignment_id": a.id, "new_due_at": (T0 + timedelta(days=1)).isoformat()}))
    assert w.require(Assignment, "hw1").due_at == T0 + timedelta(days=1)


def test_session_boundary_advances_clock() -> None:
    w = World.new(T0)
    apply_event(w, ScheduledEvent(id="sb", event_kind=EventKind.SESSION_BOUNDARY, after_step=1,
                                  payload={"session_id": "s2", "advance_hours": 48}))
    assert w.now == T0 + timedelta(hours=48)


def test_custom_event_records_and_mastery() -> None:
    w = World.new(T0)
    apply_event(w, ScheduledEvent(id="cu", event_kind=EventKind.CUSTOM, at=T0,
                                  payload={"records_add": [{"kind": "todo", "fields": {"id": "t9", "title": "x"}}],
                                           "mastery_set": {"z": 0.7}}))
    assert w.todos()[0].id == "t9" and w.mastery()["z"].mastery == 0.7


def test_unknown_kind_raises() -> None:
    w = World.new(T0)
    ev = ScheduledEvent(id="x", event_kind=EventKind.CUSTOM, at=T0)
    # monkeypatch kind to something without a handler
    object.__setattr__(ev, "event_kind", "nope")
    with pytest.raises(EventError):
        apply_event(w, ev)
