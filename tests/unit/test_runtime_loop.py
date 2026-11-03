from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from learneragentbench.env import World, apply_event
from learneragentbench.runtime import (
    ActionListAdapter,
    AgentLoop,
    PolicyAdapter,
    Recorder,
    RunSpec,
    TaskView,
)
from learneragentbench.runtime.adapter import AdapterError
from learneragentbench.schema import (
    Action,
    ApprovalRule,
    Availability,
    CalendarEvent,
    ClarificationRule,
    Contact,
    EventKind,
    MasteryState,
    ModelUsage,
    Observation,
    ScheduledEvent,
    SimulatedUserSpec,
    Skill,
    SkillGraph,
    StudentProfile,
    TimeWindow,
)
from learneragentbench.tools import REGISTRY, ToolContext, ToolExecutor

T0 = datetime(2026, 11, 2, 19, 0)


def _world() -> World:
    w = World.new(T0)
    w.set_skill_graph(SkillGraph(subject="algebra", skills=[Skill(id="lin_eq", name="L", subject="algebra")]))
    w.add(StudentProfile(id="stu", created_at=T0, updated_at=T0, name="Dana", level="cc", program="algebra",
                         contacts=[Contact(id="tutor1", name="Sam", role="tutor", email="s@x"),
                                   Contact(id="prof1", name="Kim", role="instructor", email="k@x")],
                         availability=Availability(windows={d: [TimeWindow(start="18:00", end="22:00")] for d in range(7)})))
    w.add(MasteryState(id="m", created_at=T0, updated_at=T0, skill_id="lin_eq", mastery=0.3))
    return w


def _spec(**kw: Any) -> RunSpec:
    base = dict(run_id="r1", task_id="t1", persona_id="stu", model="scripted", adapter="scripted",
                user_goal="Plan my week.", allowed_tools=REGISTRY.names(), max_steps=20)
    base.update(kw)
    return RunSpec(**base)


def _loop(world: World, adapter, spec: RunSpec, tmp: Path) -> AgentLoop:
    ex = ToolExecutor(REGISTRY, ToolContext(world, run_id=spec.run_id, allowed_tools=spec.allowed_tools))
    return AgentLoop(world, ex, adapter, spec, tmp)


def test_scripted_run_records_steps_and_final_state(tmp_path: Path) -> None:
    w = _world()
    actions = [
        Action.call("get_student_profile"),
        Action.call("create_task", title="Read ch. 3", due_at="2026-11-04T20:00:00"),
        Action.final("Added a task."),
    ]
    traj = _loop(w, ActionListAdapter(actions), _spec(), tmp_path).run()
    assert traj.status == "completed" and traj.final_message == "Added a task."
    assert [s.action.type for s in traj.steps] == ["tool_call", "tool_call", "final"]
    assert traj.steps[0].observation.type == "task" and traj.steps[1].observation.type == "tool_result"
    assert traj.steps[1].observation.content["result"]["name"] == "Dana"
    assert w.todos()[0].title == "Read ch. 3"
    assert w.now == T0 + timedelta(minutes=4)  # two tool steps × 2 virtual minutes
    assert (tmp_path / "trajectory.json").is_file()
    lines = (tmp_path / "steps.jsonl").read_text().splitlines()
    assert len(lines) == 3 and json.loads(lines[0])["action"]["tool_call"]["tool"] == "get_student_profile"
    assert Recorder.load(tmp_path).run_id == "r1"
    assert traj.steps[1].tool_record_id and w.tool_calls("r1")[0].step == 0


def test_tool_errors_become_observations_not_crashes(tmp_path: Path) -> None:
    w = _world()
    actions = [Action.call("get_calendar_events", start="nonsense"), Action.call("no_such_tool"), Action.final("x")]
    traj = _loop(w, ActionListAdapter(actions), _spec(), tmp_path).run()
    assert traj.status == "completed"
    assert traj.steps[1].observation.type == "tool_error" and "invalid arguments" in traj.steps[1].observation.content["error"]
    assert traj.steps[2].observation.content["status"] == "unknown_tool"
    assert traj.errors == []


