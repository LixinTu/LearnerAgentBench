"""Declarative oracle: executes a task's ``reference_path`` (RefStep list) against the world.

Steps are static tool calls, questions, waits and the final message, plus ``plan_for``, which
the oracle expands at run time into a ``create_study_plan`` (or ``update_study_plan``) call
built by ``PlanOracle`` for the current state of the world — so the same path stays correct
under variants that move exams, block days or change the daily cap.

The oracle reads the world directly (it is a reference policy, not a model). It also reads the
check parameters for plan constraints, which is deliberate: the reference path proves the
task's conditions are jointly satisfiable. Independence of the *verifier* from the oracle is
tested separately (tests/integration/test_independent_plan_checker.py).
"""
from __future__ import annotations

from typing import Any

from ..env.world import World
from ..learner import PlanConstraints, PlanGoal, PlanOracle
from ..runtime import PolicyAdapter, TaskView
from ..runtime.adapter import AgentAdapter
from ..schema import Action, Assessment, CounterfactualCondition, Observation, RefStep, TaskSpec
from ..tools import ToolExecutor


def constraints_for(task: TaskSpec, world: World) -> PlanConstraints:
    base = PlanConstraints.from_world(world)
    for c in task.checks:
        if c.verifier.startswith("plan.") and c.params.get("constraints"):
            return base.model_copy(update=c.params["constraints"])
    return base


def _target_from_checks(task: TaskSpec, default: float) -> float:
    for c in task.checks:
        if c.verifier in ("plan.reaches_target", "plan.acceptable") and c.params.get("goal", {}).get("target_knowledge"):
            return float(c.params["goal"]["target_knowledge"])
    return default


def expand_plan_for(step: RefStep, task: TaskSpec, world: World) -> Action:
    a: Assessment | None = world.get(Assessment, step.assessment_id) if step.assessment_id else None
    if a is None:
        upcoming = [x for x in world.assessments() if x.scheduled_at >= world.now]
        a = min(upcoming, key=lambda x: x.scheduled_at) if upcoming else None
    if a is None:
        return Action.final("No upcoming assessment to plan for.")
    skills = step.skill_ids or a.skill_ids
    target = step.target_knowledge if step.target_knowledge is not None else _target_from_checks(task, 0.6)
    goal = PlanGoal(skill_ids=skills, target_date=a.scheduled_at, target_knowledge=target)
    blocks, _ = PlanOracle(world).build(goal, constraints_for(task, world))
    if not blocks:
        return Action.final("No study time is available before the assessment under the current rules.")
    payload = [{"start": b.start.isoformat(), "end": b.end.isoformat(), "skill_ids": b.skill_ids, "activity": b.activity} for b in blocks]
    if step.update_existing and world.active_plan() is not None:
        return Action.call("update_study_plan", replace_blocks=payload, target_date=a.scheduled_at.isoformat(),
                           rationale=step.goal or f"reworked for {a.title}")
    return Action.call("create_study_plan", title=step.title or f"Plan for {a.title}", goal=step.goal or f"Be ready for {a.title}",
                       target_date=a.scheduled_at.isoformat(), rationale="reference path", blocks=payload)


def reference_adapter(task: TaskSpec, world: World, executor: ToolExecutor, *, condition: CounterfactualCondition) -> AgentAdapter:
    steps = list(task.reference_path)

    def policy(view: TaskView, obs: Observation, mem: dict[str, Any]) -> Action:
        while True:
            i = mem.get("i", 0)
            if i >= len(steps):
                return Action.final("Reference path finished.")
            step = steps[i]
            mem["i"] = i + 1
            if step.only_if == "no_memory" and condition != CounterfactualCondition.NO_MEMORY:
                continue
            if step.only_if == "has_memory" and condition == CounterfactualCondition.NO_MEMORY:
                continue
            if step.action == "tool_call":
                return Action(type="tool_call", tool_call={"tool": step.tool or "", "args": dict(step.args)})  # type: ignore[arg-type]
            if step.action == "ask_user":
                return Action.ask(step.message)
            if step.action == "wait":
                return Action.wait(step.minutes, step.message)
            if step.action == "plan_for":
                return expand_plan_for(step, task, world)
            return Action.final(step.message)

    return PolicyAdapter(policy, name="oracle:reference")
