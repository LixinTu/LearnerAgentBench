"""End-to-end: the runner builds the world, runs the oracle policy through the real tool layer,
snapshots, verifies and writes every artifact; the CLI drives the same path; a run can be
interrupted and resumed. No language model is involved."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from learneragentbench.env import World
from learneragentbench.harness import load_verdicts, resume_run, reverify, run_one
from learneragentbench.schema import RunConfig
from learneragentbench.tasks import Dataset

TASK = "D01_midterm_plan_from_rules"
DS = Dataset()


def _cfg(**kw) -> RunConfig:
    base = dict(model="oracle", adapter="oracle", output_dir="unused")
    base.update(kw)
    return RunConfig(**base)


ALL_RUNS = [(tid, vid) for tid in DS.task_ids() for vid in ["base", *[v.id for v in DS.load_task(tid).variants]]]


@pytest.mark.parametrize(("task_id", "variant"), ALL_RUNS, ids=[f"{t}:{v}" for t, v in ALL_RUNS])
def test_oracle_succeeds_on_every_task_and_variant(tmp_path: Path, task_id: str, variant: str) -> None:
    res = run_one(DS, task_id, variant, _cfg(), 0, out_root=tmp_path)
    v = res.verdict
    assert v.task_success, [(c.check_id, c.evidence) for c in v.checks if c.passed is not True]
    assert v.failure_attribution == "none" and v.score == v.max_score
    for name in ("config.json", "task_effective.json", "world_init.db", "world_final.db", "steps.jsonl",
                 "trajectory.json", "verdict.json", "variant_log.json"):
        assert (res.out_dir / name).is_file(), name


@pytest.mark.parametrize("variant", ["base", "no_memory", "updated_calendar", "new_result", "relaxed_cap", "no_memory_tool"])
def test_d01_oracle_variants_in_detail(tmp_path: Path, variant: str) -> None:
    res = run_one(DS, TASK, variant, _cfg(), 0, out_root=tmp_path)
    v = res.verdict
    assert v.task_success, [(c.check_id, c.evidence) for c in v.checks if c.passed is not True]
    assert v.failure_attribution == "none" and v.score == v.max_score
    for name in ("config.json", "task_effective.json", "world_init.db", "world_final.db", "steps.jsonl",
                 "trajectory.json", "verdict.json", "variant_log.json"):
        assert (res.out_dir / name).is_file(), name
    final = World.from_snapshot(res.out_dir / "world_final.db")
    assert final.active_plan() is not None
    assert [e for e in final.calendar() if e.event_kind == "study"], "plan blocks should be on the calendar"
    init = World.from_snapshot(res.out_dir / "world_init.db")
    assert init.active_plan() is None
    if variant == "no_memory":
        assert init.memory() == [] and any(s.action.type == "ask_user" for s in res.trajectory.steps)
    if variant == "updated_calendar":
        assert any(e.id == "shift_1107" for e in final.calendar())


def test_memory_and_tool_profiles_change_what_the_agent_sees(tmp_path: Path) -> None:
    res = run_one(DS, TASK, "base", _cfg(memory_access="full"), 0, out_root=tmp_path / "full")
    view = res.trajectory.steps[0].observation.content
    assert view["memory_notes"] and view["history"]
    res2 = run_one(DS, TASK, "base", _cfg(memory_access="tools"), 0, out_root=tmp_path / "tools")
    view2 = res2.trajectory.steps[0].observation.content
    assert view2["memory_notes"] == [] and view2["history"] == []
    res3 = run_one(DS, TASK, "base", _cfg(tool_profile="read_only"), 0, out_root=tmp_path / "ro")
    assert not res3.verdict.task_success  # the oracle cannot write a plan without write tools
    names = {t["function"]["name"] for t in res3.trajectory.steps[0].observation.content["tools"]}
    assert "create_study_plan" not in names and "get_preferences" in names


def test_interrupt_resume_and_reverify(tmp_path: Path) -> None:
    cfg = _cfg(adapter_params={"interrupt_after": 2})
    res = run_one(DS, TASK, "base", cfg, 0, out_root=tmp_path)
    assert res.trajectory.status == "interrupted" and (res.out_dir / "loop_state.json").is_file()
    assert not res.verdict.task_success
    res2 = resume_run(res.out_dir, _cfg(), DS)
    assert res2.trajectory.status == "completed" and res2.verdict.task_success
    assert [s.index for s in res2.trajectory.steps] == list(range(len(res2.trajectory.steps)))
    v = reverify(res.out_dir, DS)
    assert v.task_success and v.score == res2.verdict.score
    assert len(load_verdicts(tmp_path)) == 1


def test_cli_run_show_summarize(tmp_path: Path) -> None:
    out = tmp_path / "runs"
    cmd = [sys.executable, "-m", "learneragentbench.harness.cli", "run", "--model", "oracle", "--adapter", "oracle",
           "--task", TASK, "--variant", "base", "--variant", "no_memory", "--seed", "0", "--out", str(out)]
    p = subprocess.run(cmd, capture_output=True, text=True)
    assert p.returncode == 0, p.stderr
    assert "2/2 runs succeeded" in p.stdout
    run_dirs = sorted(out.iterdir())
    assert len(run_dirs) == 2
    show = subprocess.run([sys.executable, "-m", "learneragentbench.harness.cli", "show", str(run_dirs[0])], capture_output=True, text=True)
    assert show.returncode == 0 and "[PASS] plan_exists" in show.stdout
    summ = subprocess.run([sys.executable, "-m", "learneragentbench.harness.cli", "summarize", str(out)], capture_output=True, text=True)
    assert summ.returncode == 0 and "oracle / base" in summ.stdout and "1.00" in summ.stdout
    cfg = json.loads((run_dirs[0] / "config.json").read_text())
    assert cfg["model"] == "oracle" and cfg["seed"] == 0


def test_cli_validate_reports_ok(tmp_path: Path) -> None:
    p = subprocess.run([sys.executable, "-m", "learneragentbench.harness.cli", "validate", TASK, "--oracle", "--out", str(tmp_path)],
                       capture_output=True, text=True)
    assert p.returncode == 0, p.stdout + p.stderr
    assert "[OK ]" in p.stdout
