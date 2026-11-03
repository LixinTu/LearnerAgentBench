"""Trajectory recording: one JSON line per step while running, a Trajectory JSON at the end."""
from __future__ import annotations

from pathlib import Path

from ..schema import Step, Trajectory


class Recorder:
    def __init__(self, out_dir: Path, trajectory: Trajectory) -> None:
        self.out_dir = Path(out_dir)
        self.out_dir.mkdir(parents=True, exist_ok=True)
        self.trajectory = trajectory
        self.steps_path = self.out_dir / "steps.jsonl"

    def record(self, step: Step) -> None:
        self.trajectory.steps.append(step)
        with self.steps_path.open("a", encoding="utf-8") as fh:
            fh.write(step.model_dump_json() + "\n")

    def flush(self) -> Path:
        path = self.out_dir / "trajectory.json"
        path.write_text(self.trajectory.model_dump_json(indent=2), encoding="utf-8")
        return path

    @staticmethod
    def load(out_dir: Path) -> Trajectory:
        return Trajectory.model_validate_json((Path(out_dir) / "trajectory.json").read_text(encoding="utf-8"))

    @staticmethod
    def load_steps(out_dir: Path) -> list[Step]:
        p = Path(out_dir) / "steps.jsonl"
        if not p.is_file():
            return []
        return [Step.model_validate_json(line) for line in p.read_text(encoding="utf-8").splitlines() if line.strip()]
