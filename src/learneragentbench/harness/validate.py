"""Static + dynamic validation of a task: schema, references, verifiers, and (optionally) the
oracle policy must succeed on the base task and every variant."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from ..env import build_world
from ..schema import RunConfig
from ..tasks import Dataset, apply_patch, effective_task, resolve_variant
from ..tools import REGISTRY
from ..verify import VERIFIERS


def validate_task(ds: Dataset, task_id: str, *, run_oracle: bool = False, out_root: str | Path = "runs/validate") -> dict[str, Any]:
    problems: list[str] = []
    task = ds.load_task(task_id)
    if task.persona_id not in ds.persona_ids():
        problems.append(f"persona {task.persona_id!r} not found")
    graph_id = task.initial_state.skill_graph or "algebra"
    if graph_id not in ds.graph_ids():
        problems.append(f"skill graph {graph_id!r} not found")
    for t in task.available_tools:
        if t not in REGISTRY:
            problems.append(f"unknown tool {t!r}")
    for c in task.checks:
        if c.verifier not in VERIFIERS:
            problems.append(f"check {c.id}: unknown verifier {c.verifier!r}")
    if not any(c.hard for c in task.checks):
        problems.append("no hard (failure-condition) check")
    for v in task.variants:
        for c in v.checks_add:
            if c.verifier not in VERIFIERS:
                problems.append(f"variant {v.id} check {c.id}: unknown verifier {c.verifier!r}")
        if v.patch.persona_id and v.patch.persona_id not in ds.persona_ids():
            problems.append(f"variant {v.id}: persona {v.patch.persona_id!r} not found")
        for t in v.patch.tools_add:
            if t not in REGISTRY:
                problems.append(f"variant {v.id}: unknown tool {t!r}")
    # every variant's world must build and patch cleanly
    if not problems:
        for vid in ["base", *[v.id for v in task.variants]]:
            variant = resolve_variant(task, vid)
            eff = effective_task(task, variant)
            try:
                world = build_world(eff.initial_state, ds.load_persona(eff.persona_id), ds.load_graph(graph_id),
                                    task_memory=eff.memory, task_id=task_id)
                apply_patch(world, variant.patch, condition=variant.condition, run_seed_text="validate")
            except Exception as exc:
                problems.append(f"variant {vid}: world build failed: {type(exc).__name__}: {exc}")
    oracle_lines: list[str] = []
    if run_oracle and not problems:
        from .runner import run_one
        cfg = RunConfig(model="oracle", adapter="oracle", output_dir=str(out_root))
        for vid in ["base", *[v.id for v in task.variants]]:
            try:
                res = run_one(ds, task_id, vid, cfg, 0, out_root=out_root)
            except KeyError as exc:
                problems.append(f"variant {vid}: {exc}")
                continue
            v = res.verdict
            if not v.task_success:
                failed = [c.check_id for c in v.checks if c.passed is not True]
                problems.append(f"variant {vid}: oracle did not succeed: {failed} (status {res.trajectory.status})")
            oracle_lines.append(f"{vid}: {v.score:g}/{v.max_score:g}")
    summary = (f"{task.family.value} · {len(task.checks)} checks · {len(task.variants)} variants"
               + (f" · oracle {', '.join(oracle_lines)}" if oracle_lines else ""))
    return {"ok": not problems, "problems": problems, "summary": summary}
