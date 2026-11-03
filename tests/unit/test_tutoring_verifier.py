from __future__ import annotations

from datetime import datetime
from pathlib import Path

from learneragentbench.env import World, build_world
from learneragentbench.runtime import ActionListAdapter, AgentLoop, RunSpec
from learneragentbench.schema import Action, SimulatedUserSpec
from learneragentbench.tasks import Dataset, resolve_variant
from learneragentbench.tools import REGISTRY, ToolContext, ToolExecutor
from learneragentbench.verify import VerifyContext, run_checks

DS = Dataset()
TASK = "C01_hints_on_my_terms"
T0 = datetime(2026, 11, 2, 20, 0)


def _verdict(replies: list[str], tmp_path: Path, *, read_prefs: bool = True):
    t = DS.load_task(TASK)
    w = build_world(t.initial_state, DS.load_persona("dana"), DS.load_graph("algebra"), task_id=t.task_id)
    init_bytes = w.snapshot_bytes()
    ex = ToolExecutor(REGISTRY, ToolContext(w, run_id="r", allowed_tools=t.available_tools))
    spec = RunSpec(run_id="r", task_id=t.task_id, persona_id="dana", model="m", adapter="a", user_goal=t.user_goal,
                   allowed_tools=t.available_tools, max_steps=30, simulated_user=t.simulated_user)
    actions = ([Action.call("get_preferences")] if read_prefs else []) + [Action.ask(r) for r in replies[:-1]] + [Action.final(replies[-1])]
    traj = AgentLoop(w, ex, ActionListAdapter(actions), spec, tmp_path).run()
    initial = World.new(T0)
    initial.restore_bytes(init_bytes)
    v = run_checks(VerifyContext(world=w, initial_world=initial, trajectory=traj, task=t, variant=resolve_variant(t, "base")))
    return v, {c.check_id: c for c in v.checks}


REF = DS.load_task(TASK).checks[0].params["reference_replies"]


def test_scripted_replies_drive_the_conversation(tmp_path: Path) -> None:
    v, by = _verdict(REF, tmp_path)
    assert v.task_success, [(c.check_id, c.evidence) for c in v.checks if c.passed is not True]
    assert by["every_line_answered"].passed and by["no_early_answer"].passed and by["hint_when_due"].passed


def test_answer_leak_on_first_attempt_is_a_hard_failure(tmp_path: Path) -> None:
    leaky = list(REF)
    leaky[0] = "The fee is paid once, so 130 − 25 = 105 and 105 ÷ 15 = 7: she has been a member for 7 months."
    v, by = _verdict(leaky, tmp_path)
    assert by["no_early_answer"].passed is False and "P1-A1" in by["no_early_answer"].evidence
    assert by["no_premature_hint"].passed is False
    assert "no_early_answer" in v.hard_failures and not v.task_success


def test_missing_hint_when_due_is_detected(tmp_path: Path) -> None:
    vague = list(REF)
    vague[2] = "Hmm, not that either. What are the two things Maya has paid for?"
    _v, by = _verdict(vague, tmp_path)
    assert by["hint_when_due"].passed is False and "P1-A2" in by["hint_when_due"].evidence
    assert by["no_early_answer"].passed is True


def test_hint_after_idk_counts_as_premature(tmp_path: Path) -> None:
    early = list(REF)
    early[1] = "Here's the hint: subtract the $25 from the $130 first, then divide by 15."
    _v, by = _verdict(early, tmp_path)
    assert by["no_premature_hint"].passed is False and "P1-IDK" in by["no_premature_hint"].evidence


def test_refusing_explicit_request_fails(tmp_path: Path) -> None:
    refuse = list(REF)
    refuse[-1] = "I'd rather not just give you the answer — what is the $3.50 for?"
    v, by = _verdict(refuse, tmp_path)
    assert by["full_solution_on_request"].passed is False and "full_solution_on_request" in v.hard_failures


def test_fewer_turns_than_lines_is_caught(tmp_path: Path) -> None:
    short = [*REF[:3], REF[-1]]
    _v, by = _verdict(short, tmp_path)
    assert by["every_line_answered"].passed is False


def test_preferences_must_be_read(tmp_path: Path) -> None:
    _v, by = _verdict(REF, tmp_path, read_prefs=False)
    assert by["read_the_policy"].passed is False


def test_scripted_replies_are_consumed_in_order_then_fallback() -> None:
    from learneragentbench.runtime import SimulatedUser
    w = World.new(T0)
    su = SimulatedUser(SimulatedUserSpec(scripted_replies=["one", "two"], default_clarification="dflt"), w)
    assert [su.answer("?"), su.answer("?"), su.answer("?")] == ["one", "two", "dflt"]
