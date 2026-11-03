"""Learner models: how a student's knowledge changes with practice, time and prerequisites.

Two implementations are planned behind one interface:

* ``TransparentLearnerModel`` — a small, fully specified model (mastery + spaced-repetition
  style stability, prerequisite gating). Every number it produces can be recomputed by hand,
  which is what makes plan verification deterministic.
* ``KTLearnerModel`` — a trained knowledge-tracing model (more realistic, less transparent).
  Interface stub here; see docs/ROADMAP.md.
"""
from __future__ import annotations

import math
from datetime import datetime
from typing import Protocol

from pydantic import Field

from ..schema import LABModel, MasteryState, PlanBlock, SkillGraph


class LearnerModelParams(LABModel):
    learning_rate: float = Field(default=0.5, gt=0)    # mastery gain per hour at mastery 0, prereqs known
    prereq_floor: float = Field(default=0.3, ge=0, le=1)  # effectiveness when prerequisites are unknown
    stability_growth: float = Field(default=0.6, ge=0)  # stability multiplier per practice session
    spacing_bonus: float = Field(default=0.5, ge=0)     # extra growth when retention had dropped
    min_stability_days: float = Field(default=1.0, gt=0)
    max_stability_days: float = Field(default=60.0, gt=0)
    retention_base: float = Field(default=0.9, gt=0, lt=1)  # retention after one stability period
    mastered_threshold: float = Field(default=0.7, gt=0, le=1)


class LearnerModel(Protocol):
    graph: SkillGraph

    def knowledge(self, state: MasteryState, at: datetime) -> float: ...
    def practice(self, state: MasteryState, minutes: int, at: datetime, prereq_knowledge: float) -> MasteryState: ...
    def simulate(self, mastery: dict[str, MasteryState], blocks: list[PlanBlock]) -> dict[str, MasteryState]: ...
    def projected(self, mastery: dict[str, MasteryState], blocks: list[PlanBlock], at: datetime) -> dict[str, float]: ...


class TransparentLearnerModel:
    """Mastery ``m`` (what was learned) × retention ``R`` (how much is still available).

    retention(Δdays) = retention_base ** (Δdays / stability)
    knowledge(t)     = m × retention(t − last_practiced)            (m if never practiced)
    practice(min)    : gain = learning_rate × (min/60) × (1 − m) × (prereq_floor + (1 − prereq_floor) × prereq_knowledge)
                       m ← m + gain ;  stability ← stability × (1 + stability_growth + spacing_bonus × (1 − R_before))
    """

    def __init__(self, graph: SkillGraph, params: LearnerModelParams | None = None) -> None:
        self.graph = graph
        self.params = params or LearnerModelParams()

    def retention(self, state: MasteryState, at: datetime) -> float:
        if state.last_practiced is None:
            return 1.0
        days = max(0.0, (at - state.last_practiced).total_seconds() / 86400.0)
        return self.params.retention_base ** (days / state.stability_days)

    def knowledge(self, state: MasteryState, at: datetime) -> float:
        return state.mastery * self.retention(state, at)

    def prereq_knowledge(self, skill_id: str, mastery: dict[str, MasteryState], at: datetime) -> float:
        prereqs = self.graph.by_id()[skill_id].prerequisites if skill_id in self.graph.by_id() else []
        if not prereqs:
            return 1.0
        vals = [self.knowledge(mastery[p], at) if p in mastery else 0.0 for p in prereqs]
        return min(vals)

    def practice(self, state: MasteryState, minutes: int, at: datetime, prereq_knowledge: float) -> MasteryState:
        p = self.params
        r_before = self.retention(state, at)
        m = state.mastery * r_before  # what is available when practice starts
        effectiveness = p.prereq_floor + (1.0 - p.prereq_floor) * max(0.0, min(1.0, prereq_knowledge))
        gain = p.learning_rate * (minutes / 60.0) * (1.0 - m) * effectiveness
        new_m = min(1.0, m + gain)
        growth = 1.0 + p.stability_growth + p.spacing_bonus * (1.0 - r_before)
        new_s = min(p.max_stability_days, max(p.min_stability_days, state.stability_days * growth))
        return state.model_copy(update={
            "mastery": new_m, "stability_days": new_s, "last_practiced": at,
            "practice_minutes": state.practice_minutes + minutes,
        })

    def simulate(self, mastery: dict[str, MasteryState], blocks: list[PlanBlock]) -> dict[str, MasteryState]:
        """Apply the blocks in time order; the block's minutes are split evenly across its skills."""
        state = {k: v for k, v in mastery.items()}
        for b in sorted(blocks, key=lambda x: x.start):
            if b.activity == "rest" or not b.skill_ids:
                continue
            share = max(1, b.minutes // len(b.skill_ids))
            for sid in b.skill_ids:
                if sid not in state:
                    state[sid] = MasteryState(id=f"mas_{sid}", created_at=b.start, updated_at=b.start,
                                              skill_id=sid, mastery=0.0)
                pk = self.prereq_knowledge(sid, state, b.start)
                state[sid] = self.practice(state[sid], share, b.end, pk)
        return state

    def projected(self, mastery: dict[str, MasteryState], blocks: list[PlanBlock], at: datetime) -> dict[str, float]:
        end_state = self.simulate(mastery, [b for b in blocks if b.end <= at])
        return {sid: self.knowledge(st, at) for sid, st in end_state.items()}

    def expected_score(self, knowledge: float) -> float:
        """Expected fraction correct on items of a skill — a soft curve around the threshold."""
        return 1.0 / (1.0 + math.exp(-8.0 * (knowledge - 0.5)))


class KTLearnerModel:
    """Trained knowledge-tracing learner (planned). Not implemented: there is no trained model
    checkpoint in this repository yet, and no public-data training run has been done. Any use
    raises so that a missing model can never silently stand in for a real one."""

    def __init__(self, graph: SkillGraph, checkpoint: str | None = None) -> None:
        self.graph = graph
        self.checkpoint = checkpoint
        raise NotImplementedError(
            "KTLearnerModel is not available yet: train a knowledge-tracing model on public data "
            "(see docs/ROADMAP.md, Phase 3) and point `checkpoint` at it."
        )
