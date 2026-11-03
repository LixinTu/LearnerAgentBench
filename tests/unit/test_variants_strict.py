"""A variant patch that names a memory id which does not exist must fail loudly: a stale id would
otherwise turn the counterfactual into a silent no-op (found in D04's standing_rule_instead variant,
whose memory_remove had pointed at an id that no longer existed)."""
from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from learneragentbench.env.seed import build_world
from learneragentbench.env.world import NotFoundError
from learneragentbench.schema import CounterfactualCondition, MemoryEntry, StatePatch
from learneragentbench.tasks import Dataset
from learneragentbench.tasks.variants import apply_patch

DS = Dataset()


def _world(tid: str, tmp: Path):
    task = DS.load_task(tid)
    persona = DS.load_persona(task.persona_id)
    graph = DS.load_graph(task.initial_state.skill_graph or "algebra")
    return build_world(task.initial_state, persona, graph, task_memory=task.memory, path=tmp / "w.db", task_id=tid)


def test_unknown_memory_id_in_patch_raises() -> None:
    with tempfile.TemporaryDirectory() as d:
        world = _world("D04_one_off_versus_standing_rule", Path(d))
        with pytest.raises(NotFoundError, match="mem_nope"):
            apply_patch(world, StatePatch(memory_remove=["mem_nope"]), condition=CounterfactualCondition.OUTDATED_MEMORY)


def test_known_memory_id_is_removed_and_no_memory_tolerates_stale_ids() -> None:
    with tempfile.TemporaryDirectory() as d:
        world = _world("D04_one_off_versus_standing_rule", Path(d))
        one_off = next(m for m in world.list(MemoryEntry) if m.memory_kind.value == "one_off")
        log = apply_patch(world, StatePatch(memory_remove=[one_off.id]), condition=CounterfactualCondition.OUTDATED_MEMORY)
        assert f"removed memory {one_off.id}" in log
        assert world.get(MemoryEntry, one_off.id) is None
    with tempfile.TemporaryDirectory() as d:
        world = _world("D04_one_off_versus_standing_rule", Path(d))
        # under no_memory every entry is already gone; an id in the patch is not an error there
        apply_patch(world, StatePatch(memory_remove=["mem_nope"]), condition=CounterfactualCondition.NO_MEMORY)
        assert world.list(MemoryEntry) == []


def test_every_dataset_variant_patch_names_existing_memories() -> None:
    bad = []
    for tid in DS.task_ids():
        task = DS.load_task(tid)
        for v in task.variants:
            if not (v.patch.memory_remove or v.patch.memory_replace):
                continue
            with tempfile.TemporaryDirectory() as d:
                world = _world(tid, Path(d))
                try:
                    apply_patch(world, v.patch, condition=v.condition)
                except NotFoundError as exc:
                    bad.append(f"{tid}/{v.id}: {exc}")
    assert not bad, "\n".join(bad)
