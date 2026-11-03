from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from learneragentbench.env import World
from learneragentbench.learner import (
    KTLearnerModel,
    LearnerModelParams,
    PlanConstraints,
    PlanGoal,
    PlanOracle,
    TransparentLearnerModel,
)
from learneragentbench.schema import (
    Availability,
    CalendarEvent,
    MasteryState,
    PlanBlock,
    Preference,
    Skill,
    SkillGraph,
    StudentProfile,
    TimeWindow,
)

T0 = datetime(2026, 11, 2, 9, 0)  # a Monday
GRAPH = SkillGraph(subject="algebra", skills=[
    Skill(id="lin_eq", name="Linear equations", subject="algebra"),
    Skill(id="word_prob", name="Word problems", subject="algebra", prerequisites=["lin_eq"]),
    Skill(id="systems", name="Systems of equations", subject="algebra", prerequisites=["lin_eq"]),
])


def _m(skill: str, mastery: float, last: datetime | None = None, stability: float = 3.0) -> MasteryState:
    return MasteryState(id=f"m_{skill}", created_at=T0, updated_at=T0, skill_id=skill, mastery=mastery,
                        last_practiced=last, stability_days=stability)


class TestTransparentModel:
    def test_knowledge_decays_with_time_and_stability(self) -> None:
        model = TransparentLearnerModel(GRAPH)
        s = _m("lin_eq", 0.8, last=T0, stability=3.0)
        assert model.knowledge(s, T0) == pytest.approx(0.8)
        assert model.knowledge(s, T0 + timedelta(days=3)) == pytest.approx(0.8 * 0.9)
        stable = _m("lin_eq", 0.8, last=T0, stability=30.0)
        assert model.knowledge(stable, T0 + timedelta(days=3)) > model.knowledge(s, T0 + timedelta(days=3))

    def test_never_practiced_does_not_decay(self) -> None:
        model = TransparentLearnerModel(GRAPH)
        assert model.knowledge(_m("lin_eq", 0.5), T0 + timedelta(days=100)) == 0.5

    def test_practice_raises_mastery_and_stability_and_is_gated_by_prereqs(self) -> None:
        model = TransparentLearnerModel(GRAPH)
        s = _m("word_prob", 0.2, last=T0)
        with_prereq = model.practice(s, 60, T0 + timedelta(hours=1), prereq_knowledge=1.0)
        without = model.practice(s, 60, T0 + timedelta(hours=1), prereq_knowledge=0.0)
        assert with_prereq.mastery > without.mastery > 0.2
        assert with_prereq.stability_days > 3.0
        assert with_prereq.practice_minutes == 60 and with_prereq.last_practiced == T0 + timedelta(hours=1)
        assert model.practice(_m("x", 1.0), 600, T0, 1.0).mastery == 1.0

    def test_simulate_applies_blocks_in_time_order_and_projects(self) -> None:
        model = TransparentLearnerModel(GRAPH, LearnerModelParams(learning_rate=0.5))
        mastery = {"lin_eq": _m("lin_eq", 0.3), "word_prob": _m("word_prob", 0.1)}
        later = PlanBlock(start=T0 + timedelta(days=2), end=T0 + timedelta(days=2, hours=1), skill_ids=["word_prob"])
        first = PlanBlock(start=T0 + timedelta(days=1), end=T0 + timedelta(days=1, hours=1), skill_ids=["lin_eq"])
        proj = model.projected(mastery, [later, first], T0 + timedelta(days=3))
        assert proj["lin_eq"] > 0.3 and proj["word_prob"] > 0.1
        # blocks after the projection date are ignored
        assert model.projected(mastery, [later], T0 + timedelta(days=1))["word_prob"] == pytest.approx(0.1)

    def test_kt_model_is_explicitly_unavailable(self) -> None:
        with pytest.raises(NotImplementedError):
            KTLearnerModel(GRAPH)


def _world() -> World:
    w = World.new(T0)
    w.set_skill_graph(GRAPH)
    w.add(StudentProfile(id="stu", created_at=T0, updated_at=T0, name="Dana", level="cc", program="algebra",
                         availability=Availability(windows={d: [TimeWindow(start="18:00", end="21:00")] for d in range(7)})))
    for sid, m in (("lin_eq", 0.35), ("word_prob", 0.15), ("systems", 0.2)):
        w.add(_m(sid, m, last=T0 - timedelta(days=1), stability=5.0))
    w.add(Preference(id="p1", created_at=T0, updated_at=T0, key="max_daily_minutes", value=90, stated_at=T0))
    w.add(Preference(id="p2", created_at=T0, updated_at=T0, key="no_study_after", value="20:30", stated_at=T0))
    w.add(Preference(id="p3", created_at=T0, updated_at=T0, key="rest_weekdays", value=[6], stated_at=T0))
    w.add(CalendarEvent(id="shift", created_at=T0, updated_at=T0, title="Work shift", event_kind="work", fixed=True,
                        start=datetime(2026, 11, 3, 18, 0), end=datetime(2026, 11, 3, 21, 0)))
    return w


