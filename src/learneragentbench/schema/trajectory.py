"""Actions, observations, trajectories and verdicts."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import Field

from .common import Capability, LABModel


class ToolCall(LABModel):
    tool: str
    args: dict[str, Any] = Field(default_factory=dict)
    idempotency_key: str | None = None


class Action(LABModel):
    """What the agent decided to do at one step."""

    type: Literal["tool_call", "ask_user", "final", "wait"]
    tool_call: ToolCall | None = None
    message: str = ""
    reasoning: str = ""

    @classmethod
    def call(cls, tool: str, **args: Any) -> Action:
        return cls(type="tool_call", tool_call=ToolCall(tool=tool, args=args))

    @classmethod
    def final(cls, message: str) -> Action:
        return cls(type="final", message=message)

    @classmethod
    def ask(cls, message: str) -> Action:
        return cls(type="ask_user", message=message)


class Observation(LABModel):
    """What the agent sees before deciding the next action."""

    type: Literal["task", "tool_result", "tool_error", "user_message", "event", "resume", "approval"]
    content: Any
    step: int
    virtual_time: datetime


class ModelUsage(LABModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0
    calls: int = 0
    cost_usd: float | None = None


class Step(LABModel):
    index: int
    observation: Observation
    action: Action
    tool_record_id: str | None = None
    virtual_time: datetime
    wall_time: datetime
    usage: ModelUsage = Field(default_factory=ModelUsage)
    events_delivered: list[str] = Field(default_factory=list)


class Trajectory(LABModel):
    run_id: str
    task_id: str
    variant_id: str
    persona_id: str
    seed: int
    model: str
    adapter: str
    config: dict[str, Any] = Field(default_factory=dict)
    steps: list[Step] = Field(default_factory=list)
    status: Literal["running", "completed", "max_steps", "error", "interrupted"] = "running"
    final_message: str = ""
    started_at: datetime
    ended_at: datetime | None = None
    usage: ModelUsage = Field(default_factory=ModelUsage)
    errors: list[str] = Field(default_factory=list)
    env_errors: list[str] = Field(default_factory=list)

    def tool_calls(self) -> list[ToolCall]:
        return [s.action.tool_call for s in self.steps if s.action.tool_call is not None]


class CheckResult(LABModel):
    check_id: str
    passed: bool | None
    evidence: str = ""
    weight: float = 1.0
    hard: bool = False
    capability: Capability | None = None
    verifier: str = ""


class Verdict(LABModel):
    run_id: str
    task_id: str
    variant_id: str
    persona_id: str
    seed: int
    model: str
    task_success: bool
    score: float
    max_score: float
    checks: list[CheckResult]
    hard_failures: list[str] = Field(default_factory=list)
    authorization_violations: list[str] = Field(default_factory=list)
    duplicate_actions: list[str] = Field(default_factory=list)
    invalid_actions: list[str] = Field(default_factory=list)
    failure_attribution: Literal["none", "agent", "environment", "harness", "model_api"] = "none"
    capability_scores: dict[str, float] = Field(default_factory=dict)
    tool_call_count: int = 0
    notes: list[str] = Field(default_factory=list)
    judged_at: datetime
