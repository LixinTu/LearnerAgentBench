"""`lab sweep` plans a (condition × task × variant × seed) grid; a condition may restrict its own
variants so an experiment file does not re-run configurations another sweep already covers."""
from __future__ import annotations

from learneragentbench.harness.sweep import load_experiment, plan_runs, run_id_for
from learneragentbench.tasks import Dataset

EXP = {"name": "x", "model": "m", "adapter": "oracle", "tasks": ["D01_midterm_plan_from_rules", "E02_calendar_tool_outage"],
       "variants": ["base"], "seeds": [0, 1]}


def test_grid_and_run_ids() -> None:
    ds = Dataset()
    exp = {**EXP, "conditions": {"a": {"tool_profile": "full"}, "b": {"tool_profile": "read_only"}}}
    runs = plan_runs(exp, ds)
    assert len(runs) == 2 * 2 * 1 * 2
    assert {r["condition"] for r in runs} == {"a", "b"}
    assert all(r["variant_id"] == "base" for r in runs)
    assert runs[0]["overrides"] == {"tool_profile": "full"}
    ids = [run_id_for("x", r, "qwen2.5:7b") for r in runs]
    assert len(set(ids)) == len(ids)
    assert ids[0] == "x__a__D01_midterm_plan_from_rules__base__s0__qwen2.5-7b"


def test_condition_can_name_its_own_variants_and_the_key_is_not_an_override() -> None:
    ds = Dataset()
    exp = {**EXP, "conditions": {"read_only": {"tool_profile": "read_only", "variants": ["base"]},
                                 "full_tools": {"tool_profile": "full", "variants": ["never_restored", "no_such_variant"]}}}
    runs = plan_runs(exp, ds)
    ro = [r for r in runs if r["condition"] == "read_only"]
    ft = [r for r in runs if r["condition"] == "full_tools"]
    assert {r["variant_id"] for r in ro} == {"base"} and len(ro) == 4
    # never_restored exists only on E02; unknown variants are skipped, not planned
    assert [(r["task_id"], r["variant_id"], r["seed"]) for r in ft] == [("E02_calendar_tool_outage", "never_restored", 0),
                                                                        ("E02_calendar_tool_outage", "never_restored", 1)]
    assert all("variants" not in r["overrides"] for r in runs)
    assert ft[0]["overrides"] == {"tool_profile": "full"}


def test_all_variants_expands_per_task(tmp_path) -> None:
    ds = Dataset()
    exp = {**EXP, "tasks": ["E02_calendar_tool_outage"], "variants": "all", "seeds": [0], "conditions": {"c": {}}}
    runs = plan_runs(exp, ds)
    assert runs[0]["variant_id"] == "base"
    assert {r["variant_id"] for r in runs} == {"base", *[v.id for v in ds.load_task("E02_calendar_tool_outage").variants]}
    no_base = plan_runs({**exp, "exclude_base": True}, ds)
    assert no_base and "base" not in {r["variant_id"] for r in no_base}
    assert {r["variant_id"] for r in no_base} == {r["variant_id"] for r in runs} - {"base"}
    # load_experiment fills the defaults a file may omit
    f = tmp_path / "e.yaml"
    f.write_text("name: y\nmodel: m\nadapter: oracle\ntasks: [E02_calendar_tool_outage]\n", encoding="utf-8")
    loaded = load_experiment(f)
    assert loaded["variants"] == ["base"] and loaded["seeds"] == [0] and loaded["conditions"] == {"default": {}}
