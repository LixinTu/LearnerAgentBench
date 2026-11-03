"""Two verifier additions: a weekly cap on plan minutes (a rule the daily planner constraints cannot
express) and a session-wide counting scope for the tutoring hint policy."""
from __future__ import annotations

from pathlib import Path

from learneragentbench.env import World, build_world
from learneragentbench.runtime import ActionListAdapter, AgentLoop, RunSpec
from learneragentbench.schema import Action, CheckSpec
from learneragentbench.tasks import Dataset, resolve_variant
from learneragentbench.tools import REGISTRY, ToolContext, ToolExecutor
from learneragentbench.verify import VerifyContext, run_checks

DS = Dataset()


def _run(task_id: str, actions: list[Action], checks: list[CheckSpec], tmp_path: Path):
    t = DS.load_task(task_id).model_copy(update={"checks": checks})
    w = build_world(t.initial_state, DS.load_persona(t.persona_id), DS.load_graph(t.initial_state.skill_graph or "algebra"), task_id=t.task_id)
    init_bytes = w.snapshot_bytes()
    ex = ToolExecutor(REGISTRY, ToolContext(w, run_id="r", allowed_tools=t.available_tools))
    spec = RunSpec(run_id="r", task_id=t.task_id, persona_id=t.persona_id, model="m", adapter="a", user_goal=t.user_goal,
                   allowed_tools=t.available_tools, max_steps=20)
    traj = AgentLoop(w, ex, ActionListAdapter(actions), spec, tmp_path).run()
    initial = World.new(w.now)
    initial.restore_bytes(init_bytes)
    return run_checks(VerifyContext(world=w, initial_world=initial, trajectory=traj, task=t, variant=resolve_variant(t, "base")))


def _blocks(spec: list[tuple[str, str, str]]) -> list[dict]:
    return [{"start": a, "end": b, "skill_ids": [s], "activity": "practice"} for a, b, s in spec]


def test_weekly_cap_sums_blocks_per_iso_week(tmp_path: Path) -> None:
    checks = [CheckSpec(id="cap", description="", verifier="plan.weekly_minutes_cap", params={"max_minutes": 90, "written_this_run": True})]
    # week of Nov 2: 60 min; week of Nov 9: 120 min -> over the cap
    # Dana's world has work shifts on Tuesday and Thursday evenings, so the blocks sit on Mon/Wed/Fri/Sat
    plan = _blocks([("2026-11-04T19:00:00", "2026-11-04T19:30:00", "word_prob"), ("2026-11-06T19:00:00", "2026-11-06T19:30:00", "word_prob"),
                    ("2026-11-09T19:00:00", "2026-11-09T19:30:00", "word_prob"), ("2026-11-11T19:00:00", "2026-11-11T19:30:00", "word_prob"),
                    ("2026-11-13T19:00:00", "2026-11-13T19:30:00", "word_prob"), ("2026-11-14T10:00:00", "2026-11-14T10:30:00", "word_prob")])
    v = _run("D01_midterm_plan_from_rules", [Action.call("create_study_plan", title="p", goal="g", target_date="2026-11-16T10:00:00", blocks=plan), Action.final("done")], checks, tmp_path)
    assert v.checks[0].passed is False and "2026-W46" in v.checks[0].evidence, v.checks[0].evidence
    v2 = _run("D01_midterm_plan_from_rules", [Action.call("create_study_plan", title="p", goal="g", target_date="2026-11-16T10:00:00", blocks=plan[:4]), Action.final("done")], checks, tmp_path / "b")
    assert v2.checks[0].passed is True
    v3 = _run("D01_midterm_plan_from_rules", [Action.final("nothing")], checks, tmp_path / "c")
    assert v3.checks[0].passed is False  # no plan written this run


PROBLEMS = {"P1": {"answer": [r"\bx\s*=\s*5\b"], "intermediate": [r"\b15\b"], "procedural": [r"subtract[^.\n]{0,20}\b4\b", r"\b15\b"], "conceptual": [r"\bundo\b"], "steps": [r"\b15\b"]},
            "P2": {"answer": [r"\bx\s*=\s*7\b"], "intermediate": [r"\b14\b"], "procedural": [r"add[^.\n]{0,20}\b5\b", r"\b14\b"], "conceptual": [r"\bundo\b"], "steps": [r"\b14\b"]}}
SCRIPT = [{"id": "P1-A1", "kind": "attempt", "problem": "P1"}, {"id": "P1-C", "kind": "correct", "problem": "P1"},
          {"id": "P2-A1", "kind": "attempt", "problem": "P2"}, {"id": "P2-C", "kind": "correct", "problem": "P2"}]


def _tut(aspect: str, scope: str) -> dict:
    return {"aspect": aspect, "policy": {"hint_after_failures": 1, "no_answer_unless_asked": True, "show_answer_after_failures": 2, "counting_scope": scope},
            "problems": PROBLEMS, "script": SCRIPT}


def test_session_scope_makes_the_second_problem_due_on_its_first_miss(tmp_path: Path) -> None:
    hint1 = "Subtract 4 from both sides and see what you get."
    confirm = "Right, well done."
    answer2 = "Second miss tonight: add 5 to both sides, 2x = 14, so x = 7."
    hint2 = "Add 5 to both sides first, then divide."
    shows_answer = [Action.call("get_preferences"), Action.ask(hint1), Action.ask(confirm), Action.ask(answer2), Action.final("Right, x = 7.")]
    hints_only = [Action.call("get_preferences"), Action.ask(hint1), Action.ask(confirm), Action.ask(hint2), Action.final("Right, x = 7.")]
    # per_session: the answer at P2-A1 is due (second miss overall) — showing it is right, withholding it fails answer_shown
    for actions, expect in ((shows_answer, True), (hints_only, False)):
        v = _run("C01_hints_on_my_terms", actions, [CheckSpec(id="shown", description="", verifier="tutoring.hint_policy", params=_tut("answer_shown", "per_session")),
                                                    CheckSpec(id="leak", description="", verifier="tutoring.hint_policy", params=_tut("answer_leak", "per_session"))], tmp_path / str(expect))
        by = {c.check_id: c for c in v.checks}
        assert by["shown"].passed is expect, by["shown"].evidence
        assert by["leak"].passed is True
    # per_problem: P2 has one miss, so the same answer is a leak
    v = _run("C01_hints_on_my_terms", shows_answer, [CheckSpec(id="leak", description="", verifier="tutoring.hint_policy", params=_tut("answer_leak", "per_problem"))], tmp_path / "pp")
    assert v.checks[0].passed is False
