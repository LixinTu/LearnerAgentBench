"""Negative tests for every task: agents that do nothing, agents that only *claim* success, and
the deliberately wrong behaviours each task declares in ``negative_cases`` must all fail in the
way the task says. This is the guard against verifiers that reward talk instead of state."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from learneragentbench.harness import run_one
from learneragentbench.runtime import ActionListAdapter
from learneragentbench.schema import Action, RunConfig, ToolCall
from learneragentbench.tasks import Dataset

DS = Dataset()
CFG = RunConfig(model="negative", adapter="scripted", output_dir="unused")

CLAIM = ("All done. I reviewed your records, created the study plan and put every block on your calendar, "
         "added the tasks, sent the messages you asked for, recorded your progress and saved what I learned "
         "to memory. Nothing is pending.")


def _actions(raw: list[dict[str, Any]]) -> list[Action]:
    out = []
    for a in raw:
        t = a.get("type", "tool_call")
        if t == "tool_call":
            out.append(Action(type="tool_call", tool_call=ToolCall(tool=a["tool"], args=dict(a.get("args", {})))))
        elif t == "ask_user":
            out.append(Action.ask(a.get("message", "?")))
        elif t == "wait":
            out.append(Action.wait(int(a.get("minutes", 60))))
        else:
            out.append(Action.final(a.get("message", "done")))
    return out


def _run(task_id: str, variant: str, actions: list[Action], tmp_path: Path):
    return run_one(DS, task_id, variant, CFG, 0, out_root=tmp_path,
                   adapter_factory=lambda cfg, task, world, ex: ActionListAdapter(list(actions)))


@pytest.mark.parametrize("task_id", DS.task_ids())
def test_doing_nothing_fails(task_id: str, tmp_path: Path) -> None:
    res = _run(task_id, "base", [Action.final("I had a look; nothing to do.")], tmp_path)
    assert not res.verdict.task_success
    assert res.verdict.hard_failures, "every task must have a hard check that a passive agent fails"


@pytest.mark.parametrize("task_id", DS.task_ids())
def test_claiming_success_without_acting_fails(task_id: str, tmp_path: Path) -> None:
    res = _run(task_id, "base", [Action.final(CLAIM)], tmp_path)
    v = res.verdict
    assert not v.task_success
    assert v.score / v.max_score <= 0.5, f"a talker scored {v.score}/{v.max_score} on {task_id}"
    assert v.failure_attribution == "agent"


CASES = [(tid, nc) for tid in DS.task_ids() for nc in DS.load_task(tid).negative_cases]


@pytest.mark.parametrize(("task_id", "case"), CASES, ids=[f"{t}:{c.id}" for t, c in CASES])
def test_declared_negative_case(task_id: str, case, tmp_path: Path) -> None:
    res = _run(task_id, case.variant, _actions(case.actions), tmp_path)
    v = res.verdict
    by = {c.check_id: c for c in v.checks}
    assert v.task_success == case.expect_task_success, [(c.check_id, c.passed, c.evidence) for c in v.checks]
    for cid in case.expect_fail_checks:
        assert cid in by, f"{task_id}: check {cid} not in verdict"
        assert by[cid].passed is False, f"{task_id}/{case.id}: {cid} should fail; evidence: {by[cid].evidence}"
    if case.expect_authorization_violation:
        assert v.authorization_violations
    if case.expect_duplicate:
        assert v.duplicate_actions


def test_every_task_declares_at_least_one_negative_case() -> None:
    missing = [tid for tid in DS.task_ids() if not DS.load_task(tid).negative_cases]
    assert not missing, missing
