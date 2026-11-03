"""Run one (task, variant, seed) with one adapter: build the world, apply the variant, run the
loop, snapshot, verify, and write every artifact needed to reproduce or inspect the run.

runs/<run_id>/
    config.json            RunConfig + resolved parameters
    task_effective.json    the TaskSpec actually used (after the variant)
    world_init.db          snapshot after seeding and patching, before the agent acts
    world_final.db         snapshot after the agent finished
    steps.jsonl, trajectory.json
    verdict.json
    variant_log.json       what the variant patch changed
"""
from __future__ import annotations

import json
import random
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

from ..env import World, build_world
from ..env.seed import persona_system_summary
from ..runtime import AgentLoop, RunSpec
from ..runtime.adapter import AgentAdapter
from ..runtime.adapters.openai_compatible import OpenAICompatibleAdapter
from ..schema import RunConfig, TaskSpec, Trajectory, VariantSpec, Verdict, new_id
from ..tasks import Dataset, apply_patch, effective_task, resolve_variant
from ..tools import READ_TOOLS, REGISTRY, ToolContext, ToolExecutor
from ..verify import VerifyContext, run_checks

AdapterFactory = Callable[[RunConfig, TaskSpec, World, ToolExecutor], AgentAdapter]


class RunResult:
    def __init__(self, trajectory: Trajectory, verdict: Verdict, out_dir: Path) -> None:
        self.trajectory = trajectory
        self.verdict = verdict
        self.out_dir = out_dir


def make_run_id(task_id: str, variant_id: str, seed: int, model: str) -> str:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return f"{task_id}__{variant_id}__s{seed}__{model.replace('/', '_').replace(':', '-')}__{stamp}-{new_id('', str(random.random()))[1:5]}"


def allowed_tools_for(task: TaskSpec, config: RunConfig) -> list[str]:
    tools = list(task.available_tools)
    if config.tool_profile == "none":
        return []
    if config.tool_profile == "read_only":
        return [t for t in tools if t in READ_TOOLS]
    return tools


def build_run_spec(task: TaskSpec, variant: VariantSpec, config: RunConfig, seed: int, run_id: str, world: World,
                   persona_summary: str) -> RunSpec:
    memory_notes: list[str] = []
    history = list(task.history)
    if config.memory_access == "full":
        memory_notes = [m.text for m in sorted(world.memory(), key=lambda m: m.stated_at)]
    elif config.memory_access == "transcripts_only":
        memory_notes = []
    else:  # "tools": memory only through search_memory / get_preferences; "none": nothing at all
        history = []
    return RunSpec(run_id=run_id, task_id=task.task_id, variant_id=variant.id, persona_id=task.persona_id, seed=seed,
                   model=config.model, adapter=config.adapter, user_goal=task.user_goal, persona_summary=persona_summary,
                   history=history, memory_notes=memory_notes, allowed_tools=allowed_tools_for(task, config),
                   events=list(task.event_timeline), simulated_user=task.simulated_user,
                   max_steps=config.max_steps or task.max_steps, interrupt_after=config.adapter_params.get("interrupt_after"),
                   config={**config.model_dump(mode="json"), "seed": seed})


def default_adapter_factory(config: RunConfig, task: TaskSpec, world: World, executor: ToolExecutor) -> AgentAdapter:
    name = config.adapter
    if name == "oracle":
        from ..baselines import make_oracle
        from ..schema import CounterfactualCondition
        cond = CounterfactualCondition(config.adapter_params.get("variant_condition", "base"))
        return make_oracle(task, world, executor, condition=cond)
    if name == "openai_compatible":
        p = dict(config.adapter_params)
        return OpenAICompatibleAdapter(config.model, base_url=p.get("base_url"), api_key=p.get("api_key"),
                                       temperature=config.temperature, max_tokens=int(p.get("max_tokens", 1024)),
                                       json_fallback=bool(p.get("json_fallback", False)),
                                       extra_body=p.get("extra_body"), timeout=float(p.get("timeout", 180)),
                                       seed=p.get("seed"))
    raise KeyError(f"unknown adapter {name!r} (known: oracle, openai_compatible)")


