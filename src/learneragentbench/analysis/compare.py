"""Paired comparison of two run sets: the same tasks (and seeds) under two configurations.

Conditions in this benchmark differ by less than the run-to-run noise of a single episode, so the
only comparison that means anything is paired by task, averaged over the task's seeds, with a
bootstrap interval over tasks. ``compare_runs`` does exactly that for two run roots (which may be
the same root with different filters, e.g. two conditions of one sweep), and lists the checks that
one side passes and the other fails.
"""
from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any

from .summary import bootstrap_ci, load_verdicts

Filter = dict[str, str]


def parse_filter(text: str | None) -> Filter:
    """``"condition=tool_agent,variant_id=base"`` → ``{"condition": "tool_agent", "variant_id": "base"}``."""
    out: Filter = {}
    for part in (text or "").split(","):
        part = part.strip()
        if not part:
            continue
        if "=" not in part:
            raise ValueError(f"filter {part!r} is not key=value")
        k, v = part.split("=", 1)
        out[k.strip()] = v.strip()
    return out


def _select(verdicts: list[dict[str, Any]], flt: Filter) -> list[dict[str, Any]]:
    return [v for v in verdicts if all(str(v.get(k, "?")) == val for k, val in flt.items())]


def _keyed(verdicts: list[dict[str, Any]], pair_on: tuple[str, ...], side: str) -> dict[tuple[str, ...], dict[str, Any]]:
    keyed: dict[tuple[str, ...], dict[str, Any]] = {}
    for v in verdicts:
        key = tuple(str(v.get(k, "?")) for k in pair_on)
        if key in keyed:
            raise ValueError(f"side {side}: more than one run for {dict(zip(pair_on, key, strict=True))}; narrow it with a filter "
                             f"(e.g. condition=..., variant_id=...) or pair on more fields")
        keyed[key] = v
    return keyed


def _frac(v: dict[str, Any]) -> float:
    return v["score"] / v["max_score"] if v["max_score"] else 0.0


def _mean(xs: list[float]) -> float:
    return sum(xs) / len(xs) if xs else float("nan")


def _common_fracs(x: dict[str, Any], y: dict[str, Any]) -> tuple[float, float] | None:
    """Score fractions of two runs restricted to the checks both were judged on. A variant may add or remove
    checks, and then the plain fractions do not compare like with like."""
    cx = {c["check_id"]: c for c in x.get("checks", []) if c.get("passed") is not None}
    cy = {c["check_id"]: c for c in y.get("checks", []) if c.get("passed") is not None}
    ids = set(cx) & set(cy)
    if not ids:
        return None
    def frac(cs: dict[str, dict[str, Any]]) -> float:
        total = sum(float(cs[k].get("weight", 1.0)) for k in ids)
        return sum(float(cs[k].get("weight", 1.0)) for k in ids if cs[k]["passed"]) / total if total else 0.0
    return frac(cx), frac(cy)


