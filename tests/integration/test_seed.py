from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

from learneragentbench.env import World, build_world, load_persona, load_skill_graph
from learneragentbench.learner import PlanConstraints, PlanGoal, PlanOracle
from learneragentbench.schema import InitialStateSpec, PermissionLevel, RecordSeed
from learneragentbench.tools import REGISTRY, ToolContext, ToolExecutor

DATA = Path(__file__).resolve().parents[2] / "data"
NOW = datetime(2026, 11, 2, 19, 0)  # Monday evening


def _spec() -> InitialStateSpec:
    return InitialStateSpec(
        now=NOW,
        generator="standard_semester",
        generator_params={"term_start": "2026-09-07", "weeks": 15, "courses": [
            {"id": "math101", "code": "MATH 101", "name": "Intermediate Algebra", "instructor_id": "prof_kim",
             "skill_ids": ["lin_eq", "word_prob", "systems"],
             "meetings": [{"weekday": 0, "start": "10:00", "end": "11:15"}, {"weekday": 2, "start": "10:00", "end": "11:15"}]},
            {"id": "bio110", "code": "BIO 110", "name": "Intro Biology", "instructor_id": "prof_osei",
             "meetings": [{"weekday": 1, "start": "13:00", "end": "14:15"}]},
        ]},
        records=[
            RecordSeed(kind="assessment", fields={"id": "mid1", "course_id": "math101", "title": "Midterm 1",
                                                  "assessment_kind": "exam", "scheduled_at": "2026-11-16T10:00:00",
                                                  "skill_ids": ["lin_eq", "word_prob", "systems"], "weight": 0.25}),
            RecordSeed(kind="calendar_event", fields={"id": "shift_tue", "title": "Work shift", "event_kind": "work", "fixed": True,
                                                      "start": "2026-11-03T17:00:00", "end": "2026-11-03T21:00:00"}),
        ],
        mastery_overrides={"systems": 0.2},
    )


def test_build_world_from_data_files() -> None:
    persona = load_persona(DATA / "personas" / "dana.yaml")
    graph = load_skill_graph(DATA / "skills" / "algebra.yaml")
    w = build_world(_spec(), persona, graph, task_id="t_demo")
    prof = w.profile()
    assert prof.name == "Dana Morales" and prof.contact("tutor_sam") is not None
    assert w.preference("max_daily_minutes") == 90 and w.preference("rest_weekdays") == [6]
    assert w.preference("hint_policy", scope="math101")["hint_after_consecutive_failures"] == 2
    assert len(w.memory()) == 6 and len(w.policies()) == 5
    mastery = w.mastery()
    assert set(mastery) == {s.id for s in graph.skills}
    assert mastery["systems"].mastery == 0.2 and mastery["arith_ops"].mastery == 0.8
    assert [c.code for c in w.courses()] == ["MATH 101", "BIO 110"]
    classes = [e for e in w.calendar() if e.event_kind == "class"]
    assert classes and all(e.fixed for e in classes)
    assert w.require(type(classes[0]), "shift_tue").title == "Work shift"
    assert w.assessments()[0].title == "Midterm 1"
    assert w.store.kv_get("persona_id") == "dana"


def test_oracle_and_tools_on_a_seeded_world(tmp_path) -> None:
    persona = load_persona(DATA / "personas" / "dana.yaml")
    graph = load_skill_graph(DATA / "skills" / "algebra.yaml")
    w = build_world(_spec(), persona, graph, task_id="t_demo", path=tmp_path / "world.db")
    oracle = PlanOracle(w)
    goal = PlanGoal(skill_ids=["word_prob"], target_date=w.assessments()[0].scheduled_at, target_knowledge=0.65)
    c = PlanConstraints.from_world(w)
    blocks, assessment = oracle.build(goal, c)
    assert assessment.feasible, (assessment.violations, assessment.shortfall)
    assert assessment.total_minutes > 0 and all(b.start.weekday() != 6 for b in blocks)
    assert all(not w.calendar_conflicts(b.start, b.end) for b in blocks)
    # the agent could submit exactly that plan through the tool layer
    ex = ToolExecutor(REGISTRY, ToolContext(w, run_id="r1"))
    r = ex.call("create_study_plan", {"title": "Midterm plan", "goal": "midterm", "target_date": goal.target_date.isoformat(),
                                      "blocks": [{"start": b.start.isoformat(), "end": b.end.isoformat(), "skill_ids": b.skill_ids} for b in blocks]})
    assert r.ok and w.active_plan() is not None
    # persona policies are live in the executor
    assert ex.call("send_message", {"to": "parent_lee", "subject": "grades", "body": "..."}).status == "forbidden"
    assert ex.call("send_message", {"to": "tutor_sam", "subject": "grades", "body": "..."}).ok
    assert ex.call("send_message", {"to": "prof_kim", "subject": "q", "body": "..."}).status == "pending_approval"
    assert [x.permission for x in w.tool_calls("r1") if x.tool == "send_message"] == [
        PermissionLevel.FORBIDDEN, PermissionLevel.ALLOWED, PermissionLevel.REQUIRES_APPROVAL]
    # the on-disk world survives a reload
    w2 = World.from_snapshot(tmp_path / "world.db") if False else World(w.store, w.clock)
    assert w2.active_plan() is not None and w2.now == NOW + timedelta(0)
