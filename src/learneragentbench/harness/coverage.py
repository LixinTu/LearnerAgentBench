"""Coverage matrix: which capabilities, counterfactual conditions, tools and event kinds each
task (and family) exercises — and what is still uncovered."""
from __future__ import annotations

from collections import defaultdict
from typing import Any

from ..schema import Capability, CounterfactualCondition, TaskFamily
from ..tasks import Dataset
from ..verify.base import NON_CAPABILITY_VERIFIERS

FAMILY_SHORT = {f: f.value.split("_", 1)[0] for f in TaskFamily}


def coverage_matrix(ds: Dataset) -> dict[str, Any]:
    tasks: list[dict[str, Any]] = []
    cap_by_family: dict[str, set[str]] = defaultdict(set)
    cond_by_family: dict[str, set[str]] = defaultdict(set)
    personas_by_family: dict[str, set[str]] = defaultdict(set)
    for tid in ds.task_ids():
        t = ds.load_task(tid)
        caps = {c.capability.value for c in t.checks if c.capability and c.verifier not in NON_CAPABILITY_VERIFIERS}
        caps |= {c.capability.value for v in t.variants for c in v.checks_add if c.capability and c.verifier not in NON_CAPABILITY_VERIFIERS}
        conds = {v.condition.value for v in t.variants}
        tools = set(t.available_tools)
        events = {e.event_kind.value for e in t.event_timeline} | {e.event_kind.value for v in t.variants for e in v.patch.events_add}
        personas = {t.persona_id} | {v.patch.persona_id for v in t.variants if v.patch.persona_id}
        fam = FAMILY_SHORT[t.family]
        cap_by_family[fam] |= caps
        cond_by_family[fam] |= conds
        personas_by_family[fam] |= personas
        tasks.append({
            "task_id": tid, "family": fam, "persona": t.persona_id, "personas": sorted(personas),
            "capabilities": sorted(caps), "conditions": sorted(conds), "tools": len(tools), "events": sorted(events),
            "checks": len(t.checks), "hard": sum(1 for c in t.checks if c.hard), "variants": len(t.variants),
            "reference_path": bool(t.reference_path), "negative_cases": len(t.negative_cases),
        })
    all_caps = [c.value for c in Capability]
    all_conds = [c.value for c in CounterfactualCondition if c is not CounterfactualCondition.BASE]
    families = [FAMILY_SHORT[f] for f in TaskFamily]
    gaps = {
        "capabilities": {f: [c for c in all_caps if c not in cap_by_family[f]] for f in families},
        "conditions": {f: [c for c in all_conds if c not in cond_by_family[f]] for f in families},
    }
    return {"tasks": tasks, "families": families, "capabilities": all_caps, "conditions": all_conds,
            "cap_by_family": {f: sorted(v) for f, v in cap_by_family.items()},
            "cond_by_family": {f: sorted(v) for f, v in cond_by_family.items()},
            "personas_by_family": {f: sorted(v) for f, v in personas_by_family.items()},
            "tasks_per_family": {f: sum(1 for t in tasks if t["family"] == f) for f in families},
            "personas": ds.persona_ids(), "gaps": gaps}


def render_markdown(m: dict[str, Any]) -> str:
    out = ["# Coverage matrix", "", f"{len(m['tasks'])} tasks · {len(m['personas'])} personas "
           f"({', '.join(m['personas'])}) · target 60 tasks / 12 personas", ""]
    out.append("## Tasks per family")
    out.append("")
    out.append("| family | tasks | personas used | missing capabilities | missing counterfactual conditions |")
    out.append("|---|---|---|---|---|")
    for f in m["families"]:
        out.append(f"| {f} | {m['tasks_per_family'][f]} | {', '.join(m['personas_by_family'].get(f, [])) or '—'} | "
                   f"{', '.join(m['gaps']['capabilities'][f]) or '—'} | {', '.join(m['gaps']['conditions'][f]) or '—'} |")
    out.append("")
    out.append("## Capability × family (number of tasks whose checks tag the capability)")
    out.append("")
    out.append("| capability | " + " | ".join(m["families"]) + " |")
    out.append("|---|" + "---|" * len(m["families"]))
    for cap in m["capabilities"]:
        row = [str(sum(1 for t in m["tasks"] if t["family"] == f and cap in t["capabilities"])) for f in m["families"]]
        out.append(f"| {cap} | " + " | ".join(row) + " |")
    out.append("")
    out.append("## Counterfactual condition × family (number of tasks with such a variant)")
    out.append("")
    out.append("| condition | " + " | ".join(m["families"]) + " |")
    out.append("|---|" + "---|" * len(m["families"]))
    for cond in m["conditions"]:
        row = [str(sum(1 for t in m["tasks"] if t["family"] == f and cond in t["conditions"])) for f in m["families"]]
        out.append(f"| {cond} | " + " | ".join(row) + " |")
    out.append("")
    out.append("## Per task")
    out.append("")
    out.append("| task | family | persona(s) | checks (hard) | variants | events | ref. path | negative cases | capabilities |")
    out.append("|---|---|---|---|---|---|---|---|---|")
    for t in m["tasks"]:
        out.append(f"| {t['task_id']} | {t['family']} | {', '.join(t['personas'])} | {t['checks']} ({t['hard']}) | {t['variants']} | "
                   f"{', '.join(t['events']) or '—'} | {'yes' if t['reference_path'] else 'family oracle'} | {t['negative_cases']} | "
                   f"{', '.join(c.replace('_', ' ') for c in t['capabilities'])} |")
    return "\n".join(out) + "\n"
