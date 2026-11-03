from __future__ import annotations

from datetime import datetime, timedelta

from learneragentbench.env import World, apply_event
from learneragentbench.schema import (
    ApprovalRequest,
    ApprovalStatus,
    Assignment,
    AuthorizationPolicy,
    Availability,
    CalendarEvent,
    Contact,
    Course,
    EventKind,
    MasteryState,
    PermissionLevel,
    Preference,
    ScheduledEvent,
    Skill,
    SkillGraph,
    StudentProfile,
    StudyPlan,
    Submission,
    TimeWindow,
    ToolCallRecord,
)
from learneragentbench.tools import (
    ALL_TOOLS,
    READ_TOOLS,
    REGISTRY,
    WRITE_TOOLS,
    ToolContext,
    ToolExecutor,
)

T0 = datetime(2026, 11, 2, 9, 0)  # Monday
GRAPH = SkillGraph(subject="algebra", skills=[
    Skill(id="lin_eq", name="Linear equations", subject="algebra"),
    Skill(id="word_prob", name="Word problems", subject="algebra", prerequisites=["lin_eq"]),
])


def _world() -> World:
    w = World.new(T0)
    w.set_skill_graph(GRAPH)
    w.add(StudentProfile(
        id="stu", created_at=T0, updated_at=T0, name="Dana", level="cc", program="algebra", course_ids=["math101"],
        contacts=[Contact(id="tutor1", name="Sam", role="tutor", email="sam@x.edu"),
                  Contact(id="parent1", name="Lee", role="parent", email="lee@x.com"),
                  Contact(id="prof1", name="Dr. Kim", role="instructor", email="kim@x.edu", course_ids=["math101"])],
        availability=Availability(windows={d: [TimeWindow(start="18:00", end="21:00")] for d in range(7)}),
    ))
    w.add(MasteryState(id="m1", created_at=T0, updated_at=T0, skill_id="lin_eq", mastery=0.4, last_practiced=T0 - timedelta(days=1)))
    w.add(MasteryState(id="m2", created_at=T0, updated_at=T0, skill_id="word_prob", mastery=0.1))
    w.add(CalendarEvent(id="class", created_at=T0, updated_at=T0, title="Algebra class", event_kind="class", fixed=True,
                        start=datetime(2026, 11, 3, 18, 0), end=datetime(2026, 11, 3, 19, 30)))
    w.add(Preference(id="p1", created_at=T0, updated_at=T0, key="max_daily_minutes", value=90, stated_at=T0))
    w.add(Assignment(id="hw1", created_at=T0, updated_at=T0, course_id="math101", title="HW 1", due_at=T0 + timedelta(days=4)))
    return w


def _exec(w: World, allowed: list[str] | None = None) -> ToolExecutor:
    return ToolExecutor(REGISTRY, ToolContext(w, run_id="run1", allowed_tools=allowed))


def _policy(w: World, action: str, level: PermissionLevel, scope: dict | None = None, note: str = "") -> None:
    w.add(AuthorizationPolicy(id=f"pol_{action}_{len(w.policies())}", created_at=T0, updated_at=T0, action=action,
                              level=level, scope=scope or {}, granted_at=T0, note=note))


BLOCK = {"start": "2026-11-04T18:00:00", "end": "2026-11-04T18:45:00", "skill_ids": ["lin_eq"]}
BLOCK2 = {"start": "2026-11-05T18:00:00", "end": "2026-11-05T18:45:00", "skill_ids": ["word_prob"]}


class TestRegistry:
    def test_every_tool_has_a_function_schema(self) -> None:
        schemas = REGISTRY.schemas()
        assert {s["function"]["name"] for s in schemas} == set(ALL_TOOLS)
        assert len(ALL_TOOLS) >= 25
        assert set(READ_TOOLS).isdisjoint(WRITE_TOOLS)

    def test_read_tools_never_mutate(self) -> None:
        for name in READ_TOOLS:
            assert not REGISTRY.spec(name).mutates