class TestPlanOracle:
    def test_constraints_from_world_merge_preferences_and_availability(self) -> None:
        c = PlanConstraints.from_world(_world())
        assert c.max_daily_minutes == 90 and c.no_study_after == "20:30" and c.rest_weekdays == [6]
        assert c.windows_for(datetime(2026, 11, 2)) == [TimeWindow(start="18:00", end="20:30")]
        assert c.windows_for(datetime(2026, 11, 8)) == []  # Sunday is a rest day

    def test_target_skills_include_weak_prerequisites_in_order(self) -> None:
        oracle = PlanOracle(_world())
        goal = PlanGoal(skill_ids=["word_prob"], target_date=T0 + timedelta(days=14))
        assert oracle.target_skills(goal) == ["lin_eq", "word_prob"]

    def test_assess_flags_every_constraint_violation(self) -> None:
        w = _world()
        oracle = PlanOracle(w)
        goal = PlanGoal(skill_ids=["word_prob"], target_date=T0 + timedelta(days=14))
        c = PlanConstraints.from_world(w)
        blocks = [
            PlanBlock(start=datetime(2026, 11, 3, 18, 0), end=datetime(2026, 11, 3, 19, 0), skill_ids=["lin_eq"]),   # shift conflict
            PlanBlock(start=datetime(2026, 11, 4, 20, 0), end=datetime(2026, 11, 4, 21, 0), skill_ids=["lin_eq"]),   # after 20:30
            PlanBlock(start=datetime(2026, 11, 5, 18, 0), end=datetime(2026, 11, 5, 18, 20), skill_ids=["lin_eq"]),  # too short
            PlanBlock(start=datetime(2026, 11, 8, 18, 0), end=datetime(2026, 11, 8, 19, 0), skill_ids=["lin_eq"]),   # rest day
            PlanBlock(start=datetime(2026, 11, 6, 18, 0), end=datetime(2026, 11, 6, 19, 0), skill_ids=["lin_eq"]),
            PlanBlock(start=datetime(2026, 11, 6, 18, 30), end=datetime(2026, 11, 6, 19, 30), skill_ids=["word_prob"]),  # overlaps + cap
        ]
        a = oracle.assess(blocks, goal, c)
        joined = "\n".join(a.violations)
        assert not a.feasible
        for needle in ("overlaps calendar", "outside the allowed", "shorter than", "overlap each other", "exceeds the daily cap"):
            assert needle in joined, needle
        assert set(a.shortfall) >= {"word_prob"}

    def test_oracle_builds_a_feasible_plan_that_its_own_checker_accepts(self) -> None:
        w = _world()
        oracle = PlanOracle(w)
        goal = PlanGoal(skill_ids=["word_prob"], target_date=T0 + timedelta(days=14), target_knowledge=0.75)
        c = PlanConstraints.from_world(w)
        blocks, assessment = oracle.build(goal, c)
        assert assessment.feasible, assessment.violations or assessment.shortfall
        assert blocks and all(b.start.weekday() != 6 for b in blocks)
        assert all(not w.calendar_conflicts(b.start, b.end) for b in blocks)
        assert all(b.end.time().strftime("%H:%M") <= "20:30" for b in blocks)
        by_day: dict[str, int] = {}
        for b in blocks:
            by_day[b.start.date().isoformat()] = by_day.get(b.start.date().isoformat(), 0) + b.minutes
        assert max(by_day.values()) <= 90
        # prerequisites are scheduled before the dependent skill
        first_lin = min(b.start for b in blocks if "lin_eq" in b.skill_ids)
        first_wp = min(b.start for b in blocks if "word_prob" in b.skill_ids)
        assert first_lin < first_wp
        plan = oracle.to_plan(blocks, goal)
        assert plan.total_minutes() == sum(b.minutes for b in blocks)

    def test_infeasible_goal_is_reported_not_hidden(self) -> None:
        w = _world()
        oracle = PlanOracle(w)
        goal = PlanGoal(skill_ids=["word_prob"], target_date=T0 + timedelta(days=1), target_knowledge=0.95)
        _blocks, assessment = oracle.build(goal, PlanConstraints.from_world(w))
        assert not assessment.feasible and assessment.shortfall