def test_ask_user_uses_clarification_rules(tmp_path: Path) -> None:
    w = _world()
    spec = _spec(simulated_user=SimulatedUserSpec(
        clarifications=[ClarificationRule(keywords=["which", "course"], answer="Algebra, MATH 101.")]))
    actions = [Action.ask("Which course is this for?"), Action.ask("Do you like cats?"), Action.final("ok")]
    traj = _loop(w, ActionListAdapter(actions), spec, tmp_path).run()
    assert traj.steps[1].observation.type == "user_message"
    assert traj.steps[1].observation.content["answer"] == "Algebra, MATH 101."
    assert traj.steps[2].observation.content["answer"] == spec.simulated_user.default_clarification


def test_wait_advances_virtual_time_and_fires_timed_events(tmp_path: Path) -> None:
    w = _world()
    ev = ScheduledEvent(id="msg1", event_kind=EventKind.NEW_MESSAGE, at=T0 + timedelta(hours=3),
                        payload={"sender": "prof1", "subject": "Exam moved", "body": "Now Friday."},
                        description="instructor email")
    actions = [Action.wait(minutes=30), Action.wait(minutes=180), Action.call("search_email", query="exam"), Action.final("x")]
    traj = _loop(w, ActionListAdapter(actions), _spec(events=[ev]), tmp_path).run()
    assert traj.steps[1].events_delivered == []           # 30 min later: not yet
    assert any("instructor email" in n for n in traj.steps[2].events_delivered)  # after the 3h wait
    assert traj.steps[2].observation.content["notices"]
    assert traj.steps[3].observation.content["result"][0]["subject"] == "Exam moved"


def test_step_triggered_event_and_env_error_attribution(tmp_path: Path) -> None:
    w = _world()
    good = ScheduledEvent(id="e_ok", event_kind=EventKind.TOOL_OUTAGE, after_step=1, payload={"tool": "get_student_profile"})
    bad = ScheduledEvent(id="e_bad", event_kind=EventKind.EXAM_RESCHEDULED, after_step=1,
                         payload={"assessment_id": "missing", "new_scheduled_at": T0.isoformat()})
    actions = [Action.call("get_student_profile"), Action.call("get_student_profile"), Action.final("x")]
    traj = _loop(w, ActionListAdapter(actions), _spec(events=[good, bad]), tmp_path).run()
    assert traj.steps[1].observation.type == "tool_result"               # before the outage
    assert traj.steps[2].observation.type == "tool_error" and traj.steps[2].observation.content["status"] == "outage"
    assert traj.env_errors and "e_bad" in traj.env_errors[0]


def test_approval_flow_with_delay(tmp_path: Path) -> None:
    w = _world()
    spec = _spec(simulated_user=SimulatedUserSpec(approval_rules=[
        ApprovalRule(tool="send_message", args_contains={"to": "prof1"}, decision="approve", delay_steps=1, note="fine")]))
    msg = dict(to="prof1", subject="Question", body="When is office hours?")
    actions = [Action.call("send_message", **msg), Action.wait(minutes=5), Action.call("send_message", **msg), Action.final("sent")]
    traj = _loop(w, ActionListAdapter(actions), spec, tmp_path).run()
    assert traj.steps[1].observation.content["status"] == "pending_approval"
    assert any("approved your request" in n for n in traj.steps[2].events_delivered)
    assert traj.steps[3].observation.content["status"] == "ok"
    assert len([m for m in w.messages() if m.sent_by.value == "agent"]) == 1


def test_default_denial_when_no_rule_matches(tmp_path: Path) -> None:
    w = _world()
    msg = dict(to="prof1", subject="Q", body="B")
    actions = [Action.call("send_message", **msg), Action.call("send_message", **msg), Action.final("x")]
    traj = _loop(w, ActionListAdapter(actions), _spec(), tmp_path).run()
    assert traj.steps[2].observation.content["status"] == "denied"


