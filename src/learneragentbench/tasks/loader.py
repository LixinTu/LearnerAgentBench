"""Load tasks, personas and skill graphs from the data directory; resolve variants."""
from __future__ import annotations

from pathlib import Path

import yaml

from ..env.seed import PersonaBundle, load_persona, load_skill_graph
from ..schema import SkillGraph, TaskFamily, TaskSpec

DEFAULT_DATA_DIR = Path(__file__).resolve().parents[3] / "data"


class Dataset:
    """Index of everything under ``data/``: tasks by id, personas by id, skill graphs by subject."""

    def __init__(self, data_dir: str | Path | None = None) -> None:
        self.data_dir = Path(data_dir) if data_dir else DEFAULT_DATA_DIR
        self._tasks: dict[str, Path] = {}
        self._personas: dict[str, Path] = {}
        self._graphs: dict[str, Path] = {}
        for p in sorted((self.data_dir / "tasks").rglob("*.yaml")):
            self._tasks[p.stem] = p
        for p in sorted((self.data_dir / "personas").glob("*.yaml")):
            self._personas[p.stem] = p
        for p in sorted((self.data_dir / "skills").glob("*.yaml")):
            self._graphs[p.stem] = p

    # --------------------------------------------------------------- listing
    def task_ids(self, families: list[TaskFamily] | None = None) -> list[str]:
        if not families:
            return sorted(self._tasks)
        return [tid for tid in sorted(self._tasks) if self.load_task(tid).family in families]

    def persona_ids(self) -> list[str]:
        return sorted(self._personas)

    def graph_ids(self) -> list[str]:
        return sorted(self._graphs)

    # --------------------------------------------------------------- loading
    def load_task(self, task_id: str) -> TaskSpec:
        if task_id not in self._tasks:
            raise KeyError(f"unknown task {task_id!r}; known: {sorted(self._tasks)[:10]}…")
        data = yaml.safe_load(self._tasks[task_id].read_text(encoding="utf-8"))
        spec = TaskSpec.model_validate(data)
        if spec.task_id != task_id:
            raise ValueError(f"{self._tasks[task_id]}: task_id {spec.task_id!r} does not match file name {task_id!r}")
        return spec

    def load_persona(self, persona_id: str) -> PersonaBundle:
        if persona_id not in self._personas:
            raise KeyError(f"unknown persona {persona_id!r}; known: {sorted(self._personas)}")
        return load_persona(self._personas[persona_id])

    def load_graph(self, subject: str) -> SkillGraph:
        if subject not in self._graphs:
            raise KeyError(f"unknown skill graph {subject!r}; known: {sorted(self._graphs)}")
        return load_skill_graph(self._graphs[subject])

    def task_path(self, task_id: str) -> Path:
        return self._tasks[task_id]