def run_one(dataset: Dataset, task_id: str, variant_id: str, config: RunConfig, seed: int, *,
            adapter_factory: AdapterFactory = default_adapter_factory, out_root: str | Path | None = None,
            run_id: str | None = None) -> RunResult:
    random.seed(seed)
    base_task = dataset.load_task(task_id)
    variant = resolve_variant(base_task, variant_id)
    persona = dataset.load_persona(variant.patch.persona_id or base_task.persona_id)
    if not base_task.history and persona.history:
        base_task = base_task.model_copy(update={"history": list(persona.history)})
    task = effective_task(base_task, variant)
    graph = dataset.load_graph(task.initial_state.skill_graph or "algebra")
    run_id = run_id or make_run_id(task_id, variant_id, seed, config.model)
    out_dir = Path(out_root or config.output_dir) / run_id
    out_dir.mkdir(parents=True, exist_ok=True)

    world = build_world(task.initial_state, persona, graph, task_memory=task.memory, path=out_dir / "world.db", task_id=task_id)
    variant_log = apply_patch(world, variant.patch, condition=variant.condition, run_seed_text=f"{run_id}")
    (out_dir / "variant_log.json").write_text(json.dumps(variant_log, indent=2), encoding="utf-8")
    world.snapshot(out_dir / "world_init.db")
    executor = ToolExecutor(REGISTRY, ToolContext(world, run_id=run_id, allowed_tools=allowed_tools_for(task, config)))
    spec = build_run_spec(task, variant, config, seed, run_id, world, persona_system_summary(persona))
    (out_dir / "config.json").write_text(json.dumps({**config.model_dump(mode="json"), "seed": seed, "run_id": run_id,
                                                      "task_id": task_id, "variant_id": variant_id}, indent=2), encoding="utf-8")
    (out_dir / "task_effective.json").write_text(task.model_dump_json(indent=2), encoding="utf-8")

    config = config.model_copy(update={"adapter_params": {**config.adapter_params, "variant_condition": variant.condition.value, "seed": seed}})
    adapter = adapter_factory(config, task, world, executor)
    loop = AgentLoop(world, executor, adapter, spec, out_dir)
    trajectory = loop.run()
    world.snapshot(out_dir / "world_final.db")
    verdict = verify_run(world, World.from_snapshot(out_dir / "world_init.db"), trajectory, task, variant)
    (out_dir / "verdict.json").write_text(verdict.model_dump_json(indent=2), encoding="utf-8")
    return RunResult(trajectory, verdict, out_dir)


def verify_run(world: World, initial_world: World | None, trajectory: Trajectory, task: TaskSpec, variant: VariantSpec) -> Verdict:
    ctx = VerifyContext(world=world, initial_world=initial_world, trajectory=trajectory, task=task, variant=variant)
    return run_checks(ctx)


def reverify(out_dir: str | Path, dataset: Dataset) -> Verdict:
    """Re-score an existing run directory (e.g. after a verifier fix). Does not re-run the agent."""
    out = Path(out_dir)
    task_eff = TaskSpec.model_validate_json((out / "task_effective.json").read_text(encoding="utf-8"))
    cfg = json.loads((out / "config.json").read_text(encoding="utf-8"))
    base_task = dataset.load_task(cfg["task_id"])
    variant = resolve_variant(base_task, cfg["variant_id"])
    trajectory = Trajectory.model_validate_json((out / "trajectory.json").read_text(encoding="utf-8"))
    world = World.from_snapshot(out / "world_final.db")
    initial = World.from_snapshot(out / "world_init.db") if (out / "world_init.db").is_file() else None
    verdict = verify_run(world, initial, trajectory, task_eff, variant)
    (out / "verdict.json").write_text(verdict.model_dump_json(indent=2), encoding="utf-8")
    return verdict


class RescoreError(ValueError):
    """The task has changed in a way the agent could see, so the stored run no longer answers it."""


