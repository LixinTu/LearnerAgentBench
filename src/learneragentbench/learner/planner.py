"""Plan oracle: build a study plan that is provably good under the learner model, and check
whether any candidate plan is acceptable. The checker is what verifiers use, so a task never
depends on one 'golden' plan — any plan that satisfies the constraints and reaches the
target knowledge passes.
"""
from __future__ import annotations

from datetime import datetime, time, timedelta
from typing import Any

from pydantic import Field

from ..env.world import World
from ..schema import LABModel, MasteryState, PlanBlock, SkillGraph, StudyPlan, TimeWindow
from .model import TransparentLearnerModel


class PlanConstraints(LABModel):
    """Derived from preferences + availability; see docs/DATASET.md for the preference keys."""

    max_daily_minutes: int = 120
    min_block_minutes: int = 30
    preferred_block_minutes: int = 45
    no_study_before: str = "07:00"
    no_study_after: str = "22:00"
    rest_weekdays: list[int] = Field(default_factory=list)
    buffer_hours_before_exam: int = 12
    windows_by_weekday: dict[int, list[TimeWindow]] = Field(default_factory=dict)
    max_skills_per_block: int = 2

    @classmethod
    def from_world(cls, world: World, scope: str = "global") -> PlanConstraints:
        prof = world.profile()
        get = world.preference
        return cls(
            max_daily_minutes=int(get("max_daily_minutes", scope, 120)),
            min_block_minutes=int(get("min_block_minutes", scope, 30)),
            preferred_block_minutes=int(get("preferred_block_minutes", scope, 45)),
            no_study_before=str(get("no_study_before", scope, "07:00")),
            no_study_after=str(get("no_study_after", scope, "22:00")),
            rest_weekdays=[int(x) for x in get("rest_weekdays", scope, [])],
            buffer_hours_before_exam=int(get("buffer_hours_before_exam", scope, 12)),
            windows_by_weekday={int(k): v for k, v in prof.availability.windows.items()},
        )

    def windows_for(self, day: datetime) -> list[TimeWindow]:
        wd = day.weekday()
        if wd in self.rest_weekdays:
            return []
        wins = self.windows_by_weekday.get(wd) or [TimeWindow(start="07:00", end="22:00")]
        lo, hi = time.fromisoformat(self.no_study_before), time.fromisoformat(self.no_study_after)
        out: list[TimeWindow] = []
        for w in wins:
            s = max(time.fromisoformat(w.start), lo)
            e = min(time.fromisoformat(w.end), hi)
            if s < e:
                out.append(TimeWindow(start=s.strftime("%H:%M"), end=e.strftime("%H:%M")))
        return out


class PlanGoal(LABModel):
    skill_ids: list[str]
    target_date: datetime
    target_knowledge: float = 0.75
    include_prerequisites: bool = True


class PlanAssessment(LABModel):
    """Result of checking a candidate plan against constraints and the learner model."""

    feasible: bool
    projected: dict[str, float]
    shortfall: dict[str, float]
    violations: list[str]
    total_minutes: int
    minutes_by_skill: dict[str, int]


