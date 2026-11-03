"""Aggregate verdict.json files into tables with bootstrap confidence intervals."""
from __future__ import annotations

import json
import random
from collections import defaultdict
from pathlib import Path
from typing import Any


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
    return [json.loads(p.read_text(encoding="utf-8")) for p in sorted(Path(root).rglob("verdict.json"))]


def summarize_runs(root: str | Path, *, group_by: str = "model,variant_id") -> str:
    verdicts = load_verdicts(root)
    if not verdicts:
        return f"no verdict.json under {root}"
    keys = [k.strip() for k in group_by.split(",") if k.strip()]
    groups: dict[tuple[str, ...], list[dict[str, Any]]] = defaultdict(list)
    for v in verdicts:
        groups[tuple(str(v.get(k, "?")) for k in keys)].append(v)
    lines = [f"{' / '.join(keys):40s} {'n':>4s} {'success':>8s} {'95% CI':>15s} {'score':>7s} {'calls':>6s} {'auth_viol':>9s} {'attribution'}"]
    for key, vs in sorted(groups.items()):
        succ = [1.0 if v["task_success"] else 0.0 for v in vs]
        rate = sum(succ) / len(succ)
        lo, hi = bootstrap_ci(succ)
        score = sum(v["score"] / v["max_score"] if v["max_score"] else 0.0 for v in vs) / len(vs)
        calls = sum(v["tool_call_count"] for v in vs) / len(vs)
        viol = sum(len(v["authorization_violations"]) for v in vs)
        attr: dict[str, int] = defaultdict(int)
        for v in vs:
            attr[v["failure_attribution"]] += 1
        attr_s = ",".join(f"{k}:{n}" for k, n in sorted(attr.items()))
        lines.append(f"{' / '.join(key):40s} {len(vs):4d} {rate:8.2f} [{lo:5.2f},{hi:5.2f}] {score:7.2f} {calls:6.1f} {viol:9d} {attr_s}")
    caps: dict[str, list[float]] = defaultdict(list)
    for v in verdicts:
        for cap, val in v.get("capability_scores", {}).items():
            caps[cap].append(val)
    if caps:
        lines.append("")
        lines.append("capability scores (mean over runs that have the capability tagged):")
        for cap, vals in sorted(caps.items()):
            lines.append(f"  {cap:32s} {sum(vals) / len(vals):5.2f}  (n={len(vals)})")
    return "\n".join(lines)
