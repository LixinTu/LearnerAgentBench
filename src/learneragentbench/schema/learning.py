"""Skills, mastery, learning history, LMS records and study plans."""
from __future__ import annotations

from datetime import datetime
from typing import ClassVar, Literal

from pydantic import Field, model_validator

from .common import Actor, LABModel, Record


class Skill(LABModel):
    id: str
    name: str
    subject: str
    prerequisites: list[str] = Field(default_factory=list)
    description: str = ""
    difficulty: float = 0.5


class SkillGraph(LABModel):
    subject: str
    skills: list[Skill]

    @model_validator(mode="after")
    def _acyclic(self) -> SkillGraph:
        ids = {s.id for s in self.skills}
        for s in self.skills:
            for p in s.prerequisites:
                if p not in ids:
                    raise ValueError(f"skill {s.id} requires unknown skill {p}")
        # Kahn's algorithm
        indeg = {s.id: len(s.prerequisites) for s in self.skills}
        order: list[str] = [k for k, d in indeg.items() if d == 0]
        seen = set(order)
        i = 0
        by_id = {s.id: s for s in self.skills}
        while i < len(order):
            cur = order[i]
            i += 1
            for s in self.skills:
                if cur in s.prerequisites and s.id not in seen:
                    indeg[s.id] -= 1
                    if indeg[s.id] == 0:
                        order.append(s.id)
                        seen.add(s.id)
        if len(order) != len(by_id):
            raise ValueError("skill graph has a cycle")
        return self

    def by_id(self) -> dict[str, Skill]:
        return {s.id: s for s in self.skills}

    def topological_order(self) -> list[str]:
        by_id = self.by_id()
        done: list[str] = []
        seen: set[str] = set()

        def visit(sid: str) -> None:
            if sid in seen:
                return
            seen.add(sid)
            for p in by_id[sid].prerequisites:
                visit(p)
            done.append(sid)

        for s in self.skills:
            visit(s.id)
        return done

    def ancestors(self, skill_id: str) -> list[str]:
        """All transitive prerequisites, nearest first."""
        by_id = self.by_id()
        out: list[str] = []
        stack = list(by_id[skill_id].prerequisites)
        while stack:
            p = stack.pop(0)
            if p not in out:
                out.append(p)
                stack.extend(by_id[p].prerequisites)
        return out


class MasteryState(Record):
    """Per-skill knowledge state of the student (ground truth, hidden from the agent except
    through assessments and the analyze_skill_gaps tool)."""

    kind: ClassVar[str] = "mastery"

    skill_id: str
    mastery: float = Field(ge=0.0, le=1.0)
    stability_days: float = Field(gt=0.0, default=3.0)
    last_practiced: datetime | None = None
    practice_minutes: int = 0


class StudySession(Record):
    kind: ClassVar[str] = "study_session"

    skill_ids: list[str]
    started_at: datetime
    ended_at: datetime
    minutes: int
    source: Literal["actual", "agent_recorded", "planned"] = "actual"
    activity: str = "practice"
    notes: str = ""


class Course(Record):
    kind: ClassVar[str] = "course"

    code: str
    name: str
    instructor_id: str
    term: str
    skill_ids: list[str] = Field(default_factory=list)


class Assessment(Record):
    kind: ClassVar[str] = "assessment"

    course_id: str
    title: str
    assessment_kind: Literal["quiz", "exam", "homework", "diagnostic", "mock"] = "quiz"
    scheduled_at: datetime
    skill_ids: list[str]
    max_score: float = 100.0
    weight: float = 0.0
    location: str = ""


class AssessmentResult(Record):
    kind: ClassVar[str] = "assessment_result"

    assessment_id: str
    taken_at: datetime
    posted_at: datetime
    per_skill: dict[str, float]
    score: float
    max_score: float = 100.0
    feedback: str = ""


class Assignment(Record):
    kind: ClassVar[str] = "assignment"

    course_id: str
    title: str
    due_at: datetime
    skill_ids: list[str] = Field(default_factory=list)
    status: Literal["open", "submitted", "graded", "late", "excused"] = "open"
    weight: float = 0.0
    submission_id: str | None = None
    description: str = ""


class Submission(Record):
    kind: ClassVar[str] = "submission"

    assignment_id: str
    submitted_at: datetime
    content: str
    submitted_by: Actor


class PlanBlock(LABModel):
    start: datetime
    end: datetime
    skill_ids: list[str]
    activity: Literal["practice", "review", "read", "flashcards", "mock_exam", "office_hours", "rest"] = "practice"
    note: str = ""

    @model_validator(mode="after")
    def _ordered(self) -> PlanBlock:
        if self.end <= self.start:
            raise ValueError("block end must be after start")
        return self

    @property
    def minutes(self) -> int:
        return int((self.end - self.start).total_seconds() // 60)


class StudyPlan(Record):
    kind: ClassVar[str] = "study_plan"

    title: str
    goal: str
    target_date: datetime | None = None
    status: Literal["draft", "active", "superseded", "cancelled"] = "active"
    blocks: list[PlanBlock] = Field(default_factory=list)
    rationale: str = ""
    created_by: Actor = Actor.AGENT
    supersedes: str | None = None

    def total_minutes(self) -> int:
        return sum(b.minutes for b in self.blocks)

    def minutes_by_skill(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for b in self.blocks:
            if not b.skill_ids:
                continue
            share = b.minutes / len(b.skill_ids)
            for s in b.skill_ids:
                out[s] = out.get(s, 0) + int(share)
        return out