_AGENT_FACING = ("user_goal", "persona_id", "initial_state", "memory", "event_timeline", "available_tools", "simulated_user")


def rescore(out_dir: str | Path, dataset: Dataset, *, dry_run: bool = False) -> tuple[Verdict, bool]:
    """Judge a stored run against the task's CURRENT checks, without re-running the agent. This is legitimate because
    checks are hidden from the agent: changing one cannot change what it did. Anything the agent could see must be
    unchanged, or this refuses. The verdict and spec as they were at run time are kept beside the new ones.
    Returns the verdict and whether it differs from the stored one."""
    out = Path(out_dir)
    stored = TaskSpec.model_validate_json((out / "task_effective.json").read_text(encoding="utf-8"))
    cfg = json.loads((out / "config.json").read_text(encoding="utf-8"))
    base_task = dataset.load_task(cfg["task_id"])
    variant = resolve_variant(base_task, cfg["variant_id"])
    current = effective_task(base_task, variant)
    changed = [f for f in _AGENT_FACING if getattr(stored, f) != getattr(current, f)]
    if changed:
        raise RescoreError(f"{out.name}: {changed} changed since the run; it has to be run again")
    spec = stored.model_copy(update={"checks": current.checks})
    trajectory = Trajectory.model_validate_json((out / "trajectory.json").read_text(encoding="utf-8"))
    world = World.from_snapshot(out / "world_final.db")
    initial = World.from_snapshot(out / "world_init.db") if (out / "world_init.db").is_file() else None
    verdict = verify_run(world, initial, trajectory, spec, variant)
    old_text = (out / "verdict.json").read_text(encoding="utf-8")
    old = json.loads(old_text)
    def key(checks: list[dict[str, Any]]) -> list[tuple[Any, ...]]:
        return sorted((c["check_id"], c["passed"], c["weight"], c["hard"]) for c in checks)
    new = verdict.model_dump(mode="json")
    moved = key(old["checks"]) != key(new["checks"]) or old["score"] != new["score"] or old["task_success"] != new["task_success"]
    if moved and not dry_run:
        for name, text in (("verdict_at_run.json", old_text), ("task_effective_at_run.json", (out / "task_effective.json").read_text(encoding="utf-8"))):
            if not (out / name).exists():
                (out / name).write_text(text, encoding="utf-8")
        (out / "task_effective.json").write_text(spec.model_dump_json(indent=2), encoding="utf-8")
        (out / "verdict.json").write_text(verdict.model_dump_json(indent=2), encoding="utf-8")
    return verdict, moved


def resume_run(out_dir: str | Path, config: RunConfig, dataset: Dataset, *,
               adapter_factory: AdapterFactory = default_adapter_factory) -> RunResult:
    out = Path(out_dir)
    task_eff = TaskSpec.model_validate_json((out / "task_effective.json").read_text(encoding="utf-8"))
    cfg = json.loads((out / "config.json").read_text(encoding="utf-8"))
    variant = resolve_variant(dataset.load_task(cfg["task_id"]), cfg["variant_id"])

    def executor_factory(w: World) -> ToolExecutor:
        return ToolExecutor(REGISTRY, ToolContext(w, run_id=cfg["run_id"], allowed_tools=allowed_tools_for(task_eff, config)))

    def bound_adapter(w: World, ex: ToolExecutor) -> AgentAdapter:
        return adapter_factory(config, task_eff, w, ex)

    loop = AgentLoop.resume(out, bound_adapter, executor_factory)
    trajectory = loop.run()
    loop.world.snapshot(out / "world_final.db")
    verdict = verify_run(loop.world, World.from_snapshot(out / "world_init.db"), trajectory, task_eff, variant)
    (out / "verdict.json").write_text(verdict.model_dump_json(indent=2), encoding="utf-8")
    return RunResult(trajectory, verdict, out)


def load_verdicts(root: str | Path) -> list[dict[str, Any]]:
    out = []
    for p in sorted(Path(root).glob("*/verdict.json")):
        out.append(json.loads(p.read_text(encoding="utf-8")))
    return out