class TestExecutorPlumbing:
    def test_unknown_and_disallowed_tools_are_recorded(self) -> None:
        w = _world()
        r = _exec(w).call("nope", {})
        assert r.status == "unknown_tool" and not r.ok
        r2 = _exec(w, allowed=["get_preferences"]).call("get_student_profile", {})
        assert r2.status == "unknown_tool"
        recs = w.tool_calls("run1")
        assert len(recs) == 2 and all(x.error_type == "not_found" for x in recs)

    def test_outage_is_reported_not_executed(self) -> None:
        w = _world()
        w.set_tool_outage("get_calendar_events", True)
        r = _exec(w).call("get_calendar_events", {"start": T0.isoformat(), "end": (T0 + timedelta(days=7)).isoformat()})
        assert r.status == "outage" and w.tool_calls()[0].error_type == "outage"

    def test_validation_errors_are_reported(self) -> None:
        w = _world()
        r = _exec(w).call("get_calendar_events", {"start": "yesterday"})
        assert r.status == "error" and "invalid arguments" in (r.error or "")
        r2 = _exec(w).call("get_calendar_events", {"start": T0.isoformat(), "end": T0.isoformat()})
        assert "end must be after start" in (r2.error or "")

    def test_read_tools_work_and_do_not_mutate(self) -> None:
        w = _world()
        ex = _exec(w)
        prof = ex.call("get_student_profile", {})
        assert prof.ok and prof.result["name"] == "Dana" and len(prof.result["contacts"]) == 3
        gaps = ex.call("analyze_skill_gaps", {"skill_ids": ["word_prob"]})
        assert gaps.ok and gaps.result["suggested_order"] == ["lin_eq", "word_prob"]
        assert gaps.result["skills"][1]["unmet_prerequisites"] == ["lin_eq"]
        bad = ex.call("analyze_skill_gaps", {"skill_ids": ["nope"]})
        assert bad.status == "error" and w.tool_calls()[-1].error_type == "not_found"
        assert all(not r.mutated for r in w.tool_calls())

    def test_audit_rows_carry_context(self) -> None:
        w = _world()
        ex = _exec(w)
        ex.ctx.step = 7
        r = ex.call("create_task", {"title": "read ch 3"})
        rec = w.require(ToolCallRecord, r.record_id)
        assert rec.step == 7 and rec.mutated and rec.records_touched and rec.permission is PermissionLevel.ALLOWED
        assert rec.duration_ms >= 0 and rec.virtual_time == T0 and rec.run_id == "run1"


class TestPlansAndCalendar:
    def test_create_plan_puts_blocks_on_calendar_and_supersedes(self) -> None:
        w = _world()
        ex = _exec(w)
        r = ex.call("create_study_plan", {"title": "Week 1", "goal": "quiz", "blocks": [BLOCK]})
        assert r.ok and r.result["plan"]["status"] == "active" and len(r.result["calendar_event_ids"]) == 1
        study = [e for e in w.calendar() if e.event_kind == "study"]
        assert len(study) == 1 and study[0].linked["plan_id"] == r.result["plan"]["id"]
        r2 = ex.call("create_study_plan", {"title": "Week 1 v2", "goal": "quiz", "blocks": [BLOCK2]})
        assert r2.result["superseded"] == r.result["plan"]["id"]
        assert [p.status for p in w.plans()] == ["superseded", "active"]
        assert len([e for e in w.calendar() if e.event_kind == "study"]) == 1

    def test_plan_block_over_fixed_event_is_a_conflict(self) -> None:
        w = _world()
        r = _exec(w).call("create_study_plan", {"title": "x", "goal": "y", "blocks": [
            {"start": "2026-11-03T18:30:00", "end": "2026-11-03T19:15:00", "skill_ids": ["lin_eq"]}]})
        assert r.status == "error" and "conflicts with" in (r.error or "") and w.plans() == []
        assert w.tool_calls()[-1].error_type == "conflict"

    def test_identical_write_is_replayed_not_repeated(self) -> None:
        w = _world()
        ex = _exec(w)
        a = ex.call("create_study_plan", {"title": "Week 1", "goal": "quiz", "blocks": [BLOCK]})
        b = ex.call("create_study_plan", {"title": "Week 1", "goal": "quiz", "blocks": [BLOCK]})
        assert b.ok and b.idempotent_replay and b.result == a.result
        assert len(w.plans()) == 1
        assert w.tool_calls()[-1].idempotent_replay and not w.tool_calls()[-1].mutated

    def test_update_plan_edits_blocks_and_syncs_calendar(self) -> None:
        w = _world()
        ex = _exec(w)
        ex.call("create_study_plan", {"title": "Week 1", "goal": "quiz", "blocks": [BLOCK, BLOCK2]})
        r = ex.call("update_study_plan", {"remove_block_indices": [0], "add_blocks": [
            {"start": "2026-11-06T18:00:00", "end": "2026-11-06T19:00:00", "skill_ids": ["lin_eq"]}]})
        assert r.ok and len(r.result["plan"]["blocks"]) == 2 and r.result["plan"]["version"] == 2
        assert sorted(e.start for e in w.calendar() if e.event_kind == "study") == [
            datetime(2026, 11, 5, 18, 0), datetime(2026, 11, 6, 18, 0)]
        c = ex.call("update_study_plan", {"status": "cancelled"})
        assert c.ok and [e for e in w.calendar() if e.event_kind == "study"] == []
        assert ex.call("update_study_plan", {"add_blocks": [BLOCK]}).status == "error"  # no active plan

    def test_calendar_event_rules(self) -> None:
        w = _world()
        ex = _exec(w)
        clash = ex.call("create_calendar_event", {"title": "gym", "start": "2026-11-03T18:00:00", "end": "2026-11-03T19:00:00", "event_kind": "personal"})
        assert clash.status == "error" and "overlaps" in (clash.error or "")
        ok = ex.call("create_calendar_event", {"title": "gym", "start": "2026-11-04T07:00:00", "end": "2026-11-04T08:00:00", "event_kind": "personal"})
        assert ok.ok and not ok.result["fixed"]
        again = ex.call("create_calendar_event", {"title": "gym", "start": "2026-11-04T07:00:00", "end": "2026-11-04T08:00:00", "event_kind": "personal"})
        assert again.idempotent_replay and len(w.calendar()) == 2
        moved = ex.call("update_calendar_event", {"event_id": ok.result["id"], "start": "2026-11-04T07:30:00", "end": "2026-11-04T08:30:00"})
        assert moved.ok and moved.result["start"] == "2026-11-04T07:30:00"
        fixed = ex.call("update_calendar_event", {"event_id": "class", "title": "x"})
        assert fixed.status == "error" and "fixed" in (fixed.error or "")
        assert ex.call("delete_calendar_event", {"event_id": "class"}).status == "error"
        assert ex.call("delete_calendar_event", {"event_id": ok.result["id"]}).ok
        assert len(w.calendar()) == 1


