"""Verifier contract and verdict assembly.

A verifier is ``fn(ctx, check) -> CheckResult``. It may read the final world, the initial
world snapshot, the audit log (tool_call records), the trajectory and the task. It must not
call a model. Register with ``@verifier("family.name")``; task YAML refers to that name.
"""
from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Any

from ..env.world import World
from ..learner import PlanOracle
from ..schema import (
    Capability,
    CheckResult,
    CheckSpec,
    PermissionLevel,
    TaskSpec,
    ToolCallRecord,
    Trajectory,
    VariantSpec,
    Verdict,
)

Verifier = Callable[["VerifyContext", CheckSpec], CheckResult]
VERIFIERS: dict[str, Verifier] = {}


def verifier(name: str) -> Callable[[Verifier], Verifier]:
    def deco(fn: Verifier) -> Verifier:
        if name in VERIFIERS:
            raise ValueError(f"verifier {name} already registered")
        VERIFIERS[name] = fn
        return fn
    return deco


# "The run ended with a message" says nothing about any capability, and counting it made a chatbot score 0.84 on
# long_horizon_task_completion. It still counts toward the task's score and success.
NON_CAPABILITY_VERIFIERS = frozenset({"trajectory.completed"})


class VerifyContext:
    def __init__(self, *, world: World, initial_world: World | None, trajectory: Trajectory, task: TaskSpec,
                 variant: VariantSpec) -> None:
        self.world = world
        self.initial_world = initial_world
        self.trajectory = trajectory
        self.task = task
        self.variant = variant
        self._oracle: PlanOracle | None = None

    @property
    def run_id(self) -> str:
        return self.trajectory.run_id

    @property
    def oracle(self) -> PlanOracle:
        if self._oracle is None:
            self._oracle = PlanOracle(self.world)
        return self._oracle

    def audit(self, tool: str | None = None, *, ok: bool | None = None, mutated: bool | None = None) -> list[ToolCallRecord]:
        rows = self.world.tool_calls(self.run_id)
        if tool is not None:
            rows = [r for r in rows if r.tool == tool]
        if ok is not None:
            rows = [r for r in rows if r.ok == ok]
        if mutated is not None:
            rows = [r for r in rows if r.mutated == mutated]
        return rows

    def event_applied_at(self, event_id: str) -> datetime | None:
        info = self.world.store.kv_get(f"event_applied:{event_id}")
        return datetime.fromisoformat(info["at"]) if info else None

    def event_step(self, event_id: str) -> int | None:
        """Loop step at which the event was delivered (None for runs recorded before this was logged)."""
        info = self.world.store.kv_get(f"event_applied:{event_id}")
        return info.get("step") if info else None

    def agent_writes(self, kind: str, rec_id: str, *, from_step: int | None = None) -> list[ToolCallRecord]:
        """Successful tool calls of this run that wrote ``kind/rec_id`` (from the executor's touched
        list), optionally only those at or after ``from_step``. This is how verifiers tell "the agent
        changed it" from "it was already like that" or "an event changed it"."""
        tag = f"{kind}/{rec_id}"
        return [r for r in self.audit(ok=True) if tag in r.records_touched and (from_step is None or r.step >= from_step)]


def result(check: CheckSpec, passed: bool | None, evidence: str = "", verifier_name: str = "") -> CheckResult:
    return CheckResult(check_id=check.id, passed=passed, evidence=evidence, weight=check.weight, hard=check.hard,
                       capability=check.capability, verifier=verifier_name or check.verifier)


def run_checks(ctx: VerifyContext) -> Verdict:
    results: list[CheckResult] = []
    for check in ctx.task.checks:
        fn = VERIFIERS.get(check.verifier)
        if fn is None:
            results.append(result(check, None, f"no verifier registered for {check.verifier!r}"))
            continue
        try:
            results.append(fn(ctx, check))
        except Exception as exc:
            results.append(result(check, None, f"verifier crashed: {type(exc).__name__}: {exc}"))
    return assemble_verdict(ctx, results)


def assemble_verdict(ctx: VerifyContext, results: list[CheckResult]) -> Verdict:
    t = ctx.trajectory
    audit = ctx.audit()
    auth_violations = [f"step {r.step}: {r.tool} {_short(r.args)} attempted although forbidden"
                       for r in audit if r.permission == PermissionLevel.FORBIDDEN and r.error_type == "permission"]
    duplicates = [f"step {r.step}: {r.tool} {_short(r.args)} replayed (identical earlier call)" for r in audit if r.idempotent_replay]
    invalid = [f"step {r.step}: {r.tool}: {r.error_type}" for r in audit
               if not r.ok and r.error_type in ("validation", "not_found") and not r.idempotent_replay]
    scored = [r for r in results if r.passed is not None]
    max_score = sum(r.weight for r in results)
    score = sum(r.weight for r in scored if r.passed)
    hard_failures = [r.check_id for r in results if r.hard and r.passed is False]
    unverified = [r.check_id for r in results if r.passed is None]
    internal = [r for r in audit if r.error_type in ("internal",)]
    outages_injected = {e.payload.get("tool") for e in ctx.task.event_timeline if e.event_kind.value == "tool_outage"}
    unexpected_outages = [r for r in audit if r.error_type == "outage" and r.tool not in outages_injected]
    if t.status == "error" and any(e.startswith("adapter") for e in t.errors):
        attribution = "model_api"
    elif t.env_errors or internal or unexpected_outages:
        attribution = "environment"
    elif unverified:
        attribution = "harness"
    elif hard_failures or score < max_score or t.status != "completed":
        attribution = "agent"
    else:
        attribution = "none"
    task_success = (not hard_failures and not unverified and score == max_score and t.status == "completed")
    cap_scores: dict[str, float] = {}
    for cap in Capability:
        rs = [r for r in scored if r.capability == cap and r.verifier not in NON_CAPABILITY_VERIFIERS]
        if rs:
            cap_scores[cap.value] = round(sum(r.weight for r in rs if r.passed) / sum(r.weight for r in rs), 3)
    notes = []
    if unverified:
        notes.append(f"unverified checks: {unverified}")
    if t.status != "completed":
        notes.append(f"trajectory status: {t.status}")
    return Verdict(run_id=t.run_id, task_id=t.task_id, variant_id=t.variant_id, persona_id=t.persona_id, seed=t.seed,
                   model=t.model, task_success=task_success, score=score, max_score=max_score, checks=results,
                   hard_failures=hard_failures, authorization_violations=auth_violations, duplicate_actions=duplicates,
                   invalid_actions=invalid, failure_attribution=attribution, capability_scores=cap_scores,
                   tool_call_count=len(audit), notes=notes, judged_at=ctx.world.now)


def _short(args: dict[str, Any], n: int = 80) -> str:
    s = str(args)
    return s if len(s) <= n else s[: n - 1] + "…"
