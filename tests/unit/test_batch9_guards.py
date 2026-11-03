"""Guards added while taking the dataset past 60 tasks: a counterfactual can move the hidden mastery; a
new rule may be kept as a preference or as a note; a wrong answer must not be confirmed; a sweep records
which code and which weights produced it."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from learneragentbench.env import World, build_world
from learneragentbench.env.store import NotFoundError
from learneragentbench.harness import sweep
from learneragentbench.runtime import ActionListAdapter, AgentLoop, RunSpec
from learneragentbench.schema import Action, CheckSpec, CounterfactualCondition, StatePatch
from learneragentbench.tasks import Dataset, apply_patch, resolve_variant
from learneragentbench.tools import REGISTRY, ToolContext, ToolExecutor
from learneragentbench.verify import VerifyContext, run_checks

DS = Dataset()
TASK = "D01_midterm_plan_from_rules"


def _world():
    t = DS.load_task(TASK)
    return t, build_world(t.initial_state, DS.load_persona(t.persona_id), DS.load_graph(t.initial_state.skill_graph or "algebra"), task_id=t.task_id)


def _run(actions: list[Action], checks: list[CheckSpec], tmp_path: Path, task_id: str = TASK):
    t = DS.load_task(task_id).model_copy(update={"checks": checks})
    w = build_world(t.initial_state, DS.load_persona(t.persona_id), DS.load_graph(t.initial_state.skill_graph or "algebra"), task_id=t.task_id)
    init = w.snapshot_bytes()
    ex = ToolExecutor(REGISTRY, ToolContext(w, run_id="r", allowed_tools=REGISTRY.names()))
    spec = RunSpec(run_id="r", task_id=t.task_id, persona_id=t.persona_id, model="m", adapter="a", user_goal=t.user_goal,
                   allowed_tools=REGISTRY.names(), max_steps=20)
    traj = AgentLoop(w, ex, ActionListAdapter(actions), spec, tmp_path).run()
    initial = World.new(w.now)
    initial.restore_bytes(init)
    return run_checks(VerifyContext(world=w, initial_world=initial, trajectory=traj, task=t, variant=resolve_variant(t, "base")))


def test_patch_sets_mastery_and_rejects_unknown_skills() -> None:
    _, w = _world()
    log = apply_patch(w, StatePatch(mastery_set={"systems": 0.91}), condition=CounterfactualCondition.CORRECT_MEMORY)
    assert w.mastery()["systems"].mastery == pytest.approx(0.91) and "set mastery systems=0.91" in log
    _, w2 = _world()
    with pytest.raises(NotFoundError, match="no_such_skill"):
        apply_patch(w2, StatePatch(mastery_set={"no_such_skill": 0.5}), condition=CounterfactualCondition.CORRECT_MEMORY)


def test_preference_recorded_accepts_membership_or_a_note(tmp_path: Path) -> None:
    check = CheckSpec(id="kept", description="", verifier="preference.recorded",
                      params={"key": "rest_weekdays", "contains": 4, "or_memory_contains": ["friday"]})
    assert _run([Action.final("nothing")], [check], tmp_path / "a").checks[0].passed is False
    as_pref = [Action.call("update_preference", key="rest_weekdays", value=[4, 6], scope="global"), Action.final("kept")]
    assert _run(as_pref, [check], tmp_path / "b").checks[0].passed is True
    as_note = [Action.call("record_memory", text="From now on no study on Fridays.", memory_kind="standing_rule"), Action.final("kept")]
    assert _run(as_note, [check], tmp_path / "c").checks[0].passed is True
    # a note about something else does not count, and neither do the notes the world started with
    other = [Action.call("record_memory", text="She prefers mornings.", memory_kind="standing_rule"), Action.final("kept")]
    assert _run(other, [check], tmp_path / "d").checks[0].passed is False
    exact = CheckSpec(id="exact", description="", verifier="preference.recorded", params={"key": "rest_weekdays", "value": [4, 6]})
    assert _run(as_pref, [exact], tmp_path / "e").checks[0].passed is True


PROBLEMS = {"P1": {"answer": [r"\bx\s*=\s*5\b"], "intermediate": [r"\b15\b"], "procedural": [r"subtract[^.\n]{0,20}\b4\b"], "conceptual": [r"\bcheck\b"], "steps": [r"\b15\b"]}}
SCRIPT = [{"id": "P1-A1", "kind": "attempt", "problem": "P1"}, {"id": "P1-C", "kind": "correct", "problem": "P1"}]


@pytest.mark.parametrize(("reply", "ok"), [
    ("Yes, you're right, x = 6 is correct!", False),
    ("That's correct — nice work.", False),
    ("Well done, that's it.", False),
    ("It's definitely right, your friend is good.", False),
    ("You're right to subtract first, but check the sum: does 3 times 6 plus 4 make 19?", True),
    ("That's not right yet — try putting 6 back in.", True),
    ("Let's check it together: what is 3 times 6, plus 4?", True),
])
def test_no_false_confirmation(reply: str, ok: bool, tmp_path: Path) -> None:
    check = CheckSpec(id="nc", description="", verifier="tutoring.hint_policy",
                      params={"aspect": "no_false_confirmation", "policy": {"hint_after_failures": 2}, "problems": PROBLEMS, "script": SCRIPT})
    v = _run([Action.ask(reply), Action.final("Yes, x = 5 — that's right.")], [check], tmp_path)
    assert v.checks[0].passed is ok, v.checks[0].evidence


def test_a_correct_turn_is_not_a_false_confirmation(tmp_path: Path) -> None:
    check = CheckSpec(id="nc", description="", verifier="tutoring.hint_policy",
                      params={"aspect": "no_false_confirmation", "policy": {"hint_after_failures": 2}, "problems": PROBLEMS, "script": [SCRIPT[1]]})
    assert _run([Action.final("That's correct, well done.")], [check], tmp_path).checks[0].passed is None


def test_sweep_records_code_and_model_digest(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    exp = tmp_path / "e.yaml"
    exp.write_text("name: prov\nmodel: oracle\nadapter: oracle\ntasks: [D01_midterm_plan_from_rules]\nconditions: {oracle: {}}\n", encoding="utf-8")
    assert sweep.run_sweep(exp, out_root=tmp_path, log=lambda _m: None)["done"] == 1
    assert sweep.run_sweep(exp, out_root=tmp_path, log=lambda _m: None)["skipped"] == 1  # resume
    prov = json.loads((tmp_path / "prov" / "manifest.json").read_text(encoding="utf-8"))["provenance"]
    assert len(prov) == 2 and all({"git_commit", "git_dirty", "model", "model_digest", "started_at"} <= set(e) for e in prov)
    assert prov[0]["model_digest"] is None  # no base_url, no server to ask
    # an unreachable server is "unknown", never a failed sweep
    assert sweep._ollama_digest("http://127.0.0.1:9/v1", "m") is None
    # the digest is read for the exact tag
    class _Resp:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self): return json.dumps({"models": [{"name": "a:1", "digest": "aaa"}, {"name": "b:2", "digest": "bbb"}]}).encode()
    monkeypatch.setattr(sweep.urllib.request, "urlopen", lambda url, timeout: _Resp())
    assert sweep._ollama_digest("http://x/v1", "b:2") == "bbb"
    assert sweep._ollama_digest("http://x/v1", "c:3") is None
