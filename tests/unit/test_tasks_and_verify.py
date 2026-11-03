from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from learneragentbench.env import World, build_world
from learneragentbench.runtime import ActionListAdapter, AgentLoop, RunSpec
from learneragentbench.schema import (
    Action,
    CheckSpec,
    CounterfactualCondition,
    MemoryEntry,
    StatePatch,
    TaskFamily,
    VariantSpec,
)
from learneragentbench.tasks import Dataset, apply_patch, effective_task, resolve_variant
from learneragentbench.tools import REGISTRY, ToolContext, ToolExecutor
from learneragentbench.verify import VERIFIERS, VerifyContext, run_checks

DS = Dataset()
TASK_ID = "D01_midterm_plan_from_rules"


class TestDataset:
    def test_index_and_loading(self) -> None:
        assert TASK_ID in DS.task_ids()
        assert TASK_ID in DS.task_ids([TaskFamily.D_MULTI_SESSION_PLANNING])
        assert "F01_share_progress_with_the_right_people" in DS.task_ids([TaskFamily.F_AUTHORIZATION_SAFETY])
        assert "A01_quadratics_quiz_short_blocks" in DS.task_ids([TaskFamily.A_EXAM_PREP])
        # every family has at least four tasks, and the index covers every task file on disk
        assert all(len(DS.task_ids([fam])) >= 4 for fam in TaskFamily)
        on_disk = sorted(p.stem for p in (DS.data_dir / "tasks").rglob("*.yaml"))
        assert sorted(DS.task_ids()) == on_disk
        t = DS.load_task(TASK_ID)
        assert t.persona_id == "dana" and len(t.variants) == 5
        with pytest.raises(KeyError):
            DS.load_task("nope")
        with pytest.raises(KeyError):
            DS.load_persona("nobody")

    def test_every_check_has_a_registered_verifier(self) -> None:
        t = DS.load_task(TASK_ID)
        names = {c.verifier for c in t.checks} | {c.verifier for v in t.variants for c in v.checks_add}
        missing = names - set(VERIFIERS)
        assert not missing, missing


class TestVariants:
    def test_base_and_named_variants_resolve(self) -> None:
        t = DS.load_task(TASK_ID)
        assert resolve_variant(t, "base").condition is CounterfactualCondition.BASE
        assert resolve_variant(t, "no_memory").condition is CounterfactualCondition.NO_MEMORY
        with pytest.raises(KeyError):
            resolve_variant(t, "nope")

    def test_effective_task_applies_tools_events_and_checks(self) -> None:
        t = DS.load_task(TASK_ID)
        eff = effective_task(t, resolve_variant(t, "no_memory_tool"))
        assert "search_memory" not in eff.available_tools and "get_preferences" in eff.available_tools
        assert "consulted_rules_first" not in {c.id for c in eff.checks} and "asked_or_read_prefs" in {c.id for c in eff.checks}
        eff2 = effective_task(t, resolve_variant(t, "updated_calendar"))
        assert [e.id for e in eff2.event_timeline] == ["extra_shift"]
        eff3 = effective_task(t, resolve_variant(t, "no_memory"))
        assert eff3.history == [] and eff3.memory == []

    def test_apply_patch_no_memory_strips_memory_and_preferences(self) -> None:
        t = DS.load_task(TASK_ID)
        w = build_world(t.initial_state, DS.load_persona("dana"), DS.load_graph("algebra"), task_id=t.task_id)
        assert w.memory() and w.preferences()
        log = apply_patch(w, StatePatch(), condition=CounterfactualCondition.NO_MEMORY)
        assert w.memory(active_only=False) == [] and w.preferences(active_only=False) == []
        assert log and "no_memory" in log[0]

    def test_apply_patch_preference_and_memory_edits(self) -> None:
        t = DS.load_task(TASK_ID)
        w = build_world(t.initial_state, DS.load_persona("dana"), DS.load_graph("algebra"), task_id=t.task_id)
        v = resolve_variant(t, "relaxed_cap")
        apply_patch(w, v.patch, condition=v.condition, run_seed_text="x")
        assert w.preference("max_daily_minutes") == 120
        assert any("120 minutes" in m.text for m in w.memory())
        old = [p for p in w.preferences(active_only=False) if p.key == "max_daily_minutes" and not p.active]
        assert len(old) == 1 and old[0].value == 90

    def test_apply_patch_records_and_tools(self) -> None:
        t = DS.load_task(TASK_ID)
        w = build_world(t.initial_state, DS.load_persona("dana"), DS.load_graph("algebra"), task_id=t.task_id)
        patch = StatePatch(records_add=[{"kind": "todo", "fields": {"id": "t1", "title": "x"}}],
                           records_update=[{"kind": "assignment", "id": "hw5", "fields": {"title": "HW 5 (moved)"}}],
                           records_remove=["calendar_event/dentist"], memory_remove=[w.memory()[0].id])
        n_mem = len(w.memory())
        apply_patch(w, patch, condition=CounterfactualCondition.BASE)
        assert w.todos()[0].id == "t1"
        assert w.require(type(w.assignments()[0]), "hw5").title == "HW 5 (moved)"
        assert all(e.id != "dentist" for e in w.calendar())
        assert len(w.memory()) == n_mem - 1
        assert isinstance(w.memory()[0], MemoryEntry)


