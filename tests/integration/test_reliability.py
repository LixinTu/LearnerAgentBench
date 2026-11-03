"""Benchmark reliability: the agent never sees grading material; results reproduce; environment
failures are attributed to the environment, not the agent; forbidden, duplicate and
event-ignoring behaviour is visible in the verdict."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from learneragentbench.env import World, build_world
from learneragentbench.harness import run_one
from learneragentbench.runtime import ActionListAdapter, AgentLoop, RunSpec
from learneragentbench.schema import Action, RunConfig
from learneragentbench.tasks import Dataset, resolve_variant
from learneragentbench.tools import REGISTRY, ToolContext, ToolExecutor
from learneragentbench.verify import VerifyContext, run_checks

DS = Dataset()
GRADING_WORDS = ["hidden_constraints", "expected_final_state", "verifier", "check_id", "reference_replies",
                 "negative_cases", "reference_path", "scripted_replies", "expected_delta", "rubrics", "capability_requirements"]
ALLOWED_VIEW_KEYS = {"run_id", "task_id", "variant_id", "user_goal", "now", "instructions", "persona_summary",
                     "history", "memory_notes", "tools", "max_steps", "notices"}


@pytest.mark.parametrize("task_id", DS.task_ids())
def test_agent_inputs_contain_no_grading_material(task_id: str, tmp_path: Path) -> None:
    cfg = RunConfig(model="oracle", adapter="oracle", memory_access="full")
    res = run_one(DS, task_id, "base", cfg, 0, out_root=tmp_path)
    view = res.trajectory.steps[0].observation.content
    assert set(view) <= ALLOWED_VIEW_KEYS, set(view) - ALLOWED_VIEW_KEYS
    everything_seen = json.dumps([s.observation.content for s in res.trajectory.steps], default=str).lower()
    for w in GRADING_WORDS:
        assert w not in everything_seen, f"{w!r} reached the agent in {task_id}"
    # the request itself never restates the hidden constraints (memory may — that is the point)
    goal = DS.load_task(task_id).user_goal.lower()
    for hc in DS.load_task(task_id).hidden_constraints:
        assert hc.lower()[:40] not in goal


def test_oracle_runs_reproduce(tmp_path: Path) -> None:
    cfg = RunConfig(model="oracle", adapter="oracle")
    a = run_one(DS, "D01_midterm_plan_from_rules", "base", cfg, 0, out_root=tmp_path / "a")
    b = run_one(DS, "D01_midterm_plan_from_rules", "base", cfg, 0, out_root=tmp_path / "b")
    assert [(c.check_id, c.passed) for c in a.verdict.checks] == [(c.check_id, c.passed) for c in b.verdict.checks]
    assert a.verdict.score == b.verdict.score
    wa, wb = World.from_snapshot(a.out_dir / "world_final.db"), World.from_snapshot(b.out_dir / "world_final.db")
    pa, pb = wa.active_plan(), wb.active_plan()
    assert pa is not None and pb is not None
    assert [(x.start, x.end, x.skill_ids) for x in pa.blocks] == [(x.start, x.end, x.skill_ids) for x in pb.blocks]
    assert wa.summary() == wb.summary()
    assert [s.action.model_dump() for s in a.trajectory.steps] == [s.action.model_dump() for s in b.trajectory.steps]


def test_internal_tool_error_is_attributed_to_the_environment(tmp_path: Path, monkeypatch) -> None:
    def boom(ctx, p):
        raise RuntimeError("database on fire")
    monkeypatch.setitem(REGISTRY._fns, "get_preferences", boom)
    res = run_one(DS, "D01_midterm_plan_from_rules", "base", RunConfig(model="oracle", adapter="oracle"), 0, out_root=tmp_path)
    assert res.verdict.failure_attribution == "environment"
    assert any(r.error_type == "internal" for r in World.from_snapshot(res.out_dir / "world_final.db").tool_calls())


def test_unexpected_outage_is_attributed_to_the_environment(tmp_path: Path) -> None:
    t = DS.load_task("D01_midterm_plan_from_rules")
    w = build_world(t.initial_state, DS.load_persona("dana"), DS.load_graph("algebra"), task_id=t.task_id)
    w.set_tool_outage("get_preferences", True)  # not in the task's event timeline
    ex = ToolExecutor(REGISTRY, ToolContext(w, run_id="r", allowed_tools=t.available_tools))
    spec = RunSpec(run_id="r", task_id=t.task_id, persona_id="dana", model="m", adapter="a", user_goal=t.user_goal,
                   allowed_tools=t.available_tools, max_steps=5)
    traj = AgentLoop(w, ex, ActionListAdapter([Action.call("get_preferences"), Action.final("x")]), spec, tmp_path).run()
    v = run_checks(VerifyContext(world=w, initial_world=None, trajectory=traj, task=t, variant=resolve_variant(t, "base")))
    assert v.failure_attribution == "environment"


def test_injected_outage_is_not_blamed_on_the_environment(tmp_path: Path) -> None:
    from learneragentbench.schema import EventKind, ScheduledEvent
    t = DS.load_task("D01_midterm_plan_from_rules")
    t = t.model_copy(update={"event_timeline": [ScheduledEvent(id="o", event_kind=EventKind.TOOL_OUTAGE, after_step=0, payload={"tool": "get_preferences"})]})
    w = build_world(t.initial_state, DS.load_persona("dana"), DS.load_graph("algebra"), task_id=t.task_id)
    ex = ToolExecutor(REGISTRY, ToolContext(w, run_id="r", allowed_tools=t.available_tools))
    spec = RunSpec(run_id="r", task_id=t.task_id, persona_id="dana", model="m", adapter="a", user_goal=t.user_goal,
                   allowed_tools=t.available_tools, max_steps=5, events=list(t.event_timeline))
    traj = AgentLoop(w, ex, ActionListAdapter([Action.call("get_preferences"), Action.final("x")]), spec, tmp_path).run()
    v = run_checks(VerifyContext(world=w, initial_world=None, trajectory=traj, task=t, variant=resolve_variant(t, "base")))
    assert v.failure_attribution == "agent"


def test_adapter_crash_is_attributed_to_the_model_api(tmp_path: Path) -> None:
    from learneragentbench.runtime.adapter import AdapterError

    class Broken(ActionListAdapter):
        def step(self, observation):
            raise AdapterError("502 from the model server")

    res = run_one(DS, "F01_share_progress_with_the_right_people", "base", RunConfig(model="x", adapter="scripted"), 0,
                  out_root=tmp_path, adapter_factory=lambda cfg, task, world, ex: Broken([]))
    assert res.trajectory.status == "error" and res.verdict.failure_attribution == "model_api"


def test_tool_calls_change_state_and_claims_do_not(tmp_path: Path) -> None:
    """A successful create_task shows up in the final world; a final message does not."""
    talk = run_one(DS, "B01_weekly_checkin_act_on_what_matters", "base", RunConfig(model="x", adapter="scripted"), 0,
                   out_root=tmp_path / "talk", adapter_factory=lambda c, t, w, e: ActionListAdapter([Action.final("Added a task for Homework 4.")]))
    act = run_one(DS, "B01_weekly_checkin_act_on_what_matters", "base", RunConfig(model="x", adapter="scripted"), 0,
                  out_root=tmp_path / "act", adapter_factory=lambda c, t, w, e: ActionListAdapter([
                      Action.call("create_task", title="Turn in Homework 4", linked_assignment_id="hw4"), Action.final("Added a task for Homework 4.")]))
    assert World.from_snapshot(talk.out_dir / "world_final.db").todos() == []
    assert len(World.from_snapshot(act.out_dir / "world_final.db").todos()) == 1
    by_talk = {c.check_id: c.passed for c in talk.verdict.checks}
    by_act = {c.check_id: c.passed for c in act.verdict.checks}
    assert by_talk["overdue_homework_task"] is False and by_act["overdue_homework_task"] is True


@pytest.mark.parametrize(("task_id", "check_ids"), [
    ("B02_silent_drift", ["plan_reworked", "distributions_rescheduled", "respects_theo_rules"]),
    ("D03_pick_up_where_we_left_off", ["same_plan_extended", "respects_marcus_rules"]),
    ("E05_meet_added_blocks_the_next_day", ["plan_changed_after_event", "still_respects_rules", "still_reaches_target"]),
])
def test_records_that_predate_the_session_do_not_satisfy_outcome_checks(task_id: str, check_ids: list[str], tmp_path: Path) -> None:
    """A plan seeded into the world last week must not pass this session's plan checks, and a
    seeded record is not "changed after the event" just because its timestamp equals the event's.
    An agent that only talks therefore fails every check tagged ``written_this_run``."""
    cfg = RunConfig(model="talker", adapter="scripted", output_dir="unused")
    res = run_one(DS, task_id, "base", cfg, 0, out_root=tmp_path,
                  adapter_factory=lambda c, t, w, ex: ActionListAdapter([Action.final("All done — plan updated and everything is in order.")]))
    by = {c.check_id: c for c in res.verdict.checks}
    for cid in check_ids:
        assert by[cid].passed is False, (cid, by[cid].evidence)
        assert "written by the agent" in by[cid].evidence, (cid, by[cid].evidence)


def test_event_state_after_counts_only_agent_writes_after_delivery(tmp_path: Path) -> None:
    res = run_one(DS, "E05_meet_added_blocks_the_next_day", "base", RunConfig(model="oracle", adapter="oracle"), 0, out_root=tmp_path)
    by = {c.check_id: c for c in res.verdict.checks}
    assert by["plan_changed_after_event"].passed is True
    assert "delivered at step 1" in by["plan_changed_after_event"].evidence
    assert res.trajectory.env_errors == [] and res.verdict.failure_attribution == "none"
