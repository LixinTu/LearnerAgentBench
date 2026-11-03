"""Apply a counterfactual variant to a task: the result is an *effective* TaskSpec plus the
state patch to run against the world after it is built. Variants are first-class so that a
base run and its counterfactuals share everything except the named difference."""
from __future__ import annotations

from datetime import timedelta
from typing import Any

from ..env.world import NotFoundError, World
from ..schema import (
    RECORD_TYPES,
    AuthorizationPolicy,
    CounterfactualCondition,
    MemoryEntry,
    PermissionLevel,
    Preference,
    SimulatedUserSpec,
    StatePatch,
    TaskSpec,
    VariantSpec,
    new_id,
)


def base_variant(task: TaskSpec) -> VariantSpec:
    return VariantSpec(id="base", condition=CounterfactualCondition.BASE, description="the task as written")


def resolve_variant(task: TaskSpec, variant_id: str) -> VariantSpec:
    if variant_id == "base":
        return base_variant(task)
    v = task.variant(variant_id)
    if v is None:
        raise KeyError(f"task {task.task_id} has no variant {variant_id!r}; has {[x.id for x in task.variants]}")
    return v


def effective_task(task: TaskSpec, variant: VariantSpec) -> TaskSpec:
    """The task as the harness sees it under this variant (persona, goal, tools, events, checks)."""
    p = variant.patch
    update: dict[str, Any] = {}
    if p.persona_id:
        update["persona_id"] = p.persona_id
    if p.user_goal:
        update["user_goal"] = p.user_goal
    tools = [t for t in task.available_tools if t not in p.tools_remove]
    tools += [t for t in p.tools_add if t not in tools]
    update["available_tools"] = tools
    events = [e for e in task.event_timeline if e.id not in p.events_remove] + list(p.events_add)
    update["event_timeline"] = events
    history = [h for h in task.history if h.session_id not in p.history_remove_sessions]
    update["history"] = history
    checks = [c for c in task.checks if c.id not in variant.checks_remove] + list(variant.checks_add)
    update["checks"] = checks
    if p.simulated_user is not None:
        # re-validate: a plain dict patch must become ApprovalRule / ClarificationRule models
        merged = {**task.simulated_user.model_dump(mode="json"), **p.simulated_user}
        update["simulated_user"] = SimulatedUserSpec.model_validate(merged)
    if variant.reference_path is not None:
        update["reference_path"] = list(variant.reference_path)
    update["negative_cases"] = [n for n in task.negative_cases if n.variant == variant.id]
    if variant.condition == CounterfactualCondition.NO_MEMORY:
        update["history"] = []
        update["memory"] = []
    return task.model_copy(update=update)


def apply_patch(world: World, patch: StatePatch, *, condition: CounterfactualCondition, run_seed_text: str = "") -> list[str]:
    """Mutate a freshly built world according to the patch. Returns a log of what changed."""
    log: list[str] = []
    now = world.now
    if condition == CounterfactualCondition.NO_MEMORY:
        for m in world.memory(active_only=False):
            world.remove(MemoryEntry, m.id)
        for pref in world.preferences(active_only=False):
            world.remove(Preference, pref.id)
        log.append("removed all memory entries and stated preferences (no_memory)")
    for mid in patch.memory_remove:
        # A patch that names a memory which is not there is an authoring error (a stale id would
        # otherwise turn the variant into a silent no-op), except under no_memory, where it is gone already.
        if world.get(MemoryEntry, mid) is None:
            if condition == CounterfactualCondition.NO_MEMORY:
                continue
            raise NotFoundError(f"variant patch removes memory {mid!r}, which does not exist in this world "
                                f"(known ids: {[m.id for m in world.memory(active_only=False)]})")
        world.remove(MemoryEntry, mid)
        log.append(f"removed memory {mid}")
    for i, m in enumerate(patch.memory_add):
        f = dict(m)
        f.setdefault("id", new_id("mem", f"{run_seed_text}|variant|{i}|{f.get('text', '')[:40]}"))
        f.setdefault("stated_at", now - timedelta(days=1))
        world.add(MemoryEntry(created_at=now, updated_at=now, **f))
        log.append(f"added memory {f['id']}")
    for m in patch.memory_replace:
        old = world.require(MemoryEntry, m["id"])
        world.patch(old, {k: v for k, v in m.items() if k != "id"})
        log.append(f"replaced memory {m['id']}")
    for key in patch.preference_remove:
        for pref in world.preferences(key=key):
            world.update(pref.model_copy(update={"active": False}))
            log.append(f"deactivated preference {key} ({pref.scope})")
    for i, pf in enumerate(patch.preference_set):
        f = dict(pf)
        scope = f.get("scope", "global")
        for old in world.preferences(key=f["key"]):
            if old.scope == scope:
                world.update(old.model_copy(update={"active": False}))
        f.setdefault("id", new_id("pref", f"{run_seed_text}|variant|{f['key']}|{scope}|{i}"))
        f.setdefault("stated_at", now - timedelta(hours=1))
        world.add(Preference(created_at=now, updated_at=now, **f))
        log.append(f"set preference {f['key']}={f['value']!r} ({scope})")
    for rid in patch.records_remove:
        kind, _, rec_id = rid.partition("/")
        world.remove(RECORD_TYPES[kind], rec_id)
        log.append(f"removed {rid}")
    for upd in patch.records_update:
        cls = RECORD_TYPES[upd["kind"]]
        rec = world.require(cls, upd["id"])
        world.patch(rec, upd["fields"])
        log.append(f"updated {upd['kind']}/{upd['id']}")
    for i, seed in enumerate(patch.records_add):
        cls = RECORD_TYPES[seed["kind"]]
        fields = dict(seed["fields"])
        fields.setdefault("id", new_id(seed["kind"][:4], f"{run_seed_text}|variant|{i}"))
        if seed["kind"] == "auth_policy":
            fields["level"] = PermissionLevel(fields["level"])
            fields.setdefault("granted_at", now)
            world.add(AuthorizationPolicy(created_at=now, updated_at=now, **fields))
        else:
            world.add(cls(created_at=now, updated_at=now, **fields))
        log.append(f"added {seed['kind']}/{fields['id']}")
    return log