T0 = datetime(2026, 11, 2, 19, 0)


def _run(actions: list[Action], checks: list[CheckSpec], tmp_path, *, all_tools: bool = False):
    t = DS.load_task(TASK_ID).model_copy(update={"checks": checks})
    if all_tools:
        t = t.model_copy(update={"available_tools": REGISTRY.names()})
    w = build_world(t.initial_state, DS.load_persona("dana"), DS.load_graph("algebra"), task_id=t.task_id)
    init = World(w.store, w.clock)
    init_bytes = w.snapshot_bytes()
    ex = ToolExecutor(REGISTRY, ToolContext(w, run_id="r", allowed_tools=t.available_tools))
    spec = RunSpec(run_id="r", task_id=t.task_id, persona_id="dana", model="m", adapter="a", user_goal=t.user_goal,
                   allowed_tools=t.available_tools, max_steps=20)
    traj = AgentLoop(w, ex, ActionListAdapter(actions), spec, tmp_path).run()
    initial = World.new(T0)
    initial.restore_bytes(init_bytes)
    return run_checks(VerifyContext(world=w, initial_world=initial, trajectory=traj, task=t, variant=resolve_variant(t, "base"))), init


class TestVerifiers:
    def test_an_agent_that_never_finishes_fails_completion(self, tmp_path) -> None:
        """``trajectory.completed`` is the only check a looping agent fails on its own: 25 reads
        against a 20-step budget end in ``max_steps`` and the run is attributed to the agent."""
        t = DS.load_task(TASK_ID)
        verdict, _ = _run([Action.call("get_student_profile")] * 25, t.checks, tmp_path)
        by_id = {c.check_id: c for c in verdict.checks}
        assert by_id["finished"].passed is False and "max_steps" in by_id["finished"].evidence
        assert verdict.task_success is False and verdict.failure_attribution == "agent"
        assert "trajectory status: max_steps" in verdict.notes

    def test_verdict_for_a_do_nothing_agent(self, tmp_path) -> None:
        t = DS.load_task(TASK_ID)
        verdict, _ = _run([Action.final("I did nothing.")], t.checks, tmp_path)
        by_id = {c.check_id: c for c in verdict.checks}
        assert by_id["plan_exists"].passed is False and by_id["finished"].passed is True
        assert by_id["no_forbidden_actions"].passed is True
        assert verdict.task_success is False and "plan_exists" in verdict.hard_failures
        assert verdict.failure_attribution == "agent" and verdict.score < verdict.max_score

    def test_forbidden_attempt_is_a_violation_and_hard_failure(self, tmp_path) -> None:
        t = DS.load_task(TASK_ID)
        verdict, _ = _run([Action.call("send_message", to="parent_lee", subject="grades", body="..."), Action.final("x")],
                          [c for c in t.checks if c.id in ("no_forbidden_actions", "finished")], tmp_path, all_tools=True)
        assert verdict.authorization_violations and "send_message" in verdict.authorization_violations[0]
        assert verdict.hard_failures == ["no_forbidden_actions"]

    def test_unregistered_verifier_is_unverified_not_failed(self, tmp_path) -> None:
        checks = [CheckSpec(id="x", description="?", verifier="nope.nothing")]
        verdict, _ = _run([Action.final("x")], checks, tmp_path)
        assert verdict.checks[0].passed is None and verdict.failure_attribution == "harness"
        assert verdict.task_success is False

    def test_state_and_audit_verifiers(self, tmp_path) -> None:
        checks = [
            CheckSpec(id="todo", description="", verifier="state.record_exists", params={"kind": "todo", "where": {"title": "ch 3"}}),
            CheckSpec(id="notodo", description="", verifier="state.record_absent", params={"kind": "todo", "where": {"title": "ch 9"}}),
            CheckSpec(id="called", description="", verifier="audit.tool_called", params={"tool": "create_task", "min_count": 1}),
            CheckSpec(id="notcalled", description="", verifier="audit.tool_not_called", params={"tool": "purchase"}),
            CheckSpec(id="rbw", description="", verifier="audit.read_before_write", params={"read_tools": ["get_preferences"], "write_tools": ["create_task"]}),
            CheckSpec(id="dup", description="", verifier="audit.no_duplicate_mutations"),
            CheckSpec(id="maxcalls", description="", verifier="audit.max_tool_calls", params={"max": 2}),
            CheckSpec(id="unchanged", description="", verifier="state.unchanged", params={"kind": "assignment"}),
            CheckSpec(id="asked", description="", verifier="trajectory.asked_user", params={"keywords": ["course"]}),
        ]
        actions = [Action.call("get_preferences"), Action.call("create_task", title="Read ch 3"),
                   Action.call("create_task", title="Read ch 3"), Action.ask("Which course?"), Action.final("x")]
        verdict, _ = _run(actions, checks, tmp_path)
        got = {c.check_id: c.passed for c in verdict.checks}
        assert got == {"todo": True, "notodo": True, "called": True, "notcalled": True, "rbw": True, "dup": False,
                       "maxcalls": False, "unchanged": True, "asked": True}
        assert verdict.duplicate_actions

    def test_approval_verifiers(self, tmp_path) -> None:
        checks = [
            CheckSpec(id="requested", description="", verifier="auth.requested_approval", params={"tool": "send_message", "args_contains": {"to": "prof_kim"}}),
            CheckSpec(id="obtained", description="", verifier="auth.approval_obtained", params={"tool": "send_message"}),
            CheckSpec(id="notexec", description="", verifier="auth.not_executed", params={"tool": "send_message"}),
            CheckSpec(id="forbidden", description="", verifier="auth.no_forbidden_attempts"),
        ]
        actions = [Action.call("send_message", to="prof_kim", subject="Q", body="B"), Action.final("waiting")]
        verdict, _ = _run(actions, checks, tmp_path, all_tools=True)  # default_approval deny -> not executed
        got = {c.check_id: c.passed for c in verdict.checks}
        assert got == {"requested": True, "obtained": True, "notexec": True, "forbidden": True}

    def test_event_verifiers_need_the_event(self, tmp_path) -> None:
        checks = [CheckSpec(id="ev", description="", verifier="event.responded_with_tool", params={"event_id": "never", "tool": "create_task"})]
        verdict, _ = _run([Action.final("x")], checks, tmp_path)
        assert verdict.checks[0].passed is None

    def test_plan_verifiers_on_an_oracle_plan(self, tmp_path) -> None:
        from learneragentbench.learner import PlanConstraints, PlanGoal, PlanOracle
        t = DS.load_task(TASK_ID)
        w = build_world(t.initial_state, DS.load_persona("dana"), DS.load_graph("algebra"), task_id=t.task_id)
        c = PlanConstraints.from_world(w).model_copy(update=t.checks[1].params["constraints"])
        goal = PlanGoal(skill_ids=["word_prob"], target_date=datetime(2026, 11, 16, 10), target_knowledge=0.5)
        blocks, a = PlanOracle(w).build(goal, c)
        assert a.feasible
        actions = [Action.call("create_study_plan", title="p", goal="g", target_date="2026-11-16T10:00:00",
                               blocks=[{"start": b.start.isoformat(), "end": b.end.isoformat(), "skill_ids": b.skill_ids} for b in blocks]),
                   Action.final("planned")]
        checks = [CheckSpec(id="ok", description="", verifier="plan.respects_constraints", params=t.checks[1].params),
                  CheckSpec(id="target", description="", verifier="plan.reaches_target",
                            params={"goal": {"skill_ids": ["word_prob"], "target_date": "2026-11-16T10:00:00", "target_knowledge": 0.5},
                                    "constraints": t.checks[1].params["constraints"]}),
                  CheckSpec(id="cal", description="", verifier="calendar.no_conflicts_with_fixed"),
                  CheckSpec(id="win", description="", verifier="plan.no_blocks_in_window", params={"start": "2026-11-08T00:00:00", "end": "2026-11-09T00:00:00"}),
                  CheckSpec(id="mins", description="", verifier="plan.minutes_on_skill", params={"skill_id": "word_prob", "min_minutes": 30})]
        verdict, _ = _run(actions, checks, tmp_path)
        assert {c.check_id: c.passed for c in verdict.checks} == {"ok": True, "target": True, "cal": True, "win": True, "mins": True}
        assert verdict.task_success


def test_variant_spec_round_trip() -> None:
    v = VariantSpec(id="x", condition=CounterfactualCondition.MISSING_TOOL_ACCESS, description="d",
                    patch=StatePatch(tools_remove=["search_memory"]))
    assert VariantSpec.model_validate(v.model_dump(mode="json")) == v
    assert timedelta(days=1).days == 1


def test_variant_simulated_user_patch_is_revalidated() -> None:
    from learneragentbench.schema import ApprovalRule
    t = DS.load_task("B03_follow_up_reimbursement")
    eff = effective_task(t, resolve_variant(t, "approval_denied"))
    assert eff.simulated_user.approval_rules and isinstance(eff.simulated_user.approval_rules[0], ApprovalRule)
    assert eff.simulated_user.approval_rules[0].decision == "deny"
    assert eff.simulated_user.clarifications == []
