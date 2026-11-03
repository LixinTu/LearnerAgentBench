"""A hint policy that changes mid-session: `policy_after_event` makes the tutoring verifier judge
every tutor turn at or after the event's delivery step by the new policy, and earlier turns (or all
turns, if the event never fired) by the old one."""
from __future__ import annotations

from pathlib import Path

from learneragentbench.env import World, build_world
from learneragentbench.runtime import ActionListAdapter, AgentLoop, RunSpec
from learneragentbench.schema import Action, CheckSpec, ScheduledEvent
from learneragentbench.tasks import Dataset, resolve_variant
from learneragentbench.tools import REGISTRY, ToolContext, ToolExecutor
from learneragentbench.verify import VerifyContext, run_checks

DS = Dataset()
TASK_ID = "C01_hints_on_my_terms"
PROBLEMS = {"P1": {"answer": [r"\bx\s*=\s*5\b"], "intermediate": [r"\b15\b"], "procedural": [r"subtract[^.\n]{0,20}\b4\b", r"\b15\b"], "conceptual": [r"\bundo\b"], "steps": [r"\b15\b"]},
            "P2": {"answer": [r"\bx\s*=\s*7\b"], "intermediate": [r"\b14\b"], "procedural": [r"add[^.\n]{0,20}\b5\b", r"\b14\b"], "conceptual": [r"\bundo\b"], "steps": [r"\b14\b"]},
            "P3": {"answer": [r"\bx\s*=\s*9\b"], "intermediate": [r"\b18\b"], "procedural": [r"double[^.\n]{0,20}\b9\b", r"\b18\b"], "conceptual": [r"\bundo\b"], "steps": [r"\b18\b"]}}
SCRIPT = [{"id": "P1-A1", "kind": "attempt", "problem": "P1"}, {"id": "P2-A1", "kind": "attempt", "problem": "P2"},
          {"id": "P2-A2", "kind": "attempt", "problem": "P2"}, {"id": "P3-A1", "kind": "attempt", "problem": "P3"}]
EVENT = ScheduledEvent(id="rule_change", event_kind="preference_update", after_step=3, description="hint after one miss now",
                       payload={"key": "hint_policy", "value": {"hint_after_consecutive_failures": 1}, "text": "From now on hint me after the first miss."})


def _params(aspect: str, with_switch: bool) -> dict:
    p = {"aspect": aspect, "policy": {"hint_after_failures": 2, "no_answer_unless_asked": True}, "problems": PROBLEMS, "script": SCRIPT}
    if with_switch:
        p["policy_after_event"] = {"event_id": "rule_change", "policy": {"hint_after_failures": 1}}
    return p


def _run(actions: list[Action], checks: list[CheckSpec], events: list[ScheduledEvent], tmp_path: Path):
    t = DS.load_task(TASK_ID).model_copy(update={"checks": checks, "event_timeline": events})
    w = build_world(t.initial_state, DS.load_persona(t.persona_id), DS.load_graph("algebra"), task_id=t.task_id)
    init_bytes = w.snapshot_bytes()
    ex = ToolExecutor(REGISTRY, ToolContext(w, run_id="r", allowed_tools=t.available_tools))
    spec = RunSpec(run_id="r", task_id=t.task_id, persona_id=t.persona_id, model="m", adapter="a", user_goal=t.user_goal,
                   allowed_tools=t.available_tools, max_steps=20, events=list(events))
    traj = AgentLoop(w, ex, ActionListAdapter(actions), spec, tmp_path).run()
    initial = World.new(w.now)
    initial.restore_bytes(init_bytes)
    return run_checks(VerifyContext(world=w, initial_world=initial, trajectory=traj, task=t, variant=resolve_variant(t, "base")))


# steps: 0 get_preferences, 1 ask (P1-A1), 2 ask (P2-A1), 3 ask (P2-A2), 4 final (P3-A1); the event is delivered at step 3
NO_HINT_AT_FIRST = "Not quite — have another look and try again."
HINT = "Here's the step: subtract 4, then you get 15; or for the others add 5 to get 14, double 9 to get 18."