class PlanOracle:
    def __init__(self, world: World, model: TransparentLearnerModel | None = None) -> None:
        self.world = world
        self.graph: SkillGraph = world.skill_graph
        self.model = model or TransparentLearnerModel(self.graph)

    # ----------------------------------------------------------------- checking
    def target_skills(self, goal: PlanGoal, mastery: dict[str, MasteryState] | None = None) -> list[str]:
        mastery = mastery if mastery is not None else self.world.mastery()
        wanted: list[str] = []
        for sid in goal.skill_ids:
            if goal.include_prerequisites:
                for anc in reversed(self.graph.ancestors(sid)):
                    k = self.model.knowledge(mastery[anc], self.world.now) if anc in mastery else 0.0
                    if k < self.model.params.mastered_threshold and anc not in wanted:
                        wanted.append(anc)
            if sid not in wanted:
                wanted.append(sid)
        order = self.graph.topological_order()
        return sorted(wanted, key=lambda s: order.index(s) if s in order else len(order))

    def assess(self, blocks: list[PlanBlock], goal: PlanGoal, constraints: PlanConstraints,
               *, tolerance: float = 0.02, mastery: dict[str, MasteryState] | None = None) -> PlanAssessment:
        mastery = mastery if mastery is not None else self.world.mastery()
        violations: list[str] = []
        now = self.world.now
        # structural checks
        by_day: dict[str, int] = {}
        for i, b in enumerate(blocks):
            if b.start < now:
                violations.append(f"block {i} starts in the past ({b.start.isoformat()})")
            if b.end > goal.target_date - timedelta(hours=constraints.buffer_hours_before_exam) and b.activity != "rest":
                violations.append(f"block {i} ends inside the {constraints.buffer_hours_before_exam}h buffer before the target")
            if b.minutes < constraints.min_block_minutes and b.activity != "rest":
                violations.append(f"block {i} is shorter than {constraints.min_block_minutes} min")
            if len(b.skill_ids) > constraints.max_skills_per_block:
                violations.append(f"block {i} mixes {len(b.skill_ids)} skills (max {constraints.max_skills_per_block})")
            wins = constraints.windows_for(b.start)
            inside = any(time.fromisoformat(w.start) <= b.start.time() and b.end.time() <= time.fromisoformat(w.end)
                         and b.start.date() == b.end.date() for w in wins)
            if not inside:
                violations.append(f"block {i} ({b.start:%a %H:%M}-{b.end:%H:%M}) is outside the allowed study windows")
            conflicts = self.world.calendar_conflicts(b.start, b.end)
            conflicts = [c for c in conflicts if c.event_kind != "study" or c.fixed]
            if conflicts:
                violations.append(f"block {i} overlaps calendar: {', '.join(c.title for c in conflicts)}")
            key = b.start.date().isoformat()
            by_day[key] = by_day.get(key, 0) + (0 if b.activity == "rest" else b.minutes)
            for j, other in enumerate(blocks):
                if j > i and b.start < other.end and other.start < b.end:
                    violations.append(f"blocks {i} and {j} overlap each other")
        for day, mins in by_day.items():
            if mins > constraints.max_daily_minutes:
                violations.append(f"{day}: {mins} min exceeds the daily cap of {constraints.max_daily_minutes}")
        # knowledge projection
        projected = self.model.projected(mastery, blocks, goal.target_date)
        shortfall: dict[str, float] = {}
        for sid in self.target_skills(goal, mastery):
            k = projected.get(sid, self.model.knowledge(mastery[sid], goal.target_date) if sid in mastery else 0.0)
            if k + tolerance < goal.target_knowledge:
                shortfall[sid] = round(goal.target_knowledge - k, 3)
        plan = StudyPlan(id="tmp", created_at=now, updated_at=now, title="", goal="", blocks=blocks)
        return PlanAssessment(
            feasible=not violations and not shortfall, projected={k: round(v, 3) for k, v in projected.items()},
            shortfall=shortfall, violations=violations, total_minutes=plan.total_minutes(),
            minutes_by_skill=plan.minutes_by_skill(),
        )

    # ------------------------------------------------------------------ building
    def build(self, goal: PlanGoal, constraints: PlanConstraints, *, max_days: int = 60) -> tuple[list[PlanBlock], PlanAssessment]:
        """Greedy forward scheduler: fill allowed free slots day by day, assigning each block to
        the target skill with the largest remaining deficit whose prerequisites are ready."""
        mastery = self.world.mastery()
        targets = self.target_skills(goal, mastery)
        blocks: list[PlanBlock] = []
        latest_end = goal.target_date - timedelta(hours=constraints.buffer_hours_before_exam)
        day = self.world.now.replace(hour=0, minute=0, second=0, microsecond=0)
        days_used = 0
        while day <= latest_end and days_used < max_days:
            if self.assess(blocks, goal, constraints, mastery=mastery).feasible:
                break
            wins = constraints.windows_for(day)
            used_today = 0
            for s, e in self.world.free_slots(day, wins, min_minutes=constraints.min_block_minutes):
                cur = max(s, self.world.now)
                while cur + timedelta(minutes=constraints.min_block_minutes) <= e and used_today < constraints.max_daily_minutes:
                    room = min(constraints.preferred_block_minutes, constraints.max_daily_minutes - used_today,
                               int((e - cur).total_seconds() // 60))
                    if room < constraints.min_block_minutes:
                        break
                    end = cur + timedelta(minutes=room)
                    if end > latest_end:
                        break
                    sid = self._pick_skill(targets, list(blocks), goal, mastery, end)
                    if sid is None:
                        break
                    blocks.append(PlanBlock(start=cur, end=end, skill_ids=[sid], activity="practice"))
                    used_today += room
                    cur = end
                    if self.assess(blocks, goal, constraints, mastery=mastery).feasible:
                        break
                if self.assess(blocks, goal, constraints, mastery=mastery).feasible:
                    break
            day += timedelta(days=1)
            days_used += 1
        return blocks, self.assess(blocks, goal, constraints, mastery=mastery)

    def _pick_skill(self, targets: list[str], blocks: list[PlanBlock], goal: PlanGoal,
                    mastery: dict[str, MasteryState], at: datetime) -> str | None:
        projected = self.model.projected(mastery, blocks, goal.target_date)
        state_now = self.model.simulate(mastery, blocks)
        best: tuple[float, str] | None = None
        for sid in targets:
            k = projected.get(sid, 0.0)
            deficit = goal.target_knowledge - k
            if deficit <= 0:
                continue
            pk = self.model.prereq_knowledge(sid, state_now, at)
            # prefer skills whose prerequisites are ready; otherwise their prerequisites come first in `targets`
            if pk < self.model.params.mastered_threshold * 0.8 and any(
                p in targets and goal.target_knowledge - projected.get(p, 0.0) > 0
                for p in self.graph.by_id()[sid].prerequisites
            ):
                continue
            if best is None or deficit > best[0]:
                best = (deficit, sid)
        return None if best is None else best[1]

    def to_plan(self, blocks: list[PlanBlock], goal: PlanGoal, title: str = "Study plan") -> StudyPlan:
        now = self.world.now
        return StudyPlan(id="plan_oracle", created_at=now, updated_at=now, title=title,
                         goal=f"reach {goal.target_knowledge:.2f} on {', '.join(goal.skill_ids)} by {goal.target_date:%Y-%m-%d}",
                         target_date=goal.target_date, blocks=blocks, rationale="oracle greedy plan")

    def describe(self, assessment: PlanAssessment) -> dict[str, Any]:
        return assessment.model_dump(mode="json")
