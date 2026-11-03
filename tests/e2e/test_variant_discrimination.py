"""A counterfactual variant has to change something. The base task's oracle actions are replayed unchanged
on every variant: if they still earn full marks, the variant is only legitimate as an invariance control,
and then it must declare the wrong behaviour it does catch as a negative case of its own. A variant that is
neither is decoration: it would inflate the variant count without testing anything."""
from __future__ import annotations

import tempfile
from functools import cache
from pathlib import Path

import pytest

from learneragentbench.harness import run_one
from learneragentbench.runtime import ActionListAdapter
from learneragentbench.schema import Action, RunConfig
from learneragentbench.tasks import Dataset

DS = Dataset()
REPLAY = RunConfig(model="replay", adapter="scripted", output_dir="unused")
ORACLE = RunConfig(model="oracle", adapter="oracle", output_dir="unused")
CASES = [(tid, v.id) for tid in DS.task_ids() for v in DS.load_task(tid).variants]


@cache
def _base_actions(task_id: str) -> tuple[Action, ...]:
    with tempfile.TemporaryDirectory() as d:
        res = run_one(DS, task_id, "base", ORACLE, 0, out_root=Path(d))
    return tuple(s.action for s in res.trajectory.steps)


@pytest.mark.parametrize(("task_id", "variant"), CASES, ids=[f"{t}:{v}" for t, v in CASES])
def test_every_variant_discriminates(task_id: str, variant: str, tmp_path: Path) -> None:
    actions = list(_base_actions(task_id))
    res = run_one(DS, task_id, variant, REPLAY, 0, out_root=tmp_path,
                  adapter_factory=lambda cfg, task, world, ex: ActionListAdapter(list(actions)))
    own_negative = [n.id for n in DS.load_task(task_id).negative_cases if n.variant == variant]
    assert not res.verdict.task_success or own_negative, (
        f"{task_id}/{variant}: the unchanged base trajectory passes it ({res.verdict.score:g}/{res.verdict.max_score:g}) "
        "and it declares no negative case of its own, so nothing shows the variant can fail anybody")
