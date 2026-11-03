"""Properties of the dataset as a whole: the release targets, personas that differ in the dimensions the
benchmark claims, tasks that are not relabelled copies, and documentation whose numbers are the real ones."""
from __future__ import annotations

import itertools
import re
from collections import Counter
from pathlib import Path

from learneragentbench.tasks import Dataset

DS = Dataset()
ROOT = Path(__file__).resolve().parents[2]
TASKS = {tid: DS.load_task(tid) for tid in DS.task_ids()}
PERSONAS = {p.stem: DS.load_persona(p.stem) for p in sorted((ROOT / "data" / "personas").glob("*.yaml"))}


def test_release_targets() -> None:
    per_family = Counter(t.family for t in TASKS.values())
    assert len(TASKS) >= 60
    assert len(per_family) == 6
    assert min(per_family.values()) >= 10, per_family
    assert len(PERSONAS) == 12


def _fingerprint(t) -> tuple:
    return (t.family, tuple(sorted(c.verifier for c in t.checks)), tuple(sorted(str(e.event_kind) for e in t.event_timeline)), tuple(sorted(t.available_tools)))


def test_no_task_is_a_relabelled_copy_of_another() -> None:
    """Same family, same verifiers, same events and same tools would be a copy with new names and dates."""
    seen: dict[tuple, str] = {}
    dupes = []
    for tid, t in TASKS.items():
        fp = _fingerprint(t)
        if fp in seen:
            dupes.append((seen[fp], tid))
        seen[fp] = tid
    assert not dupes, dupes
    goals = Counter(t.user_goal.strip() for t in TASKS.values())
    assert [g for g, n in goals.items() if n > 1] == []


def _strategy(p) -> dict:
    keys = {"preferred_block_minutes", "min_block_minutes", "max_block_minutes", "max_skills_per_block", "buffer_hours_before_exam", "hint_policy"}
    return {x["key"]: x["value"] for x in p.preferences if x["key"] in keys}


def test_any_two_personas_differ_in_goals_mastery_strategy_schedule_and_authorization() -> None:
    same = []
    for (a, pa), (b, pb) in itertools.combinations(PERSONAS.items(), 2):
        dims = {"goals": pa.profile["goals"] == pb.profile["goals"],
                "mastery": pa.mastery_defaults == pb.mastery_defaults,
                "strategy": _strategy(pa) == _strategy(pb),
                "schedule": pa.profile["availability"] == pb.profile["availability"],
                "authorization": sorted(str(x) for x in pa.policies) == sorted(str(x) for x in pb.policies)}
        same += [(a, b, dim) for dim, eq in dims.items() if eq]
    assert not same, same


def test_personas_are_exercised_and_most_are_shown_to_change_the_right_answer() -> None:
    used = {t.persona_id for t in TASKS.values()}
    swapped_to = {v.patch.persona_id for t in TASKS.values() for v in t.variants if v.patch.persona_id}
    assert set(PERSONAS) <= used | swapped_to, set(PERSONAS) - used - swapped_to
    # a persona swap is checked against its own rules: it must add or remove checks, never just relabel
    for tid, t in TASKS.items():
        for v in t.variants:
            if v.patch.persona_id:
                assert v.checks_add or v.checks_remove, f"{tid}/{v.id} swaps the persona and leaves every check alone"


def test_dataset_doc_lists_every_task_and_real_counts() -> None:
    doc = (ROOT / "docs" / "DATASET.md").read_text(encoding="utf-8")
    missing = [tid for tid in TASKS if f"`{tid}`" not in doc]
    assert not missing, missing
    n_var = sum(len(t.variants) for t in TASKS.values())
    m = re.search(r"Counts: (\d+) tasks, (\d+) variants, (\d+) oracle-validated runs, (\d+) personas", doc)
    assert m, "the Counts line is missing"
    assert tuple(map(int, m.groups())) == (len(TASKS), n_var, len(TASKS) + n_var, len(PERSONAS))
    for pid in PERSONAS:
        assert f"| `{pid}` |" in doc, pid


def test_every_task_has_the_required_parts() -> None:
    for tid, t in TASKS.items():
        assert t.variants, f"{tid}: no counterfactual variant"
        assert t.negative_cases, f"{tid}: no negative case"
        assert t.hidden_constraints, f"{tid}: no hidden constraints"
        assert any(c.hard for c in t.checks), f"{tid}: no hard check"
        assert t.expected_final_state, f"{tid}: no expected final state"
