"""Aggregate verdict.json files into tables with bootstrap confidence intervals."""
from __future__ import annotations

import json
import random
import shutil
import tempfile
from collections import defaultdict
from pathlib import Path
from typing import Any

from ..verify.base import NON_CAPABILITY_VERIFIERS


def bootstrap_ci(values: list[float], *, n_boot: int = 2000, alpha: float = 0.05, seed: int = 0) -> tuple[float, float]:
    if not values:
        return (float("nan"), float("nan"))
    rng = random.Random(seed)
    means = []
    for _ in range(n_boot):
        sample = [values[rng.randrange(len(values))] for _ in values]
        means.append(sum(sample) / len(sample))
    means.sort()
    lo = means[int(alpha / 2 * n_boot)]
    hi = means[min(n_boot - 1, int((1 - alpha / 2) * n_boot))]
    return (lo, hi)


def load_verdicts(root: str | Path) -> list[dict[str, Any]]:
    """Every verdict under ``root``, each enriched with its run's sidecar metadata (experiment
    condition, task family, memory/tool settings) so tables can group by them."""
    out = []
    for p in sorted(Path(root).rglob("verdict.json")):
        v = json.loads(p.read_text(encoding="utf-8"))
        for k, val in _sidecar(p.parent).items():
            v.setdefault(k, val)
        out.append(v)
    return out


def _sidecar(run_dir: Path) -> dict[str, Any]:
    meta: dict[str, Any] = {}
    cfg_path, task_path = run_dir / "config.json", run_dir / "task_effective.json"
    if cfg_path.exists():
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        tags = cfg.get("tags") or []
        meta["condition"] = cfg.get("condition") or (tags[1] if len(tags) > 1 else "default")
        meta["experiment"] = tags[0] if tags else "?"
        for k in ("memory_access", "tool_profile", "adapter", "max_steps"):
            if k in cfg:
                meta[k] = cfg[k]
    if task_path.exists():
        meta["family"] = json.loads(task_path.read_text(encoding="utf-8")).get("family", "?")
    return meta


def capability_scores_of(verdict: dict[str, Any]) -> dict[str, float]:
    """Per-capability score of a stored verdict, recomputed from its checks so that a run scored before a
    change of definition reads the same as a new one. Falls back to the stored numbers if it has no checks."""
    checks = verdict.get("checks") or []
    if not checks:
        return dict(verdict.get("capability_scores", {}))
    earned: dict[str, float] = defaultdict(float)
    total: dict[str, float] = defaultdict(float)
    for c in checks:
        if not c.get("capability") or c.get("passed") is None or c.get("verifier") in NON_CAPABILITY_VERIFIERS:
            continue
        total[c["capability"]] += float(c.get("weight", 1.0))
        earned[c["capability"]] += float(c.get("weight", 1.0)) if c["passed"] else 0.0
    return {k: round(earned[k] / w, 3) for k, w in total.items() if w}


PASSIVE_REPLY = "I had a look; nothing to do."


def passive_floor(task_id: str, variant_id: str, data_dir: str | None = None, *, _cache: dict[tuple[str, str, str | None], float | None] = {}) -> float | None:  # noqa: B006
    """The score fraction of an agent that reads nothing and writes nothing on this task and variant: what the task
    gives away for free. Deterministic, no model involved, and never a model result. None if the variant is gone."""
    key = (task_id, variant_id, data_dir)
    if key not in _cache:
        from ..harness import run_one
        from ..runtime import ActionListAdapter
        from ..schema import Action, RunConfig
        from ..tasks import Dataset
        ds = Dataset(data_dir)
        known = ["base", *[v.id for v in ds.load_task(task_id).variants]]
        if variant_id not in known:
            _cache[key] = None
        else:
            with tempfile.TemporaryDirectory() as d:
                v = run_one(ds, task_id, variant_id, RunConfig(model="passive", adapter="scripted", output_dir=d), 0, out_root=d,
                            adapter_factory=lambda c, t, w, e: ActionListAdapter([Action.final(PASSIVE_REPLY)])).verdict
            _cache[key] = v.score / v.max_score if v.max_score else 0.0
    return _cache[key]


