"""The World: typed access to one student's simulated environment plus the virtual clock.

Every mutation goes through ``add`` / ``update`` / ``remove`` so the tool layer can learn
which records a call touched (``track``) and so the history table stays complete.
"""
from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, time, timedelta
from pathlib import Path
from typing import Any, TypeVar

from ..schema import (
    RECORD_TYPES,
    ApprovalRequest,
    Assessment,
    AssessmentResult,
    Assignment,
    AuthorizationPolicy,
    CalendarEvent,
    Course,
    MasteryState,
    MemoryEntry,
    Message,
    Preference,
    Record,
    SkillGraph,
    StudentProfile,
    StudyPlan,
    StudySession,
    Submission,
    TimeWindow,
    TodoItem,
    ToolCallRecord,
)
from .clock import VirtualClock
from .store import ConflictError, NotFoundError, Store

R = TypeVar("R", bound=Record)

__all__ = ["ConflictError", "NotFoundError", "World"]


class World:
    def __init__(self, store: Store, clock: VirtualClock) -> None:
        self.store = store
        self.clock = clock
        self._touched: list[list[str]] = []
        self.store.kv_set("clock.now", clock.now.isoformat())

    # ------------------------------------------------------------- construction
    @classmethod
    def new(cls, now: datetime, path: str | Path | None = None) -> World:
        return cls(Store(path), VirtualClock(now))

    @classmethod
    def from_snapshot(cls, path: str | Path) -> World:
        store = Store.from_snapshot(path)
        now = datetime.fromisoformat(store.kv_get("clock.now"))
        return cls(store, VirtualClock(now))

    def snapshot(self, path: str | Path) -> Path:
        self.store.kv_set("clock.now", self.clock.now.isoformat())
        return self.store.snapshot_to(path)

    def snapshot_bytes(self) -> bytes:
        self.store.kv_set("clock.now", self.clock.now.isoformat())
        return self.store.snapshot_bytes()

    def restore_bytes(self, data: bytes) -> None:
        self.store.restore_bytes(data)
        self.clock = VirtualClock(datetime.fromisoformat(self.store.kv_get("clock.now")))

    @property
    def now(self) -> datetime:
        return self.clock.now

    def advance(self, **kw: Any) -> datetime:
        t = self.clock.advance(**kw)
        self.store.kv_set("clock.now", t.isoformat())
        return t

    def set_time(self, when: datetime, reason: str = "") -> datetime:
        t = self.clock.set(when, reason)
        self.store.kv_set("clock.now", t.isoformat())
        return t

    # ------------------------------------------------------------------ tracking
    @contextmanager
    def track(self) -> Iterator[list[str]]:
        bucket: list[str] = []
        self._touched.append(bucket)
        try:
            yield bucket
        finally:
            self._touched.pop()

    def _note(self, rec: Record) -> None:
        tag = f"{type(rec).kind}/{rec.id}"
        for bucket in self._touched:
            if tag not in bucket:
                bucket.append(tag)

    # ----------------------------------------------------------------- mutation
    def add(self, rec: R) -> R:
        out = self.store.put(rec, now=self.now)
        self._note(out)
        return out  # type: ignore[return-value]

    def update(self, rec: R, *, expected_version: int | None = None) -> R:
        out = self.store.update(rec, now=self.now, expected_version=expected_version)
        self._note(out)
        return out  # type: ignore[return-value]

    def patch(self, rec: R, fields: dict[str, Any]) -> R:
        """Update ``rec`` from raw field values (strings and dicts straight from YAML), re-validated
        through the record's model so a date stays a datetime and a plan block a PlanBlock."""
        merged = type(rec).model_validate({**rec.model_dump(mode="python"), **fields})
        return self.update(merged)

    def remove(self, cls: type[Record], rec_id: str) -> Record:
        out = self.store.delete(cls, rec_id, now=self.now)
        self._note(out)
        return out

    def get(self, cls: type[R], rec_id: str) -> R | None:
        return self.store.get(cls, rec_id)

    def require(self, cls: type[R], rec_id: str) -> R:
        return self.store.require(cls, rec_id)

    def list(self, cls: type[R]) -> list[R]:
        return self.store.list(cls)

    def record_by_kind(self, kind: str, rec_id: str) -> Record | None:
        return self.store.get(RECORD_TYPES[kind], rec_id)

    # -------------------------------------------------------------- skill graph
    @property
    def skill_graph(self) -> SkillGraph:
        data = self.store.kv_get("skill_graph")
        if data is None:
            return SkillGraph(subject="none", skills=[])
        return SkillGraph.model_validate(data)

    def set_skill_graph(self, graph: SkillGraph) -> None:
        self.store.kv_set("skill_graph", graph.model_dump(mode="json"))

    # ------------------------------------------------------------------- student
    def profile(self) -> StudentProfile:
        rows = self.list(StudentProfile)
        if not rows:
            raise NotFoundError("no student profile in this world")
        return rows[0]

    def preferences(self, *, active_only: bool = True, key: str | None = None) -> list[Preference]:
        rows = self.list(Preference)
        if active_only:
            rows = [p for p in rows if p.active]
        if key is not None:
            rows = [p for p in rows if p.key == key]
        return rows

    def preference(self, key: str, scope: str = "global", default: Any = None) -> Any:
        """Most recently stated active preference for ``key``; scoped beats global."""
        best: Preference | None = None
        for p in self.preferences(key=key):
            if p.scope not in (scope, "global"):
                continue
            if best is None or (p.scope == scope and best.scope != scope) or (
                p.scope == best.scope and p.stated_at > best.stated_at
            ):
                best = p
        return default if best is None else best.value

    def memory(self, *, active_only: bool = True) -> list[MemoryEntry]:
        rows = self.list(MemoryEntry)
        return [m for m in rows if m.active] if active_only else rows

    def policies(self) -> list[AuthorizationPolicy]:
        return [p for p in self.list(AuthorizationPolicy)
                if p.expires_at is None or p.expires_at > self.now]

    def approvals(self) -> list[ApprovalRequest]:
        return self.list(ApprovalRequest)

    # ------------------------------------------------------------------ learning
    def mastery(self) -> dict[str, MasteryState]:
        return {m.skill_id: m for m in self.list(MasteryState)}

    def sessions(self) -> list[StudySession]:
        return self.list(StudySession)

    def courses(self) -> list[Course]:
        return self.list(Course)

    def assessments(self) -> list[Assessment]:
        return self.list(Assessment)

    def results(self) -> list[AssessmentResult]:
        return self.list(AssessmentResult)

    def assignments(self) -> list[Assignment]:
        return self.list(Assignment)

    def submissions(self) -> list[Submission]:
        return self.list(Submission)

    def plans(self, status: str | None = None) -> list[StudyPlan]:
        rows = self.list(StudyPlan)
        return rows if status is None else [p for p in rows if p.status == status]

    def active_plan(self) -> StudyPlan | None:
        active = self.plans("active")
        return active[-1] if active else None

    # --------------------------------------------------------------------- world
    def calendar(self, start: datetime | None = None, end: datetime | None = None,
                 *, include_cancelled: bool = False) -> list[CalendarEvent]:
        rows = self.list(CalendarEvent)
        if not include_cancelled:
            rows = [e for e in rows if e.status != "cancelled"]
        if start is not None:
            rows = [e for e in rows if e.end > start]
        if end is not None:
            rows = [e for e in rows if e.start < end]
        return sorted(rows, key=lambda e: e.start)

    def calendar_conflicts(self, start: datetime, end: datetime, *, ignore_id: str | None = None) -> list[CalendarEvent]:
        probe = CalendarEvent(id="probe", created_at=self.now, updated_at=self.now, title="", start=start, end=end)
        return [e for e in self.calendar(start, end) if e.id != ignore_id and e.overlaps(probe)]

    def free_slots(self, day: datetime, windows: list[TimeWindow], *, min_minutes: int = 30,
                   granularity_minutes: int = 15) -> list[tuple[datetime, datetime]]:
        """Free intervals inside the given windows on ``day`` (date part), avoiding calendar events."""
        base = datetime.combine(day.date(), time(0, 0))
        busy = self.calendar(base, base + timedelta(days=1))
        out: list[tuple[datetime, datetime]] = []
        step = timedelta(minutes=granularity_minutes)
        for w in windows:
            ws = datetime.combine(day.date(), time.fromisoformat(w.start))
            we = datetime.combine(day.date(), time.fromisoformat(w.end))
            cur = ws
            slot_start: datetime | None = None
            while cur + step <= we:
                nxt = cur + step
                blocked = any(e.start < nxt and cur < e.end for e in busy)
                if blocked:
                    if slot_start is not None and (cur - slot_start) >= timedelta(minutes=min_minutes):
                        out.append((slot_start, cur))
                    slot_start = None
                elif slot_start is None:
                    slot_start = cur
                cur = nxt
            if slot_start is not None and (cur - slot_start) >= timedelta(minutes=min_minutes):
                out.append((slot_start, cur))
        return out

    def messages(self, *, unread_only: bool = False) -> list[Message]:
        rows = self.list(Message)
        if unread_only:
            rows = [m for m in rows if not m.read]
        return sorted(rows, key=lambda m: m.sent_at)

    def todos(self, *, open_only: bool = False) -> list[TodoItem]:
        rows = self.list(TodoItem)
        return [t for t in rows if t.status == "open"] if open_only else rows

    def tool_calls(self, run_id: str | None = None) -> list[ToolCallRecord]:
        rows = self.list(ToolCallRecord)
        return rows if run_id is None else [r for r in rows if r.run_id == run_id]

    # ------------------------------------------------------------------- outages
    def tool_available(self, tool: str) -> bool:
        return not bool(self.store.kv_get(f"outage:{tool}", False))

    def set_tool_outage(self, tool: str, down: bool) -> None:
        self.store.kv_set(f"outage:{tool}", down)

    # ------------------------------------------------------------------- summary
    def summary(self) -> dict[str, int]:
        return {kind: self.store.count(cls) for kind, cls in RECORD_TYPES.items()}
