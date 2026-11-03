"""`lab summarize` groups by the run's sidecar metadata (experiment condition, task family), not
only by fields that happen to be inside verdict.json."""
from __future__ import annotations

import json
import re
from pathlib import Path

from learneragentbench.analysis.summary import summarize_runs


def _run(root: Path, rid: str, *, condition: str, family: str, success: bool, calls: int) -> None:
    d = root / rid
    d.mkdir(parents=True)
    (d / "verdict.json").write_text(json.dumps({
        "run_id": rid, "task_id": "A01_x", "variant_id": "base", "model": "m", "task_success": success,
        "score": 3.0 if success else 1.0, "max_score": 3.0, "tool_call_count": calls, "authorization_violations": [],
        "failure_attribution": "none" if success else "agent", "hard_failures": [] if success else ["plan_exists"],
        "capability_scores": {"tool_use_and_execution": 1.0 if success else 0.0}, "checks": [],
    }), encoding="utf-8")
    (d / "config.json").write_text(json.dumps({"model": "m", "adapter": "a", "tags": ["exp", condition],
                                               "memory_access": "tools", "tool_profile": "full"}), encoding="utf-8")
    (d / "task_effective.json").write_text(json.dumps({"task_id": "A01_x", "family": family}), encoding="utf-8")


def _row(table: str, prefix: str) -> list[str]:
    line = next(ln for ln in table.splitlines() if ln.startswith(prefix))
    m = re.match(r"(.+?)\s+(\d+)\s+([\d.]+)\s+\[.*?\]\s+([\d.]+)\s+([\d.]+)\s+(\d+)\s+(\d+)\s+(\d+)\s+(\S+)$", line)
    assert m, line
    return list(m.groups())


def test_summary_groups_by_condition_and_family(tmp_path: Path) -> None:
    _run(tmp_path, "r1", condition="tool_agent", family="A_personalized_exam_preparation", success=True, calls=4)
    _run(tmp_path, "r2", condition="chatbot", family="A_personalized_exam_preparation", success=False, calls=0)
    _run(tmp_path, "r3", condition="chatbot", family="B_learning_progress_monitoring", success=False, calls=0)
    by_cond = summarize_runs(tmp_path, group_by="condition")
    assert "?" not in by_cond
    assert _row(by_cond, "chatbot")[1:] == ["2", "0.00", "0.33", "0.0", "2", "2", "0", "agent:2"]
    assert _row(by_cond, "tool_agent")[1:] == ["1", "1.00", "1.00", "4.0", "0", "0", "0", "none:1"]
    by_fam = summarize_runs(tmp_path, group_by="family,condition")
    assert "B_learning_progress_monitoring / chatbot" in by_fam
    assert "A_personalized_exam_preparation / tool_agent" in by_fam
    assert "A_personalized_exam_preparation / chatbot" in by_fam


def test_summary_without_sidecars_falls_back_to_verdict_fields(tmp_path: Path) -> None:
    _run(tmp_path, "r1", condition="tool_agent", family="A_personalized_exam_preparation", success=False, calls=1)
    (tmp_path / "r1" / "config.json").unlink()
    (tmp_path / "r1" / "task_effective.json").unlink()
    table = summarize_runs(tmp_path, group_by="model,variant_id")
    assert table.splitlines()[1].startswith("m / base")
    assert summarize_runs(tmp_path, group_by="condition").splitlines()[1].startswith("?")
