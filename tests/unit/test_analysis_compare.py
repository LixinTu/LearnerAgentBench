"""`lab compare` pairs runs by (task, seed), averages over seeds, and reports the paired difference
with a bootstrap interval over tasks — the only comparison that survives the run-to-run noise."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from learneragentbench.analysis import compare_runs, parse_filter


def _run(root: Path, *, cond: str, task: str, seed: int, frac: float, checks: dict[str, bool], calls: int = 3, invalid: int = 0) -> None:
    rid = f"{cond}__{task}__s{seed}"
    d = root / rid
    d.mkdir(parents=True)
    (d / "verdict.json").write_text(json.dumps({
        "run_id": rid, "task_id": task, "variant_id": "base", "seed": seed, "model": "m", "task_success": frac == 1.0,
        "score": frac * 10, "max_score": 10.0, "tool_call_count": calls, "authorization_violations": [],
        "invalid_actions": ["x"] * invalid, "failure_attribution": "none" if frac == 1.0 else "agent",
        "hard_failures": [k for k, ok in checks.items() if not ok], "capability_scores": {},
        "checks": [{"check_id": k, "passed": ok, "hard": True, "weight": 1.0, "capability": "c", "verifier": "v", "evidence": {}} for k, ok in checks.items()],
    }), encoding="utf-8")
    (d / "config.json").write_text(json.dumps({"model": "m", "adapter": "a", "tags": ["exp", cond], "condition": cond}), encoding="utf-8")


def _build(root: Path) -> None:
    # condition x: T1 0.5/0.5, T2 0.2/0.4, T3 1.0/1.0;  condition y: T1 0.8/0.8, T2 0.2/0.4, T3 0.0/0.0
    _run(root, cond="x", task="T1", seed=0, frac=0.5, checks={"plan": True, "rules": False})
    _run(root, cond="x", task="T1", seed=1, frac=0.5, checks={"plan": True, "rules": False})
    _run(root, cond="x", task="T2", seed=0, frac=0.2, checks={"plan": False})
    _run(root, cond="x", task="T2", seed=1, frac=0.4, checks={"plan": True})
    _run(root, cond="x", task="T3", seed=0, frac=1.0, checks={"plan": True}, calls=5)
    _run(root, cond="x", task="T3", seed=1, frac=1.0, checks={"plan": True}, calls=5)
    _run(root, cond="y", task="T1", seed=0, frac=0.8, checks={"plan": True, "rules": True}, invalid=2)
    _run(root, cond="y", task="T1", seed=1, frac=0.8, checks={"plan": True, "rules": True}, invalid=2)
    _run(root, cond="y", task="T2", seed=0, frac=0.2, checks={"plan": False})
    _run(root, cond="y", task="T2", seed=1, frac=0.4, checks={"plan": True})
    _run(root, cond="y", task="T3", seed=0, frac=0.0, checks={"plan": False}, calls=0)
    _run(root, cond="y", task="T3", seed=1, frac=0.0, checks={"plan": False}, calls=0)


def test_paired_difference_and_check_flips(tmp_path: Path) -> None:
    _build(tmp_path)
    out = compare_runs(tmp_path, tmp_path, filter_a={"condition": "x"}, filter_b={"condition": "y"}, label_a="x", label_b="y")
    lines = out.splitlines()
    assert lines[0].startswith("paired on task_id,seed: 6 pairs over 3 tasks")
    # task means x: .5 .3 1.0 (mean .600); y: .8 .3 0.0 (mean .367); deltas +.3 0 -1.0 → mean -0.233
    assert "score fraction (task means): x 0.600  y 0.367  y-x -0.233 [95% CI" in lines[1]
    assert lines[1].endswith("tasks better/worse/same: 1/1/1")
    assert "success rate: x 0.333  y 0.000" in lines[2]
    assert "tool calls: 3.7 → 2.0" in lines[2] and "invalid calls: 0.0 → 0.7" in lines[2]
    t1 = next(ln for ln in lines if ln.startswith("T1"))
    assert "0.50   0.80   +0.30" in t1
    assert "checks passed by x in every seed and by y in none (1): T3:plan" in out
    assert "checks passed by y in every seed and by x in none (1): T1:rules" in out


def test_filters_pairing_and_errors(tmp_path: Path) -> None:
    _build(tmp_path)
    assert parse_filter("condition=x, variant_id=base") == {"condition": "x", "variant_id": "base"}
    with pytest.raises(ValueError):
        parse_filter("condition")
    # without a filter each side holds two runs per (task, seed): refuse rather than silently average
    with pytest.raises(ValueError, match="more than one run"):
        compare_runs(tmp_path, tmp_path)
    # pairing on condition too makes every run unique and compares x with x: zero difference everywhere
    out = compare_runs(tmp_path, tmp_path, filter_a={"condition": "x"}, filter_b={"condition": "x"}, pair_on="task_id,seed,condition")
    assert "x 0.600  B 0.600  B-A +0.000" in out.replace("A 0.600", "x 0.600")
    assert compare_runs(tmp_path, tmp_path, filter_a={"condition": "x"}, filter_b={"condition": "nope"}).startswith("no pairs")
    with pytest.raises(ValueError, match="task_id"):
        compare_runs(tmp_path, tmp_path, pair_on="seed")
