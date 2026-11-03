"""An event in the task's timeline that never fired because the agent ended the episode first is the
agent's failure (it was told to wait), not an unverifiable check; an event id the task does not know
stays unverified. Step-triggered events are applied after the agent finishes, so only time-triggered
ones can be missed this way."""
from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

from learneragentbench.env import World, build_world
from learneragentbench.runtime import ActionListAdapter, AgentLoop, RunSpec
from learneragentbench.schema import Action, CheckSpec, ScheduledEvent
from learneragentbench.tasks import Dataset, resolve_variant
from learneragentbench.tools import REGISTRY, ToolContext, ToolExecutor
from learneragentbench.verify import VerifyContext, run_checks

DS = Dataset()
TASK_ID = "D01_midterm_plan_from_rules"


def _run(actions: list[Action], checks: list[CheckSpec], events: list[ScheduledEvent], tmp_path: Path):
    t = DS.load_task(TASK_ID).model_copy(update={"checks": checks, "event_timeline": events})
    w = build_world(t.initial_state, DS.load_persona("dana"), DS.load_graph("algebra"), task_id=t.task_id)
    init_bytes = w.snapshot_bytes()
    ex = ToolExecutor(REGISTRY, ToolContext(w, run_id="r", allowed_tools=t.available_tools))
    spec = RunSpec(run_id="r", task_id=t.task_id, persona_id="dana", model="m", adapter="a", user_goal=t.user_goal,
                   allowed_tools=t.available_tools, max_steps=20, events=list(events))
    traj = AgentLoop(w, ex, ActionListAdapter(actions), spec, tmp_path).run()
    initial = World.new(w.now)
    initial.restore_bytes(init_bytes)
    return run_checks(VerifyContext(world=w, initial_world=initial, trajectory=traj, task=t, variant=resolve_variant(t, "base")))


def _later_event(now: datetime) -> ScheduledEvent:
    return ScheduledEvent(id="later", event_kind="custom", at=now + timedelta(hours=2), description="second session",
                          payload={"description": "second session begins"})


def test_time_triggered_event_the_agent_never_waited_for_fails_the_check(tmp_path: Path) -> None:
    t = DS.load_task(TASK_ID)
    ev = _later_event(t.initial_state.now)
    checks = [CheckSpec(id="after", description="", verifier="event.state_after", params={"event_id": "later", "kind": "study_plan", "where": {"status": "active"}}),
              CheckSpec(id="tool", description="", verifier="event.responded_with_tool", params={"event_id": "later", "tool": "create_task"})]
    v = _run([Action.call("get_preferences"), Action.final("done, see you Friday")], checks, [ev], tmp_path)
    by = {c.check_id: c for c in v.checks}
    assert by["after"].passed is False and "never fired before the agent finished" in by["after"].evidence
    assert by["tool"].passed is False
    assert v.failure_attribution == "agent"


def test_waiting_lets_the_event_fire_and_the_checks_judge_normally(tmp_path: Path) -> None:
    t = DS.load_task(TASK_ID)
    ev = _later_event(t.initial_state.now)
    checks = [CheckSpec(id="tool", description="", verifier="event.responded_with_tool", params={"event_id": "later", "tool": "create_task"})]
    v = _run([Action.wait(180), Action.call("create_task", title="after the break"), Action.final("done")], checks, [ev], tmp_path)
    assert v.checks[0].passed is True


def test_unknown_event_id_stays_unverified(tmp_path: Path) -> None:
    checks = [CheckSpec(id="ev", description="", verifier="event.state_after", params={"event_id": "never", "kind": "study_plan", "where": {}})]
    v = _run([Action.final("x")], checks, [], tmp_path)
    assert v.checks[0].passed is None
