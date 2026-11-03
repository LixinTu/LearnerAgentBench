"""Adapters that do not call a model: fixed action lists, Python policies, and replay of a
recorded trajectory. Used for harness tests, task validation and the Oracle reference policy."""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from ...schema import Action, ModelUsage, Observation, Trajectory
from ..adapter import TaskView

Policy = Callable[[TaskView, Observation, dict[str, Any]], Action]


class ActionListAdapter:
    name = "action_list"

    def __init__(self, actions: list[Action]) -> None:
        self._actions = list(actions)
        self._i = 0
        self.view: TaskView | None = None

    def start(self, view: TaskView) -> None:
        self.view = view

    def step(self, observation: Observation) -> Action:
        if self._i >= len(self._actions):
            return Action.final("")  # out of actions: silence, so a scripted agent cannot "answer" a line by accident
        a = self._actions[self._i]
        self._i += 1
        return a

    def state(self) -> dict[str, Any]:
        return {"i": self._i}

    def restore(self, state: dict[str, Any]) -> None:
        self._i = int(state.get("i", 0))

    def usage(self) -> ModelUsage:
        return ModelUsage()


class PolicyAdapter:
    """Runs a Python policy ``policy(view, observation, memory) -> Action``; ``memory`` is a
    JSON-able dict the policy may use to keep state (it is what gets checkpointed)."""

    name = "policy"

    def __init__(self, policy: Policy, name: str = "policy") -> None:
        self._policy = policy
        self.name = name
        self.memory: dict[str, Any] = {}
        self.view: TaskView | None = None

    def start(self, view: TaskView) -> None:
        self.view = view

    def step(self, observation: Observation) -> Action:
        assert self.view is not None
        return self._policy(self.view, observation, self.memory)

    def state(self) -> dict[str, Any]:
        return {"memory": self.memory}

    def restore(self, state: dict[str, Any]) -> None:
        self.memory = dict(state.get("memory", {}))

    def usage(self) -> ModelUsage:
        return ModelUsage()


class ReplayAdapter(ActionListAdapter):
    """Replays the actions of a recorded trajectory (for regression tests of the harness)."""

    name = "replay"

    def __init__(self, trajectory: Trajectory) -> None:
        super().__init__([s.action for s in trajectory.steps])
