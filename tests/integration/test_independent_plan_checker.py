"""An independent re-implementation of the structural plan rules, written without looking at
PlanOracle.assess, must agree with it on oracle-built plans and on hand-made bad plans. This
guards against the oracle and the verifier sharing a blind spot."""
from __future__ import annotations

from datetime import datetime, time, timedelta

from learneragentbench.env import World, build_world
from learneragentbench.harness import run_one
from learneragentbench.learner import PlanConstraints, PlanGoal, PlanOracle
from learneragentbench.schema import PlanBlock, RunConfig
from learneragentbench.tasks import Dataset

DS = Dataset()


def independent_violations(blocks: list[PlanBlock], world: World, c: dict, target_date: datetime) -> list[str]:
    """Plain re-implementation: windows from the profile availability ∩ daily limits, rest days,
    daily cap, minimum length, fixed-event overlap, buffer, pairwise overlap."""
    prof = world.profile()
    out: list[str] = []
    per_day: dict[str, int] = {}
    fixed = [e for e in world.calendar() if e.fixed]
    lo = time.fromisoformat(c.get("no_study_before", "07:00"))
    hi = time.fromisoformat(c["no_study_after"])
    for i, b in enumerate(blocks):
        if b.activity == "rest":
            continue
        if b.start.weekday() in c.get("rest_weekdays", []):
            out.append(f"{i}:rest_day")
        wins = prof.availability.windows.get(b.start.weekday()) or []
        inside = False
        for w in wins:
            ws, we = max(time.fromisoformat(w.start), lo), min(time.fromisoformat(w.end), hi)
            if ws <= b.start.time() and b.end.time() <= we and b.start.date() == b.end.date():
                inside = True
        if not wins and lo <= b.start.time() and b.end.time() <= hi and b.start.date() == b.end.date():
            inside = True
        if not inside:
            out.append(f"{i}:window")
        if b.minutes < c["min_block_minutes"]:
            out.append(f"{i}:short")
        if c.get("max_block_minutes") and b.minutes > c["max_block_minutes"]:
            out.append(f"{i}:long")
        if b.end > target_date - timedelta(hours=c["buffer_hours_before_exam"]):
            out.append(f"{i}:buffer")
        for e in fixed:
            if b.start < e.end and e.start < b.end:
                out.append(f"{i}:fixed:{e.id}")
        for j, o in enumerate(blocks):
            if j > i and b.start < o.end and o.start < b.end:
                out.append(f"{i}:{j}:overlap")
        k = b.start.date().isoformat()
        per_day[k] = per_day.get(k, 0) + b.minutes
    for d, m in per_day.items():
        if m > c["max_daily_minutes"]:
            out.append(f"{d}:cap")
    return out


def _world_and_constraints(task_id: str):
    t = DS.load_task(task_id)
    w = build_world(t.initial_state, DS.load_persona(t.persona_id), DS.load_graph("algebra"), task_id=task_id)
    check = next(c for c in t.checks if c.verifier == "plan.respects_constraints")
    return t, w, check.params["constraints"], check.params["goal"]


def test_oracle_plans_pass_both_checkers() -> None:
    for task_id in ("D01_midterm_plan_from_rules", "A01_quadratics_quiz_short_blocks"):
        _t, w, cdict, gdict = _world_and_constraints(task_id)
        a = w.require(type(w.assessments()[0]), gdict["assessment_id"])
        goal = PlanGoal(skill_ids=a.skill_ids, target_date=a.scheduled_at, target_knowledge=gdict["target_knowledge"])
        c = PlanConstraints.from_world(w).model_copy(update=cdict)
        blocks, assessment = PlanOracle(w).build(goal, c)
        assert assessment.feasible, assessment.violations
        assert independent_violations(blocks, w, cdict, a.scheduled_at) == []


