"""The agent loop: observation → adapter → action → environment, with event injection,
a simulated student, trajectory recording, interruption and resume.

Virtual time advances ``step_minutes`` per agent step (a tool call takes a little while) and
by ``wait_minutes`` when the agent waits. Events fire when their ``at`` time has passed or
their ``after_step`` has been reached; approvals are decided by the simulated student.
"""
from __future__ import annotations

import json
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import Field

from ..env import applied_events, apply_event
from ..env.world import World
from ..schema import (
    LABModel,
    ModelUsage,
    Observation,
    ScheduledEvent,
    SessionTranscript,
    SimulatedUserSpec,
    Step,
    Trajectory,
)
from ..tools import ToolExecutor
from .adapter import DEFAULT_INSTRUCTIONS, AdapterError, AgentAdapter, TaskView
from .recorder import Recorder
from .simulated_user import SimulatedUser


class RunSpec(LABModel):
    run_id: str
    task_id: str
    variant_id: str = "base"
    persona_id: str
    seed: int = 0
    model: str
    adapter: str
    user_goal: str
    instructions: str = DEFAULT_INSTRUCTIONS
    persona_summary: str = ""
    history: list[SessionTranscript] = Field(default_factory=list)
    memory_notes: list[str] = Field(default_factory=list)
    allowed_tools: list[str] = Field(default_factory=list)
    events: list[ScheduledEvent] = Field(default_factory=list)
    simulated_user: SimulatedUserSpec = Field(default_factory=SimulatedUserSpec)
    max_steps: int = 40
    step_minutes: int = 2
    interrupt_after: int | None = None
    config: dict[str, Any] = Field(default_factory=dict)


class LoopState(LABModel):
    """Everything needed to resume: saved next to the world snapshot."""

    spec: RunSpec
    next_step: int
    adapter_state: dict[str, Any]
    pending_observation: Observation
    started_at: datetime
    usage: ModelUsage