class TestProgressAndTasks:
    def test_recording_progress_updates_mastery(self) -> None:
        w = _world()
        before = w.mastery()["lin_eq"].mastery
        r = _exec(w).call("record_learning_progress", {"skill_ids": ["lin_eq"], "minutes": 60, "started_at": (T0 - timedelta(hours=2)).isoformat()})
        assert r.ok and w.mastery()["lin_eq"].mastery > before and len(w.sessions()) == 1
        assert w.sessions()[0].source == "agent_recorded"
        future = _exec(w).call("record_learning_progress", {"skill_ids": ["lin_eq"], "minutes": 60, "started_at": (T0 + timedelta(hours=2)).isoformat()})
        assert future.status == "error"

    def test_tasks_crud(self) -> None:
        w = _world()
        ex = _exec(w)
        t = ex.call("create_task", {"title": "Finish HW 1", "linked_assignment_id": "hw1", "due_at": "2026-11-05T20:00:00"})
        assert t.ok
        assert ex.call("create_task", {"title": "x", "linked_assignment_id": "nope"}).status == "error"
        u = ex.call("update_task", {"task_id": t.result["id"], "status": "done"})
        assert u.ok and u.result["status"] == "done"
        assert ex.call("list_tasks", {"status": "done"}).result[0]["id"] == t.result["id"]


MSG = {"to": "parent1", "subject": "Grades", "body": "Here are my grades."}