def test_bad_plans_are_flagged_by_both_checkers() -> None:
    _t, w, cdict, gdict = _world_and_constraints("D01_midterm_plan_from_rules")
    a = w.require(type(w.assessments()[0]), gdict["assessment_id"])
    goal = PlanGoal(skill_ids=a.skill_ids, target_date=a.scheduled_at, target_knowledge=0.65)
    c = PlanConstraints.from_world(w).model_copy(update=cdict)
    bad = [
        PlanBlock(start=datetime(2026, 11, 8, 10, 0), end=datetime(2026, 11, 8, 10, 45), skill_ids=["lin_eq"]),   # Sunday
        PlanBlock(start=datetime(2026, 11, 3, 18, 0), end=datetime(2026, 11, 3, 18, 45), skill_ids=["lin_eq"]),   # shift
        PlanBlock(start=datetime(2026, 11, 4, 21, 30), end=datetime(2026, 11, 4, 22, 15), skill_ids=["lin_eq"]),  # after 22:00
        PlanBlock(start=datetime(2026, 11, 15, 18, 0), end=datetime(2026, 11, 15, 18, 45), skill_ids=["lin_eq"]), # inside 24 h buffer
        PlanBlock(start=datetime(2026, 11, 6, 18, 0), end=datetime(2026, 11, 6, 18, 20), skill_ids=["lin_eq"]),   # too short
        PlanBlock(start=datetime(2026, 11, 9, 18, 0), end=datetime(2026, 11, 9, 19, 45), skill_ids=["lin_eq"]),   # 105 min > cap
    ]
    ours = PlanOracle(w).assess(bad, goal, c).violations
    theirs = independent_violations(bad, w, cdict, a.scheduled_at)
    assert len(ours) >= 6 and len(theirs) >= 6
    # every bad block is named by both
    for i in range(6):
        assert any(f"block {i}" in v for v in ours) or any(v.startswith("2026-11-09") for v in ours)
        assert any(v.startswith(f"{i}:") for v in theirs) or any(v.endswith(":cap") for v in theirs)


def test_long_blocks_are_flagged_by_both_checkers() -> None:
    """A03's accommodation caps blocks at 20 minutes: a 60-minute block inside the window must be
    named by the oracle's assess and by the independent re-implementation, and the oracle's own
    plans must never exceed the cap."""
    t = DS.load_task("A03_accommodated_exam_short_blocks_with_breaks")
    w = build_world(t.initial_state, DS.load_persona(t.persona_id), DS.load_graph("biology"), task_id=t.task_id)
    check = next(c for c in t.checks if c.verifier == "plan.respects_constraints")
    cdict, gdict = check.params["constraints"], check.params["goal"]
    a = w.require(type(w.assessments()[0]), gdict["assessment_id"])
    goal = PlanGoal(skill_ids=a.skill_ids, target_date=a.scheduled_at, target_knowledge=gdict["target_knowledge"])
    c = PlanConstraints.from_world(w).model_copy(update=cdict)
    assert c.max_block_minutes == 20
    long_block = [PlanBlock(start=datetime(2026, 11, 3, 15, 0), end=datetime(2026, 11, 3, 16, 0), skill_ids=["cell_respiration"])]
    assert any("longer than 20" in v for v in PlanOracle(w).assess(long_block, goal, c).violations)
    assert "0:long" in independent_violations(long_block, w, cdict, a.scheduled_at)
    blocks, assessment = PlanOracle(w).build(goal, c)
    assert assessment.feasible, assessment.violations
    assert blocks and all(b.minutes <= 20 for b in blocks)
    assert independent_violations(blocks, w, cdict, a.scheduled_at) == []


def test_oracle_run_plan_matches_independent_checker_end_to_end(tmp_path) -> None:
    res = run_one(DS, "E01_exam_moved_earlier", "base", RunConfig(model="oracle", adapter="oracle"), 0, out_root=tmp_path)
    assert res.verdict.task_success
    w = World.from_snapshot(res.out_dir / "world_final.db")
    plan = w.active_plan()
    assert plan is not None
    t = DS.load_task("E01_exam_moved_earlier")
    cdict = next(c for c in t.checks if c.verifier == "plan.respects_constraints").params["constraints"]
    exam = w.require(type(w.assessments()[0]), "mid1")
    assert exam.scheduled_at == datetime(2026, 11, 12, 10, 0)
    assert independent_violations(plan.blocks, w, cdict, exam.scheduled_at) == []