class AgentLoop:
    def __init__(self, world: World, executor: ToolExecutor, adapter: AgentAdapter, spec: RunSpec, out_dir: str | Path) -> None:
        self.world = world
        self.executor = executor
        self.adapter = adapter
        self.spec = spec
        self.out_dir = Path(out_dir)
        self.user = SimulatedUser(spec.simulated_user, world)
        self.trajectory = Trajectory(run_id=spec.run_id, task_id=spec.task_id, variant_id=spec.variant_id,
                                     persona_id=spec.persona_id, seed=spec.seed, model=spec.model, adapter=spec.adapter,
                                     config=spec.config, started_at=world.now)
        self.recorder = Recorder(self.out_dir, self.trajectory)
        self._next_step = 0
        self._pending: Observation | None = None

    # ------------------------------------------------------------------- view
    def task_view(self) -> TaskView:
        return TaskView(run_id=self.spec.run_id, task_id=self.spec.task_id, variant_id=self.spec.variant_id,
                        user_goal=self.spec.user_goal, now=self.world.now, instructions=self.spec.instructions,
                        persona_summary=self.spec.persona_summary, history=self.spec.history,
                        memory_notes=self.spec.memory_notes,
                        tools=self.executor.registry.schemas(self.spec.allowed_tools), max_steps=self.spec.max_steps)

    # ------------------------------------------------------------------ events
    def _due_events(self, step: int) -> list[ScheduledEvent]:
        done = set(applied_events(self.world))
        due = []
        for ev in self.spec.events:
            if ev.id in done:
                continue
            if (ev.after_step is not None and step >= ev.after_step) or (ev.at is not None and self.world.now >= ev.at):
                due.append(ev)
        return due

    def _deliver(self, step: int) -> list[str]:
        notices = []
        for ev in self._due_events(step):
            try:
                text = apply_event(self.world, ev, step=step)
            except Exception as exc:
                self.trajectory.env_errors.append(f"event {ev.id}: {type(exc).__name__}: {exc}")
                continue
            notices.append(text if not ev.description else f"{ev.description} — {text}")
        notices.extend(self.user.process_approvals(step))
        return notices

    # -------------------------------------------------------------------- run
    def run(self) -> Trajectory:
        if self._pending is None:
            self.adapter.start(self.task_view())
            view = self.task_view().model_dump(mode="json")
            self._pending = Observation(type="task", content=view, step=0, virtual_time=self.world.now)
        obs = self._pending
        step = self._next_step
        try:
            while True:
                if step >= self.spec.max_steps:
                    self.trajectory.status = "max_steps"
                    break
                if self.spec.interrupt_after is not None and step >= self.spec.interrupt_after and step > 0:
                    self._pending = obs
                    self._next_step = step
                    self.trajectory.status = "interrupted"
                    self.save_state()
                    break
                notices = self._deliver(step)
                if notices:
                    obs = obs.model_copy(update={"content": _with_notices(obs.content, notices)})
                self.executor.ctx.step = step
                try:
                    action = self.adapter.step(obs)
                except AdapterError as exc:
                    self.trajectory.errors.append(f"adapter: {exc}")
                    self.trajectory.status = "error"
                    break
                except Exception as exc:
                    self.trajectory.errors.append(f"adapter crashed: {type(exc).__name__}: {exc}\n{traceback.format_exc()}")
                    self.trajectory.status = "error"
                    break
                wall = datetime.now()
                tool_record_id = None
                if action.type == "tool_call" and action.tool_call is not None:
                    res = self.executor.call(action.tool_call.tool, action.tool_call.args,
                                             idempotency_key=action.tool_call.idempotency_key)
                    tool_record_id = res.record_id
                    self.world.advance(minutes=self.spec.step_minutes, reason=f"step {step}")
                    nxt = Observation(type="tool_result" if res.ok else "tool_error", content=res.for_agent(),
                                      step=step + 1, virtual_time=self.world.now)
                elif action.type == "ask_user":
                    reply = self.user.answer(action.message)
                    self.world.advance(minutes=self.spec.step_minutes, reason=f"step {step} ask")
                    nxt = Observation(type="user_message", content={"question": action.message, "answer": reply},
                                      step=step + 1, virtual_time=self.world.now)
                elif action.type == "wait":
                    self.world.advance(minutes=max(1, action.wait_minutes), reason=f"step {step} wait")
                    nxt = Observation(type="event", content={"waited_minutes": action.wait_minutes,
                                                             "now": self.world.now.isoformat()},
                                      step=step + 1, virtual_time=self.world.now)
                else:  # final
                    self.trajectory.final_message = action.message
                    self.trajectory.status = "completed"
                    self.recorder.record(Step(index=step, observation=obs, action=action, virtual_time=self.world.now,
                                              wall_time=wall, usage=self.adapter.usage(), events_delivered=notices))
                    break
                self.recorder.record(Step(index=step, observation=obs, action=action, tool_record_id=tool_record_id,
                                          virtual_time=self.world.now, wall_time=wall, usage=self.adapter.usage(),
                                          events_delivered=notices))
                obs = nxt
                step += 1
        finally:
            self.trajectory.usage = self.adapter.usage()
            if self.trajectory.status != "interrupted":
                self.trajectory.post_finish_events = self._deliver_pending_step_events()
                self.trajectory.ended_at = self.world.now
            self.recorder.flush()
        return self.trajectory

    def _deliver_pending_step_events(self) -> list[str]:
        """The environment does not stop when the agent does: step-triggered events the agent never
        reached (because it finished early) still happen, so verifiers judge the world the student
        actually ends up in. Time-triggered events in the future are left alone."""
        out: list[str] = []
        done = set(applied_events(self.world))
        post_step = (self.trajectory.steps[-1].index + 1) if self.trajectory.steps else 0
        for ev in self.spec.events:
            if ev.id in done or ev.after_step is None:
                continue
            try:
                out.append(apply_event(self.world, ev, step=post_step))
            except Exception as exc:
                self.trajectory.env_errors.append(f"event {ev.id} (after finish): {type(exc).__name__}: {exc}")
        return out

    # ------------------------------------------------------------ interruption
    def save_state(self) -> Path:
        assert self._pending is not None
        self.world.snapshot(self.out_dir / "world_checkpoint.db")
        state = LoopState(spec=self.spec, next_step=self._next_step, adapter_state=self.adapter.state(),
                          pending_observation=self._pending, started_at=self.trajectory.started_at,
                          usage=self.adapter.usage())
        path = self.out_dir / "loop_state.json"
        path.write_text(state.model_dump_json(indent=2), encoding="utf-8")
        return path

    @classmethod
    def resume(cls, out_dir: str | Path, adapter_factory, executor_factory) -> AgentLoop:
        """Rebuild a loop from ``loop_state.json`` + ``world_checkpoint.db``.

        ``executor_factory(world)`` returns a ToolExecutor bound to the restored world and
        ``adapter_factory(world, executor)`` returns the adapter — both receive the *same* restored
        world, so reference policies that read state directly see the clock the loop advances."""
        out = Path(out_dir)
        state = LoopState.model_validate_json((out / "loop_state.json").read_text(encoding="utf-8"))
        world = World.from_snapshot(out / "world_checkpoint.db")
        executor = executor_factory(world)
        adapter: AgentAdapter = adapter_factory(world, executor)
        loop = cls(world, executor, adapter, state.spec, out)
        loop.trajectory.steps = Recorder.load_steps(out)
        loop.trajectory.started_at = state.started_at
        loop.trajectory.status = "running"
        loop.spec = state.spec.model_copy(update={"interrupt_after": None})
        loop._next_step = state.next_step
        loop._pending = (state.pending_observation.model_copy(update={"type": "resume"})
                         if state.pending_observation.type != "task" else state.pending_observation)
        adapter.start(loop.task_view())
        adapter.restore(state.adapter_state)
        return loop


def _with_notices(content: Any, notices: list[str]) -> Any:
    if isinstance(content, dict):
        out = dict(content)
        out["notices"] = list(out.get("notices", [])) + notices
        return out
    return {"content": content, "notices": notices}


def dump_json(obj: Any, path: Path) -> None:
    path.write_text(json.dumps(obj, indent=2, default=str), encoding="utf-8")