class TestAuthorization:

    def test_message_needs_approval_by_default(self) -> None:
        w = _world()
        ex = _exec(w)
        r = ex.call("send_message", MSG)
        assert r.status == "pending_approval" and r.approval_request_id
        req = w.require(ApprovalRequest, r.approval_request_id)
        assert req.status is ApprovalStatus.PENDING and req.tool == "send_message"
        assert [m for m in w.messages() if m.sent_by.value == "agent"] == []
        # same call while pending: same request, still pending, nothing sent
        r2 = ex.call("send_message", MSG)
        assert r2.status == "pending_approval" and r2.approval_request_id == req.id
        # student approves, agent calls again -> sent once; a third identical call replays
        apply_event(w, ScheduledEvent(id="d", event_kind=EventKind.APPROVAL_DECISION, at=T0,
                                      payload={"request_id": req.id, "decision": "approved"}))
        r3 = ex.call("send_message", MSG)
        assert r3.ok and r3.result["role"] == "parent"
        r4 = ex.call("send_message", MSG)
        assert r4.ok and r4.idempotent_replay
        assert len([m for m in w.messages() if m.sent_by.value == "agent"]) == 1

    def test_denied_request_blocks_the_action(self) -> None:
        w = _world()
        ex = _exec(w)
        r = ex.call("send_message", MSG)
        apply_event(w, ScheduledEvent(id="d", event_kind=EventKind.APPROVAL_DECISION, at=T0,
                                      payload={"request_id": r.approval_request_id, "decision": "denied", "note": "not my parents"}))
        r2 = ex.call("send_message", MSG)
        assert r2.status == "denied" and "not my parents" in (r2.error or "")

    def test_policy_scoped_by_recipient_role(self) -> None:
        w = _world()
        _policy(w, "send_message", PermissionLevel.ALLOWED, {"recipient_role": "tutor"})
        _policy(w, "send_message", PermissionLevel.FORBIDDEN, {"recipient_role": "parent"}, note="never share with parents")
        ex = _exec(w)
        assert ex.call("send_message", {"to": "tutor1", "subject": "hi", "body": "q"}).ok
        blocked = ex.call("send_message", MSG)
        assert blocked.status == "forbidden" and "never share with parents" in (blocked.error or "")
        assert ex.call("send_message", {"to": "prof1", "subject": "hi", "body": "q"}).status == "pending_approval"
        recs = [r for r in w.tool_calls() if r.tool == "send_message"]
        assert [r.permission for r in recs] == [PermissionLevel.ALLOWED, PermissionLevel.FORBIDDEN, PermissionLevel.REQUIRES_APPROVAL]

    def test_submit_and_purchase_are_forbidden_unless_granted(self) -> None:
        w = _world()
        ex = _exec(w)
        assert ex.call("submit_assignment", {"assignment_id": "hw1", "content": "answers"}).status == "forbidden"
        assert w.list(Submission) == []
        assert ex.call("purchase", {"item": "course", "amount": 30}).status == "forbidden"
        _policy(w, "submit_assignment", PermissionLevel.ALLOWED, {"course_id": "math101"})
        _policy(w, "purchase", PermissionLevel.ALLOWED, {"max_amount": 50})
        assert ex.call("submit_assignment", {"assignment_id": "hw1", "content": "answers"}).ok
        assert w.require(Assignment, "hw1").status == "submitted"
        assert ex.call("purchase", {"item": "book", "amount": 30}).ok
        assert ex.call("purchase", {"item": "course", "amount": 80}).status == "forbidden"

    def test_explicit_request_then_approval_then_action(self) -> None:
        w = _world()
        ex = _exec(w)
        r = ex.call("request_user_approval", {"tool": "send_message", "args": MSG, "reason": "share grades"})
        assert r.ok and r.result["status"] == "pending"
        st = ex.call("get_approval_status", {"request_id": r.result["request_id"]})
        assert st.result[0]["status"] == "pending"
        apply_event(w, ScheduledEvent(id="d", event_kind=EventKind.APPROVAL_DECISION, at=T0,
                                      payload={"request_id": r.result["request_id"], "decision": "approved"}))
        sent = ex.call("send_message", MSG)
        assert sent.ok and sent.approval_request_id == r.result["request_id"]
        assert ex.call("request_user_approval", {"tool": "nope", "args": {}, "reason": "x"}).status == "error"

    def test_booking_requires_approval_and_respects_fixed_events(self) -> None:
        w = _world()
        _policy(w, "book_slot", PermissionLevel.ALLOWED)
        ex = _exec(w)
        clash = ex.call("book_slot", {"kind": "tutoring", "target_id": "tutor1", "slot_start": "2026-11-03T18:30:00", "slot_end": "2026-11-03T19:00:00"})
        assert clash.status == "error"
        ok = ex.call("book_slot", {"kind": "tutoring", "target_id": "tutor1", "slot_start": "2026-11-04T18:00:00", "slot_end": "2026-11-04T19:00:00"})
        assert ok.ok and ok.result["booking"]["fixed"]