def collect_runs(out: str | Path, sources: list[str | Path], *, where: dict[str, str] | None = None, where_not: dict[str, str] | None = None) -> int:
    """Copy the scoring files of selected runs into one run set, e.g. a baseline made of several sweeps. Trajectories and
    worlds stay where they are. A run id that is already there is an error, so nothing can be counted twice."""
    out = Path(out)
    n = 0
    for root in sources:
        for p in sorted(Path(root).rglob("verdict.json")):
            v = json.loads(p.read_text(encoding="utf-8"))
            for k, val in _sidecar(p.parent).items():
                v.setdefault(k, val)
            if any(str(v.get(k, "?")) != val for k, val in (where or {}).items()):
                continue
            if any(str(v.get(k, "?")) == val for k, val in (where_not or {}).items()):
                continue
            dest = out / p.parent.name
            if dest.exists():
                raise ValueError(f"{dest} already exists: this run was collected before")
            dest.mkdir(parents=True)
            for name in ("verdict.json", "config.json", "task_effective.json"):
                if (p.parent / name).is_file():
                    shutil.copy2(p.parent / name, dest / name)
            n += 1
    return n


def summarize_runs(root: str | Path, *, group_by: str = "model,variant_id", floor: bool = False, data_dir: str | None = None) -> str:
    verdicts = load_verdicts(root)
    if not verdicts:
        return f"no verdict.json under {root}"
    keys = [k.strip() for k in group_by.split(",") if k.strip()]
    groups: dict[tuple[str, ...], list[dict[str, Any]]] = defaultdict(list)
    for v in verdicts:
        groups[tuple(str(v.get(k, "?")) for k in keys)].append(v)
    lines = [f"{' / '.join(keys):40s} {'n':>4s} {'success':>8s} {'95% CI':>15s} {'score':>7s} {'calls':>6s} "
             f"{'0calls':>6s} {'hard':>5s} {'auth_viol':>9s} {'attribution'}" + (f" {'floor':>6s} {'above':>6s}" if floor else "")]
    for key, vs in sorted(groups.items()):
        succ = [1.0 if v["task_success"] else 0.0 for v in vs]
        rate = sum(succ) / len(succ)
        lo, hi = bootstrap_ci(succ)
        score = sum(v["score"] / v["max_score"] if v["max_score"] else 0.0 for v in vs) / len(vs)
        calls = sum(v["tool_call_count"] for v in vs) / len(vs)
        no_calls = sum(1 for v in vs if v["tool_call_count"] == 0)
        hard = sum(1 for v in vs if v.get("hard_failures"))
        viol = sum(len(v["authorization_violations"]) for v in vs)
        attr: dict[str, int] = defaultdict(int)
        for v in vs:
            attr[v["failure_attribution"]] += 1
        attr_s = ",".join(f"{k}:{n}" for k, n in sorted(attr.items()))
        row = (f"{' / '.join(key):40s} {len(vs):4d} {rate:8.2f} [{lo:5.2f},{hi:5.2f}] {score:7.2f} {calls:6.1f} "
               f"{no_calls:6d} {hard:5d} {viol:9d} {attr_s}")
        if floor:
            floors = [f for f in (passive_floor(v["task_id"], v["variant_id"], data_dir) for v in vs) if f is not None]
            base = sum(floors) / len(floors) if floors else float("nan")
            row += f" {base:6.2f} {score - base:+6.2f}"
        lines.append(row)
    caps: dict[str, list[float]] = defaultdict(list)
    for v in verdicts:
        for cap, val in capability_scores_of(v).items():
            caps[cap].append(val)
    if caps:
        lines.append("")
        lines.append("capability scores (mean over runs that have the capability tagged):")
        for cap, vals in sorted(caps.items()):
            lines.append(f"  {cap:32s} {sum(vals) / len(vals):5.2f}  (n={len(vals)})")
    return "\n".join(lines)
