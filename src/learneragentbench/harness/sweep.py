"""Batch experiments from a YAML config: a grid of (condition × task × variant × seed) runs
with resumable, skip-if-done semantics and a manifest.

experiments/<name>.yaml::

    name: baselines
    model: qwen2.5:7b-instruct
    adapter: openai_compatible
    adapter_params: {base_url: http://127.0.0.1:11434/v1, max_tokens: 900}
    tasks: [all]            # or a list of task ids; or families: [D_multi_session_study_planning]
    variants: [base]        # or [all]; with `exclude_base: true`, every variant except the base rows
    seeds: [0]
    max_steps: 25
    conditions:             # each condition overrides RunConfig fields; the condition name is recorded;
                            # a condition may restrict its own `variants: [...]` (not a RunConfig field)
      chatbot:             {memory_access: none,  tool_profile: none}
      memory_assistant:    {memory_access: full,  tool_profile: none}
      tool_agent:          {memory_access: tools, tool_profile: full}
      full_agent:          {memory_access: full,  tool_profile: full}
"""
from __future__ import annotations

import json
import shutil
import subprocess
import urllib.request
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
    for cond, spec in exp["conditions"].items():
        # A condition may name its own `variants`; every other key is a RunConfig override.
        overrides = {k: v for k, v in spec.items() if k != "variants"}
        wanted = spec.get("variants", exp["variants"])
        for tid in task_ids:
            t = ds.load_task(tid)
            vids = ["base", *[v.id for v in t.variants]] if wanted in (["all"], "all") else list(wanted)
            if exp.get("exclude_base"):
                vids = [v for v in vids if v != "base"]
            for vid in vids:
                if vid != "base" and t.variant(vid) is None:
                    continue
                for seed in exp["seeds"]:
                    runs.append({"condition": cond, "task_id": tid, "variant_id": vid, "seed": seed, "overrides": overrides})
    return runs


def run_id_for(exp_name: str, r: dict[str, Any], model: str) -> str:
    m = model.replace("/", "_").replace(":", "-")
    return f"{exp_name}__{r['condition']}__{r['task_id']}__{r['variant_id']}__s{r['seed']}__{m}"


def _git(*args: str) -> str | None:
    try:
        out = subprocess.run(["git", *args], capture_output=True, text=True, timeout=10, check=True)
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout.strip()


def _ollama_digest(base_url: str | None, model: str) -> str | None:
    """The model's content digest from an Ollama server, so "the same tag" can be told from "the same
    weights". Best effort: any other server (or none) leaves it unknown and the sweep goes on."""
    if not base_url:
        return None
    root = base_url.rstrip("/").removesuffix("/v1")
    try:
        with urllib.request.urlopen(f"{root}/api/tags", timeout=5) as resp:
            tags = json.loads(resp.read().decode("utf-8"))
    except (OSError, ValueError):
        return None
    return next((m.get("digest") for m in tags.get("models", []) if m.get("name") == model), None)


def provenance(exp: dict[str, Any]) -> dict[str, Any]:
    """What this invocation of the sweep ran with. A resumed sweep appends a second entry, so a run set
    produced across a code change shows it."""
    return {"started_at": datetime.now().isoformat(), "git_commit": _git("rev-parse", "HEAD"),
            "git_dirty": bool(_git("status", "--porcelain")), "model": exp["model"],
            "model_digest": _ollama_digest(exp.get("adapter_params", {}).get("base_url"), exp["model"])}


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
    if not dry_run:
        manifest.setdefault("provenance", []).append(provenance(exp))
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
        partial = out_dir / rid
        if partial.exists():
            # A run that was interrupted has a world database but no verdict. Starting over on top of that database
            # would collide with its records, so an unfinished run of this sweep is removed and run again.
            shutil.rmtree(partial)
            log(f"[{i + 1}/{len(runs)}] {rid}: removed an unfinished earlier attempt")
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
