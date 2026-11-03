"""The adapter contract every agent implementation satisfies."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Protocol, runtime_checkable

from pydantic import Field

from ..schema import Action, LABModel, ModelUsage, Observation, SessionTranscript


class TaskView(LABModel):
    """What the agent is told when a run starts. Memory and tools are gated by the run config,
    which is how the chatbot / memory-assistant / tool-agent baselines are produced from one
    model."""

    run_id: str
    task_id: str
    variant_id: str
    user_goal: str
    now: datetime
    instructions: str
    persona_summary: str = ""
    history: list[SessionTranscript] = Field(default_factory=list)
    memory_notes: list[str] = Field(default_factory=list)
    tools: list[dict[str, Any]] = Field(default_factory=list)
    max_steps: int = 40


class AdapterError(Exception):
    """The adapter (not the environment) failed: model API error, malformed output, etc."""


@runtime_checkable
class AgentAdapter(Protocol):
    name: str

    def start(self, view: TaskView) -> None: ...
    def step(self, observation: Observation) -> Action: ...
    def state(self) -> dict[str, Any]: ...
    def restore(self, state: dict[str, Any]) -> None: ...
    def usage(self) -> ModelUsage: ...


DEFAULT_INSTRUCTIONS = """You are the personal study agent of one student. You act on their behalf inside their own
digital workspace: calendar, study plans, task manager, learning records, inbox and memory of
earlier sessions. Use the tools to look things up and to make changes; do not guess state you
can read. Respect everything the student has told you before (standing rules, preferences,
who may see what). Some actions need the student's approval and some are not allowed at all —
when a tool says so, do not work around it. If a decision genuinely depends on something only
the student knows, ask them (ask_user); otherwise decide and act. When the request is done,
call finish with a short, concrete summary of what you changed and anything still pending."""