def test_max_steps_and_adapter_error(tmp_path: Path) -> None:
    w = _world()
    traj = _loop(w, ActionListAdapter([Action.call("get_student_profile")] * 50), _spec(max_steps=5), tmp_path).run()
    assert traj.status == "max_steps" and len(traj.steps) == 5

    class Broken(ActionListAdapter):
        def step(self, observation: Observation) -> Action:
            raise AdapterError("model API 500")

    traj2 = _loop(_world(), Broken([]), _spec(run_id="r2"), tmp_path / "b").run()
    assert traj2.status == "error" and "model API 500" in traj2.errors[0]


def test_interrupt_and_resume_continue_the_same_run(tmp_path: Path) -> None:
    w = _world()
    calls = {"n": 0}

    def policy(view: TaskView, obs: Observation, mem: dict[str, Any]) -> Action:
        mem["n"] = mem.get("n", 0) + 1
        calls["n"] += 1
        if mem["n"] == 1:
            return Action.call("create_task", title="first")
        if mem["n"] == 2:
            return Action.call("create_task", title="second")
        return Action.final(f"done after {mem['n']} steps")

    spec = _spec(interrupt_after=1)
    loop = _loop(w, PolicyAdapter(policy), spec, tmp_path)
    traj = loop.run()
    assert traj.status == "interrupted" and len(traj.steps) == 1
    assert (tmp_path / "loop_state.json").is_file() and (tmp_path / "world_checkpoint.db").is_file()
    assert [t.title for t in w.todos()] == ["first"]

    # a fresh process: new adapter object, world rebuilt from the checkpoint
    resumed = AgentLoop.resume(tmp_path, lambda world, ex: PolicyAdapter(policy),
                               lambda world: ToolExecutor(REGISTRY, ToolContext(world, run_id=spec.run_id, allowed_tools=spec.allowed_tools)))
    traj2 = resumed.run()
    assert traj2.status == "completed" and traj2.final_message == "done after 3 steps"
    assert [s.index for s in traj2.steps] == [0, 1, 2]
    assert [t.title for t in resumed.world.todos()] == ["first", "second"]
    assert resumed.trajectory.started_at == traj.started_at


def test_task_view_gates_memory_and_tools() -> None:
    w = _world()
    spec = _spec(allowed_tools=["get_preferences"], memory_notes=["never after 22:00"], persona_summary="Dana, cc student")
    view = _loop(w, ActionListAdapter([]), spec, Path("/tmp/unused")).task_view()
    assert [t["function"]["name"] for t in view.tools] == ["get_preferences"]
    assert view.memory_notes == ["never after 22:00"] and "Dana" in view.persona_summary


def test_event_applies_once_even_if_due_repeatedly(tmp_path: Path) -> None:
    w = _world()
    ev = ScheduledEvent(id="cal1", event_kind=EventKind.CALENDAR_CHANGE, after_step=0, notify=False,
                        payload={"op": "add", "event": {"id": "x", "title": "Dentist", "start": (T0 + timedelta(days=1)).isoformat(),
                                                        "end": (T0 + timedelta(days=1, hours=1)).isoformat(), "fixed": True}})
    actions = [Action.call("get_student_profile")] * 3 + [Action.final("x")]
    _loop(w, ActionListAdapter(actions), _spec(events=[ev]), tmp_path).run()
    assert len([e for e in w.calendar() if e.title == "Dentist"]) == 1
    apply_event  # noqa: B018 — imported for symmetry with other tests
    assert isinstance(w.calendar()[0], CalendarEvent)


def test_usage_is_carried_into_the_trajectory(tmp_path: Path) -> None:
    class Counting(ActionListAdapter):
        def usage(self) -> ModelUsage:
            return ModelUsage(prompt_tokens=10, completion_tokens=5, calls=1)

    traj = _loop(_world(), Counting([Action.final("x")]), _spec(), tmp_path).run()
    assert traj.usage.prompt_tokens == 10 and traj.steps[0].usage.calls == 1