def compare_runs(root_a: str | Path, root_b: str | Path, *, filter_a: Filter | None = None, filter_b: Filter | None = None,
                 pair_on: str = "task_id,seed", label_a: str = "A", label_b: str = "B") -> str:
    keys = tuple(k.strip() for k in pair_on.split(",") if k.strip())
    if "task_id" not in keys:
        raise ValueError("pair_on must include task_id")
    a = _keyed(_select(load_verdicts(root_a), filter_a or {}), keys, label_a)
    b = _keyed(_select(load_verdicts(root_b), filter_b or {}), keys, label_b)
    common = sorted(set(a) & set(b))
    if not common:
        return (f"no pairs: {len(a)} runs on side {label_a} ({root_a} {filter_a or ''}), {len(b)} on side {label_b} "
                f"({root_b} {filter_b or ''}), nothing in common on {keys}")
    ti = keys.index("task_id")
    per_task: dict[str, list[tuple[dict[str, Any], dict[str, Any]]]] = defaultdict(list)
    for key in common:
        per_task[key[ti]].append((a[key], b[key]))

    rows = []
    deltas = []
    for task, pairs in sorted(per_task.items()):
        fa = _mean([_frac(x) for x, _ in pairs])
        fb = _mean([_frac(y) for _, y in pairs])
        sa = _mean([1.0 if x["task_success"] else 0.0 for x, _ in pairs])
        sb = _mean([1.0 if y["task_success"] else 0.0 for _, y in pairs])
        ha = _mean([float(len(x.get("hard_failures", []))) for x, _ in pairs])
        hb = _mean([float(len(y.get("hard_failures", []))) for _, y in pairs])
        ca = _mean([float(x["tool_call_count"]) for x, _ in pairs])
        cb = _mean([float(y["tool_call_count"]) for _, y in pairs])
        ia = _mean([float(len(x.get("invalid_actions", []))) for x, _ in pairs])
        ib = _mean([float(len(y.get("invalid_actions", []))) for _, y in pairs])
        deltas.append(fb - fa)
        rows.append((task, len(pairs), fa, fb, fb - fa, sa, sb, ha, hb, ca, cb, ia, ib))

    shared: dict[str, list[tuple[float, float]]] = defaultdict(list)
    for task, pairs in per_task.items():
        for x, y in pairs:
            if (f := _common_fracs(x, y)) is not None:
                shared[task].append(f)
    shared_a = {t: _mean([a for a, _ in fs]) for t, fs in shared.items()}
    shared_b = {t: _mean([b for _, b in fs]) for t, fs in shared.items()}
    shared_d = [shared_b[t] - shared_a[t] for t in shared]
    clo, chi = bootstrap_ci(shared_d)

    lo, hi = bootstrap_ci(deltas)
    better = sum(1 for d in deltas if d > 0.005)
    worse = sum(1 for d in deltas if d < -0.005)
    same = len(deltas) - better - worse
    lines = [f"paired on {','.join(keys)}: {len(common)} pairs over {len(per_task)} tasks; "
             f"{label_a} = {root_a} {filter_a or ''}; {label_b} = {root_b} {filter_b or ''}",
             f"score fraction (task means): {label_a} {_mean([r[2] for r in rows]):.3f}  {label_b} {_mean([r[3] for r in rows]):.3f}  "
             f"{label_b}-{label_a} {_mean(deltas):+.3f} [95% CI {lo:+.3f}, {hi:+.3f}]  tasks better/worse/same: {better}/{worse}/{same}",
             f"success rate: {label_a} {_mean([r[5] for r in rows]):.3f}  {label_b} {_mean([r[6] for r in rows]):.3f}   "
             f"hard failures per run: {_mean([r[7] for r in rows]):.2f} → {_mean([r[8] for r in rows]):.2f}   "
             f"tool calls: {_mean([r[9] for r in rows]):.1f} → {_mean([r[10] for r in rows]):.1f}   "
             f"invalid calls: {_mean([r[11] for r in rows]):.1f} → {_mean([r[12] for r in rows]):.1f}",
             f"on the checks both sides share: {label_a} {_mean(list(shared_a.values())):.3f}  {label_b} {_mean(list(shared_b.values())):.3f}  "
             f"{label_b}-{label_a} {_mean(shared_d):+.3f} [95% CI {clo:+.3f}, {chi:+.3f}]",
             "",
             f"{'task':46s} {'n':>2s} {label_a:>6s} {label_b:>6s} {'delta':>7s} {'hard':>9s} {'calls':>11s} {'invalid':>9s}"]
    for task, n, fa, fb, d, _sa, _sb, ha, hb, ca, cb, ia, ib in rows:
        lines.append(f"{task:46s} {n:2d} {fa:6.2f} {fb:6.2f} {d:+7.2f} {ha:4.1f}→{hb:<4.1f} {ca:5.1f}→{cb:<5.1f} {ia:4.1f}→{ib:<4.1f}")

    # Check-level flips: pass fraction over the task's seeds on each side.
    gained: list[str] = []
    lost: list[str] = []
    for task, pairs in sorted(per_task.items()):
        ids = [c["check_id"] for c in pairs[0][0].get("checks", [])]
        for cid in ids:
            pa = [c["passed"] for x, _ in pairs for c in x.get("checks", []) if c["check_id"] == cid]
            pb = [c["passed"] for _, y in pairs for c in y.get("checks", []) if c["check_id"] == cid]
            if not pa or not pb:
                continue
            ra, rb = sum(1 for p in pa if p) / len(pa), sum(1 for p in pb if p) / len(pb)
            if ra == 1.0 and rb == 0.0:
                lost.append(f"{task[:3]}:{cid}")
            elif ra == 0.0 and rb == 1.0:
                gained.append(f"{task[:3]}:{cid}")
    lines.append("")
    lines.append(f"checks passed by {label_a} in every seed and by {label_b} in none ({len(lost)}): {', '.join(lost) or '—'}")
    lines.append(f"checks passed by {label_b} in every seed and by {label_a} in none ({len(gained)}): {', '.join(gained) or '—'}")
    return "\n".join(lines)
