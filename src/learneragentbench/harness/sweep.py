"""Batch experiments from a YAML config: a grid of (condition × task × variant × seed) runs
with resumable, skip-if-done semantics and a manifest.

experiments/<name>.yaml::

    name: baselines
    model: qwen2.5:7b-instruct
    adapter: openai_compatible
    adapter_params: {base_url: http://127.0.0.1:11434/v1, max_tokens: 900}
    tasks: [all]            # or a list of task ids; or families: [D_multi_session_study_planning]
    variants: [base]        # or [all]
    seeds: [0]
    max_steps: 25
    conditions:             # each condition overrides RunConfig fields; the condition name is recorded
      chatbot:             {memory_access: none,  tool_profile: none}
      memory_assistant:    {memory_access: full,  tool_profile: none}
      tool_agent:          {memory_access: tools, tool_profile: full}
      full_agent:          {memory_access: full,  tool_profile: full}
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

from ..schema import RunConfig, TaskFamily
from ..tasks import Dataset
from .runner import run_one


def load_experiment(path: str | Path) -> dict[str, Any]:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    data.setdefault("conditions", {"default": {}})
    data.setdefault("variants", ["base"])
    data.setdefault("seeds", [0])
    return data


def plan_runs(exp: dict[str, Any], ds: Dataset) -> list[dict[str, Any]]:
    task_ids: list[str]
    if exp.get("families"):
        task_ids = ds.task_ids([TaskFamily(f) for f in exp["families"]])
    elif exp.get("tasks") in (None, ["all"], "all"):
        task_ids = ds.task_ids()
    else:
        task_ids = list(exp["tasks"])
    runs = []
    for cond, overrides in exp["conditions"].items():
        for tid in task_ids:
            t = ds.load_task(tid)
            vids = ["base", *[v.id for v in t.variants]] if exp["variants"] in (["all"], "all") else list(exp["variants"])
            for vid in vids:
                if vid != "base" and t.variant(vid) is None:
                    continue
                for seed in exp["seeds"]:
                    runs.append({"condition": cond, "task_id": tid, "variant_id": vid, "seed": seed, "overrides": overrides})
    return runs


def run_id_for(exp_name: str, r: dict[str, Any], model: str) -> str:
    m = model.replace("/", "_").replace(":", "-")
    return f"{exp_name}__{r['condition']}__{r['task_id']}__{r['variant_id']}__s{r['seed']}__{m}"


def run_sweep(path: str | Path, *, out_root: str | Path, data_dir: str | None = None, dry_run: bool = False,
              limit: int | None = None, log=print) -> dict[str, Any]:
    exp = load_experiment(path)
    ds = Dataset(data_dir)
    runs = plan_runs(exp, ds)
    out_dir = Path(out_root) / exp["name"]
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = out_dir / "manifest.json"
    manifest: dict[str, Any] = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.is_file() else {"runs": {}}
    manifest["experiment"] = exp
    manifest["planned"] = len(runs)
    manifest["updated_at"] = datetime.now().isoformat()
    done = skipped = failed = 0
    for i, r in enumerate(runs):
        if limit is not None and done >= limit:
            break
        rid = run_id_for(exp["name"], r, exp["model"])
        if (out_dir / rid / "verdict.json").is_file():
            skipped += 1
            continue
        if dry_run:
            log(f"[dry] {rid}")
            continue
        cfg = RunConfig(model=exp["model"], adapter=exp["adapter"], adapter_params=dict(exp.get("adapter_params", {})),
                        max_steps=exp.get("max_steps"), output_dir=str(out_dir), tags=[exp["name"], r["condition"]], condition=r["condition"],
                        temperature=float(exp.get("temperature", 0.0))).model_copy(update=dict(r["overrides"]))
        try:
            res = run_one(ds, r["task_id"], r["variant_id"], cfg, r["seed"], out_root=out_dir, run_id=rid)
            v = res.verdict
            manifest["runs"][rid] = {"condition": r["condition"], "task_id": r["task_id"], "variant_id": r["variant_id"],
                                     "seed": r["seed"], "success": v.task_success, "score": v.score, "max_score": v.max_score,
                                     "status": res.trajectory.status, "attribution": v.failure_attribution}
            log(f"[{i + 1}/{len(runs)}] {rid}: {'SUCCESS' if v.task_success else 'fail'} {v.score:g}/{v.max_score:g} "
                f"status={res.trajectory.status} attr={v.failure_attribution}")
            done += 1
        except Exception as exc:
            failed += 1
            manifest["runs"][rid] = {"condition": r["condition"], "task_id": r["task_id"], "variant_id": r["variant_id"],
                                     "seed": r["seed"], "error": f"{type(exc).__name__}: {exc}"}
            log(f"[{i + 1}/{len(runs)}] {rid}: ERROR {type(exc).__name__}: {exc}")
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return {"planned": len(runs), "done": done, "skipped": skipped, "failed": failed, "out": str(out_dir)}
