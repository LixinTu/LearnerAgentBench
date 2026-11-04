"""Analysis tools added after the passive floor was measured: scoring stored runs against changed checks, reading a
score against what the task gives away for free, and building a run set out of several sweeps."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from learneragentbench.analysis import collect_runs, passive_floor, summarize_runs
from learneragentbench.harness import run_one
from learneragentbench.harness.cli import main
from learneragentbench.harness.runner import RescoreError, rescore
from learneragentbench.harness.sweep import rerun_runs
from learneragentbench.runtime import ActionListAdapter
from learneragentbench.schema import Action, RunConfig
from learneragentbench.tasks import Dataset

ROOT = Path(__file__).resolve().parents[2]
TASK = "D01_midterm_plan_from_rules"


def _copy_data(tmp: Path) -> Path:
    import shutil
    dest = tmp / "data"
    shutil.copytree(ROOT / "data", dest)
    return dest


def _task_file(data: Path) -> Path:
    return next(data.glob(f"tasks/*/{TASK}.yaml"))


def _run(ds: Dataset, out: Path, message: str = "Plan is set.") -> Path:
    cfg = RunConfig(model="m", adapter="scripted", output_dir=str(out), tags=["exp", "cond"], condition="cond")
    res = run_one(ds, TASK, "base", cfg, 0, out_root=out, run_id="r1", adapter_factory=lambda c, t, w, e: ActionListAdapter([Action.final(message)]))
    return res.out_dir


def test_rescore_follows_changed_checks_and_keeps_the_original(tmp_path: Path) -> None:
    data = _copy_data(tmp_path)
    out = _run(Dataset(str(data)), tmp_path / "runs")
    before = json.loads((out / "verdict.json").read_text(encoding="utf-8"))
    assert rescore(out, Dataset(str(data)))[1] is False  # nothing changed: nothing written
    assert not (out / "verdict_at_run.json").exists()
    f = _task_file(data)
    spec = yaml.safe_load(f.read_text(encoding="utf-8"))
    spec["checks"] = [c for c in spec["checks"] if c["id"] != "finished"]
    f.write_text(yaml.safe_dump(spec, allow_unicode=True, sort_keys=False), encoding="utf-8")
    assert rescore(out, Dataset(str(data)), dry_run=True)[1] is True
    assert not (out / "verdict_at_run.json").exists()  # a dry run writes nothing
    verdict, moved = rescore(out, Dataset(str(data)))
    assert moved and "finished" not in {c.check_id for c in verdict.checks}
    assert json.loads((out / "verdict_at_run.json").read_text(encoding="utf-8")) == before
    assert "finished" in {c["id"] for c in json.loads((out / "task_effective_at_run.json").read_text(encoding="utf-8"))["checks"]}
    assert "finished" not in {c["id"] for c in json.loads((out / "task_effective.json").read_text(encoding="utf-8"))["checks"]}
    # re-scoring again keeps the true original
    rescore(out, Dataset(str(data)))
    assert json.loads((out / "verdict_at_run.json").read_text(encoding="utf-8")) == before


@pytest.mark.parametrize("field", ["user_goal", "available_tools"])
def test_rescore_refuses_when_the_agent_could_see_the_change(tmp_path: Path, field: str) -> None:
    data = _copy_data(tmp_path)
    out = _run(Dataset(str(data)), tmp_path / "runs")
    f = _task_file(data)
    spec = yaml.safe_load(f.read_text(encoding="utf-8"))
    spec[field] = "A different request." if field == "user_goal" else spec[field][:-1]
    f.write_text(yaml.safe_dump(spec, allow_unicode=True, sort_keys=False), encoding="utf-8")
    with pytest.raises(RescoreError, match=field):
        rescore(out, Dataset(str(data)))
    assert main(["--data-dir", str(data), "rescore", str(tmp_path / "runs")]) == 1  # the command reports it as a failure
    assert main(["--data-dir", str(data), "rescore", str(tmp_path / "runs"), "--skip-task", TASK]) == 0  # the re-run task is left alone


def test_passive_floor_is_a_real_passive_run_and_unknown_variants_have_none() -> None:
    f = passive_floor(TASK, "base")
    assert f is not None and 0.0 < f < 0.5
    assert passive_floor(TASK, "no_such_variant") is None


def test_summary_shows_the_floor_and_the_score_above_it(tmp_path: Path) -> None:
    ds = Dataset()
    _run(ds, tmp_path / "runs", "I had a look; nothing to do.")
    table = summarize_runs(tmp_path / "runs", group_by="condition", floor=True)
    head, row = table.splitlines()[:2]
    assert head.split()[-2:] == ["floor", "above"]
    f, above = row.split()[-2:]
    assert float(f) == pytest.approx(passive_floor(TASK, "base"), abs=0.005)
    assert float(above) == pytest.approx(0.0, abs=0.011)  # the same reply as the floor run earns nothing above it


def test_collect_filters_and_never_counts_a_run_twice(tmp_path: Path) -> None:
    ds = Dataset()
    d = _run(ds, tmp_path / "a")
    assert json.loads((d / "task_effective.json").read_text(encoding="utf-8"))["family"].startswith("D_")
    assert collect_runs(tmp_path / "out", [tmp_path / "a"], where_not={"family": "D_multi_session_study_planning"}) == 0
    assert collect_runs(tmp_path / "out", [tmp_path / "a"], where={"condition": "cond"}) == 1
    assert sorted(x.name for x in (tmp_path / "out" / "r1").iterdir()) == ["config.json", "task_effective.json", "verdict.json"]
    assert "cond" in summarize_runs(tmp_path / "out", group_by="condition")
    with pytest.raises(ValueError, match="collected before"):
        collect_runs(tmp_path / "out", [tmp_path / "a"])


def test_rerun_replaces_in_place_and_keeps_the_original(tmp_path: Path) -> None:
    ds = Dataset()
    root = tmp_path / "sweep"
    out = _run(ds, root, "First attempt.")
    before = json.loads((out / "verdict.json").read_text(encoding="utf-8"))
    factory = lambda c, t, w, e: ActionListAdapter([Action.final("Second attempt.")])  # noqa: E731
    assert rerun_runs(root, ["r1"], adapter_factory=factory, log=lambda _: None) == {"done": 1, "skipped": 0, "failed": 0}
    old = tmp_path / "_superseded" / "sweep" / "r1"
    assert json.loads((old / "verdict.json").read_text(encoding="utf-8")) == before
    new = json.loads((out / "trajectory.json").read_text(encoding="utf-8"))
    assert new["final_message"] == "Second attempt."
    cfg = json.loads((out / "config.json").read_text(encoding="utf-8"))
    assert (cfg["seed"], cfg["condition"], cfg["task_id"], cfg["variant_id"]) == (0, "cond", TASK, "base")
    # Resumable: a finished re-run is not repeated, and its original is not overwritten by it.
    assert rerun_runs(root, ["r1"], adapter_factory=factory, log=lambda _: None) == {"done": 0, "skipped": 1, "failed": 0}
    assert json.loads((old / "trajectory.json").read_text(encoding="utf-8"))["final_message"] == "First attempt."
    # An interrupted re-run starts over from the stored configuration.
    (out / "verdict.json").unlink()
    assert rerun_runs(root, ["r1"], adapter_factory=factory, log=lambda _: None)["done"] == 1
    with pytest.raises(FileNotFoundError):
        rerun_runs(root, ["nothing_here"], adapter_factory=factory, log=lambda _: None)