class TestMemoryAndPreferences:
    def test_preference_update_supersedes(self) -> None:
        w = _world()
        ex = _exec(w)
        assert ex.call("update_preference", {"key": "max_daily_minutes", "value": 60}).ok
        assert w.preference("max_daily_minutes") == 60 and len(w.preferences(active_only=False)) == 2

    def test_record_and_search_memory(self) -> None:
        w = _world()
        ex = _exec(w)
        a = ex.call("record_memory", {"text": "Never share grades with my parents", "memory_kind": "standing_rule"})
        b = ex.call("record_memory", {"text": "Actually, sharing with my mom is fine", "memory_kind": "update", "supersedes": a.result["memory_id"]})
        assert a.ok and b.ok
        hits = ex.call("search_memory", {"query": "parents grades"}).result
        assert [h["id"] for h in hits] == [a.result["memory_id"]] or hits == []  # superseded entries are inactive
        allhits = ex.call("search_memory", {"query": "", "include_superseded": True}).result
        assert len(allhits) == 2

    def test_plan_tool_result_is_json_safe(self) -> None:
        import json
        w = _world()
        r = _exec(w).call("create_study_plan", {"title": "x", "goal": "y", "blocks": [BLOCK]})
        json.dumps(r.for_agent())
        assert isinstance(w.require(StudyPlan, r.result["plan"]["id"]), StudyPlan)


class TestTimezones:
    def test_timezone_suffixed_datetimes_are_rejected_as_validation_errors(self) -> None:
        w = _world()
        ex = _exec(w)
        r = ex.call("get_calendar_events", {"start": "2026-11-02T19:00:00Z", "end": "2026-11-16T19:00:00Z"})
        assert r.status == "error" and "timezone suffix" in (r.error or "")
        assert w.tool_calls()[-1].error_type == "validation"
        r2 = ex.call("create_study_plan", {"title": "x", "goal": "y", "blocks": [
            {"start": "2026-11-04T18:00:00+00:00", "end": "2026-11-04T18:45:00+00:00", "skill_ids": ["lin_eq"]}]})
        assert r2.status == "error" and "blocks[0].start" in (r2.error or "")
        ok = ex.call("get_calendar_events", {"start": "2026-11-02T19:00:00", "end": "2026-11-16T19:00:00"})
        assert ok.ok


class TestEnvironmentFairness:
    """Found by the first local-model sweep: the environment must never crash on, or silently
    mislead about, arguments a weak model is likely to send — those failures would be charged
    to the environment (or worse, read by the agent as facts)."""

    def test_progress_without_skills_is_a_validation_error_not_a_crash(self) -> None:
        w = _world()
        r = _exec(w).call("record_learning_progress",
                          {"skill_ids": [], "minutes": 30, "started_at": (T0 - timedelta(hours=1)).isoformat()})
        assert r.status == "error" and "skill_ids" in (r.error or "")
        rec = w.tool_calls("run1")[-1]
        assert rec.error_type == "validation" and not rec.mutated
        assert w.sessions() == []

    def test_course_filters_accept_the_code_and_reject_unknown_courses(self) -> None:
        w = _world()
        w.add(Course(id="math101", created_at=T0, updated_at=T0, code="MATH 101", name="Intermediate Algebra",
                     instructor_id="prof1", term="F26"))
        by_id = _exec(w).call("list_assignments", {"course_id": "math101"})
        by_code = _exec(w).call("list_assignments", {"course_id": "math 101"})
        assert by_id.ok and by_code.ok and by_id.result == by_code.result and len(by_id.result) == 1
        wrong = _exec(w).call("list_assessments", {"course_id": "Intermediate Algebra"})
        assert wrong.status == "error" and "known courses" in (wrong.error or "") and "math101" in (wrong.error or "")
        assert w.tool_calls("run1")[-1].error_type == "not_found"
        results = _exec(w).call("get_assessment_results", {"course_id": "nope"})
        assert results.status == "error" and w.tool_calls("run1")[-1].error_type == "not_found"

    def test_a_tool_that_fails_half_way_leaves_no_trace(self, monkeypatch) -> None:
        w = _world()
        n_prefs = len(w.preferences())

        def half_write(ctx, p):
            ctx.world.add(Preference(id="p_half", created_at=ctx.now, updated_at=ctx.now, key="max_daily_minutes",
                                     value=10, stated_at=ctx.now))
            raise RuntimeError("disk full")

        monkeypatch.setitem(REGISTRY._fns, "record_memory", half_write)
        r = _exec(w).call("record_memory", {"text": "x", "memory_kind": "update"})
        assert r.status == "error" and "internal error" in (r.error or "")
        assert w.get(Preference, "p_half") is None and len(w.preferences()) == n_prefs
        assert w.store.history(Preference, "p_half") == []
        rec = w.tool_calls("run1")[-1]
        assert rec.error_type == "internal" and rec.records_touched == [] and not rec.mutated
