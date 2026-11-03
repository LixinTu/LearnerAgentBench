"""Task specification, counterfactual variants, checks, rubrics and run configuration."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import Field, model_validator

from .common import Capability, CounterfactualCondition, LABModel, TaskFamily
from .student import SessionTranscript
from .world import ScheduledEvent


class CheckSpec(LABModel):
    """One verifiable success criterion. ``hard`` checks are failure conditions."""

    id: str
    description: str
    verifier: str
    params: dict[str, Any] = Field(default_factory=dict)
    weight: float = 1.0
    hard: bool = False
    capability: Capability | None = None


class RubricItem(LABModel):
    id: str
    criterion: str
    points: float
    judge: Literal["deterministic", "llm", "human"] = "human"


class CapabilityRequirement(LABModel):
    capability: Capability
    required: bool = True
    rationale: str = ""


class StatePatch(LABModel):
    """What a counterfactual variant changes relative to the base task."""

    persona_id: str | None = None
    memory_remove: list[str] = Field(default_factory=list)
    memory_add: list[dict[str, Any]] = Field(default_factory=list)
    memory_replace: list[dict[str, Any]] = Field(default_factory=list)
    preference_set: list[dict[str, Any]] = Field(default_factory=list)
    preference_remove: list[str] = Field(default_factory=list)
    tools_remove: list[str] = Field(default_factory=list)
    tools_add: list[str] = Field(default_factory=list)
    records_add: list[dict[str, Any]] = Field(default_factory=list)
    records_update: list[dict[str, Any]] = Field(default_factory=list)
    records_remove: list[str] = Field(default_factory=list)
    mastery_set: dict[str, float] = Field(default_factory=dict, description="Set the hidden mastery of these skills, so a counterfactual result and the LMS estimate agree.")
    events_add: list[ScheduledEvent] = Field(default_factory=list)
    events_remove: list[str] = Field(default_factory=list)
    history_remove_sessions: list[str] = Field(default_factory=list)
    user_goal: str | None = None
    simulated_user: dict[str, Any] | None = None


class VariantSpec(LABModel):
    id: str
    condition: CounterfactualCondition
    description: str
    patch: StatePatch = Field(default_factory=StatePatch)
    expected_delta: str = ""
    checks_add: list[CheckSpec] = Field(default_factory=list)
    checks_remove: list[str] = Field(default_factory=list)
    paired_with: str = "base"
    reference_path: list[RefStep] | None = Field(default=None, description="Replaces the task's reference path for this variant.")


class ApprovalRule(LABModel):
    """How the simulated student answers an approval request. First matching rule wins."""

    tool: str | None = None
    args_contains: dict[str, Any] = Field(default_factory=dict)
    decision: Literal["approve", "deny", "ignore"] = "approve"
    delay_steps: int = 0
    note: str = ""


class ClarificationRule(LABModel):
    """How the simulated student answers a clarifying question (keyword match on the question)."""

    keywords: list[str]
    answer: str


class SimulatedUserSpec(LABModel):
    approval_rules: list[ApprovalRule] = Field(default_factory=list)
    clarifications: list[ClarificationRule] = Field(default_factory=list)
    scripted_replies: list[str] = Field(default_factory=list, description="Consumed in order for ask_user before keyword rules (tutoring scripts).")
    default_clarification: str = "I'm not sure — use your best judgement based on what you know about me."
    default_approval: Literal["approve", "deny", "ignore"] = "deny"


class RefStep(LABModel):
    """One step of a task's declarative oracle path. ``action`` is one of
    tool_call | ask_user | wait | final | plan_for (expanded by the oracle runtime into a
    create_study_plan call built with PlanOracle for the named assessment)."""

    action: Literal["tool_call", "ask_user", "wait", "final", "plan_for"]
    tool: str | None = None
    args: dict[str, Any] = Field(default_factory=dict)
    message: str = ""
    minutes: int = 60
    only_if: Literal["always", "no_memory", "has_memory"] = "always"
    assessment_id: str | None = None
    target_knowledge: float | None = None
    skill_ids: list[str] = Field(default_factory=list)
    title: str = "Study plan"
    goal: str = ""
    update_existing: bool = False


class NegativeCase(LABModel):
    """A deliberately wrong agent behaviour and the checks it must fail (or the verdict it must get)."""

    id: str
    description: str
    actions: list[dict[str, Any]]
    expect_fail_checks: list[str] = Field(default_factory=list)
    expect_task_success: bool = False
    expect_authorization_violation: bool = False
    expect_duplicate: bool = False
    variant: str = "base"


class RecordSeed(LABModel):
    """An explicit record to create at initialisation: ``kind`` + fields."""

    kind: str
    fields: dict[str, Any]


class InitialStateSpec(LABModel):
    """Either a named generator with params, explicit records, or both (generator runs first)."""

    now: datetime
    generator: str | None = None
    generator_params: dict[str, Any] = Field(default_factory=dict)
    records: list[RecordSeed] = Field(default_factory=list)
    skill_graph: str | None = None
    mastery_overrides: dict[str, float] = Field(default_factory=dict)


class TaskSpec(LABModel):
    task_id: str
    family: TaskFamily
    title: str
    version: str = "1.0"
    user_goal: str
    persona_id: str
    initial_state: InitialStateSpec
    history: list[SessionTranscript] = Field(default_factory=list)
    memory: list[dict[str, Any]] = Field(default_factory=list)
    hidden_constraints: list[str] = Field(default_factory=list)
    available_tools: list[str]
    event_timeline: list[ScheduledEvent] = Field(default_factory=list)
    expected_final_state: list[str] = Field(default_factory=list)
    checks: list[CheckSpec]
    rubrics: list[RubricItem] = Field(default_factory=list)
    capability_requirements: list[CapabilityRequirement] = Field(default_factory=list)
    variants: list[VariantSpec] = Field(default_factory=list)
    simulated_user: SimulatedUserSpec = Field(default_factory=SimulatedUserSpec)
    seeds: list[int] = Field(default_factory=lambda: [0])
    max_steps: int = 40
    notes: str = ""
    reference_path: list[RefStep] = Field(default_factory=list)
    negative_cases: list[NegativeCase] = Field(default_factory=list)

    @model_validator(mode="after")
    def _unique_ids(self) -> TaskSpec:
        ids = [c.id for c in self.checks]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate check ids")
        vids = [v.id for v in self.variants]
        if len(vids) != len(set(vids)):
            raise ValueError("duplicate variant ids")
        return self

    def variant(self, variant_id: str) -> VariantSpec | None:
        for v in self.variants:
            if v.id == variant_id:
                return v
        return None


class RunConfig(LABModel):
    """Everything needed to reproduce one benchmark invocation."""

    model: str
    adapter: str
    task_ids: list[str] = Field(default_factory=list)
    families: list[TaskFamily] = Field(default_factory=list)
    persona_ids: list[str] = Field(default_factory=list)
    variant_ids: list[str] = Field(default_factory=lambda: ["base"])
    seeds: list[int] = Field(default_factory=lambda: [0])
    max_steps: int | None = None
    output_dir: str = "runs"
    resume: bool = False
    memory_access: Literal["tools", "full", "transcripts_only", "none"] = "tools"
    tool_profile: Literal["full", "read_only", "none"] = "full"
    temperature: float = 0.0
    adapter_params: dict[str, Any] = Field(default_factory=dict)
    tags: list[str] = Field(default_factory=list)
    condition: str | None = Field(default=None, description="Experiment condition name (set by `lab sweep`).")