def test_turns_after_the_event_follow_the_new_policy(tmp_path: Path) -> None:
    checks = [CheckSpec(id="due", description="", verifier="tutoring.hint_policy", params=_params("hint_due", True)),
              CheckSpec(id="early", description="", verifier="tutoring.hint_policy", params=_params("hint_early", True))]
    # old rule before the event (no hint at P1-A1, P2-A1), hint at the second miss, and — new rule — a hint at P3's FIRST miss
    good = [Action.call("get_preferences"), Action.ask(NO_HINT_AT_FIRST), Action.ask(NO_HINT_AT_FIRST), Action.ask(HINT), Action.final(HINT)]
    v = _run(good, checks, [EVENT], tmp_path)
    by = {c.check_id: c for c in v.checks}
    assert by["due"].passed is True, by["due"].evidence
    assert by["early"].passed is True, by["early"].evidence
    # same replies but no hint at P3's first miss: under the new policy that hint was due
    stale = [Action.call("get_preferences"), Action.ask(NO_HINT_AT_FIRST), Action.ask(NO_HINT_AT_FIRST), Action.ask(HINT), Action.final(NO_HINT_AT_FIRST)]
    v2 = _run(stale, checks, [EVENT], tmp_path / "b")
    assert {c.check_id: c.passed for c in v2.checks}["due"] is False


def test_without_the_switch_param_or_the_event_the_old_policy_applies_throughout(tmp_path: Path) -> None:
    checks_no_switch = [CheckSpec(id="early", description="", verifier="tutoring.hint_policy", params=_params("hint_early", False))]
    hint_at_p3 = [Action.call("get_preferences"), Action.ask(NO_HINT_AT_FIRST), Action.ask(NO_HINT_AT_FIRST), Action.ask(HINT), Action.final(HINT)]
    v = _run(hint_at_p3, checks_no_switch, [EVENT], tmp_path)
    assert v.checks[0].passed is False  # P3-A1 hint is premature under the old rule
    checks_switch = [CheckSpec(id="early", description="", verifier="tutoring.hint_policy", params=_params("hint_early", True))]
    v2 = _run(hint_at_p3, checks_switch, [], tmp_path / "b")  # switch declared, but the event is not in the run at all
    assert v2.checks[0].passed is False


# A rule change tied to the conversation arrives with the same student line however many tools the agent calls first.
def _c07_turn_policies(actions: list[Action], tmp_path: Path) -> dict:
    from learneragentbench.harness.runner import run_one
    from learneragentbench.schema import RunConfig
    from learneragentbench.verify.tutoring import replay
    cfg = RunConfig(model="scripted", adapter="scripted", output_dir="unused")
    out = run_one(DS, "C07_rule_changes_mid_tutoring", "base", cfg, 0, out_root=tmp_path,
                  adapter_factory=lambda c, t, w, e: ActionListAdapter(list(actions)))
    task = DS.load_task("C07_rule_changes_mid_tutoring")
    params = next(c.params for c in task.checks if c.verifier == "tutoring.hint_policy")
    world = World.from_snapshot(out.out_dir / "world_final.db")
    ctx = VerifyContext(world=world, initial_world=None, trajectory=out.trajectory, task=task, variant=resolve_variant(task, "base"))
    return {f["id"]: f["policy"]["show_answer_after_failures"] for f in replay(ctx, params)["findings"]}


TALK = [Action.ask("One"), Action.ask("Two"), Action.ask("Three"), Action.ask("Four"), Action.final("Five")]


def test_the_rule_changes_at_the_same_line_for_a_talker_and_for_an_agent_that_reads_first(tmp_path: Path) -> None:
    expected = {"P1-A1": 2, "P1-A2": 2, "P2-A1": None, "P2-A2": None, "P2-ASK": None}
    assert _c07_turn_policies(TALK, tmp_path / "talk") == expected
    reads = [Action.call("get_preferences"), Action.call("search_memory", query="hint"), Action.call("get_student_profile")]
    assert _c07_turn_policies(reads + TALK, tmp_path / "reads") == expected
    between = [Action.ask("One"), Action.call("get_preferences"), Action.call("get_student_profile"), Action.ask("Two"),
               Action.call("search_memory", query="hint"), Action.ask("Three"), Action.ask("Four"), Action.final("Five")]
    assert _c07_turn_policies(between, tmp_path / "between") == expected


def test_an_event_in_a_conversation_is_tied_to_the_conversation() -> None:
    """Counting loop steps here made the rule change late for an agent that only talks (after the point it matters) and
    early for one that calls tools first. Same class as above, so every scripted task has to use the line count."""
    for tid in DS.task_ids():
        t = DS.load_task(tid)
        for v in [None, *t.variants]:
            eff = t if v is None else None
            if eff is None:
                from learneragentbench.tasks.variants import effective_task
                eff = effective_task(t, v)
            if eff.simulated_user.scripted_replies:
                for ev in eff.event_timeline:
                    assert ev.after_student_lines is not None, f"{tid}/{v.id if v else 'base'}: event {ev.id} counts steps"


def test_an_event_needs_some_trigger() -> None:
    import pytest
    with pytest.raises(ValueError, match="after_student_lines"):
        ScheduledEvent(id="x", event_kind="preference_update")
