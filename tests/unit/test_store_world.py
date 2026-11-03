from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from learneragentbench.env import ConflictError, NotFoundError, Store, World
from learneragentbench.schema import (
    Actor,
    CalendarEvent,
    MasteryState,
    Preference,
    Skill,
    SkillGraph,
    StudentProfile,
    TimeWindow,
    TodoItem,
)

T0 = datetime(2026, 11, 2, 9, 0)


def _world() -> World:
    return World.new(T0)


def _todo(world: World, title: str = "read ch. 3") -> TodoItem:
    return world.add(TodoItem(id=f"todo_{title}", created_at=T0, updated_at=T0, title=title))


class TestStore:
    def test_put_get_list_roundtrip(self) -> None:
        w = _world()
        t = _todo(w)
        assert t.version == 1 and t.created_at == T0
        assert w.get(TodoItem, t.id) == t
        assert [x.id for x in w.list(TodoItem)] == [t.id]

    def test_duplicate_id_is_a_conflict(self) -> None:
        w = _world()
        _todo(w)
        with pytest.raises(ConflictError):
            _todo(w)

    def test_update_bumps_version_and_keeps_history(self) -> None:
        w = _world()
        t = _todo(w)
        w.advance(minutes=5)
        t2 = w.update(t.model_copy(update={"status": "done"}))
        assert t2.version == 2 and t2.updated_at == T0 + timedelta(minutes=5)
        hist = w.store.history(TodoItem, t.id)
        assert [h["op"] for h in hist] == ["create", "update"]
        assert hist[1]["record"]["status"] == "done"

    def test_stale_update_is_a_conflict(self) -> None:
        w = _world()
        t = _todo(w)
        w.update(t.model_copy(update={"status": "done"}))
        with pytest.raises(ConflictError):
            w.update(t.model_copy(update={"status": "cancelled"}))  # still version 1

    def test_delete_is_soft_and_logged(self) -> None:
        w = _world()
        t = _todo(w)
        w.remove(TodoItem, t.id)
        assert w.get(TodoItem, t.id) is None
        assert w.store.get(TodoItem, t.id, include_deleted=True) is not None
        assert w.store.history(TodoItem, t.id)[-1]["op"] == "delete"
        with pytest.raises(NotFoundError):
            w.update(t)

    def test_tracking_reports_touched_records(self) -> None:
        w = _world()
        with w.track() as touched:
            t = _todo(w)
            w.update(t.model_copy(update={"status": "done"}))
        assert touched == [f"todo/{t.id}"]

    def test_snapshot_and_restore_bytes_preserve_state_and_clock(self) -> None:
        w = _world()
        t = _todo(w)
        w.advance(hours=2)
        blob = w.snapshot_bytes()
        w.update(t.model_copy(update={"status": "done"}))
        w.advance(hours=1)
        w.restore_bytes(blob)
        assert w.get(TodoItem, t.id).status == "open"  # type: ignore[union-attr]
        assert w.now == T0 + timedelta(hours=2)

    def test_snapshot_to_file_and_reload(self, tmp_path) -> None:
        w = _world()
        _todo(w)
        w.set_skill_graph(SkillGraph(subject="x", skills=[Skill(id="a", name="A", subject="x")]))
        path = w.snapshot(tmp_path / "snap.db")
        w2 = World.from_snapshot(path)
        assert [t.id for t in w2.list(TodoItem)] == ["todo_read ch. 3"]
        assert w2.skill_graph.skills[0].id == "a"
        assert w2.now == T0

    def test_store_on_disk(self, tmp_path) -> None:
        s = Store(tmp_path / "w.db")
        s.kv_set("k", {"a": 1})
        s.close()
        s2 = Store(tmp_path / "w.db")
        assert s2.kv_get("k") == {"a": 1}


class TestClock:
    def test_clock_only_moves_forward(self) -> None:
        w = _world()
        w.advance(days=1)
        with pytest.raises(ValueError):
            w.set_time(T0)
        assert w.store.kv_get("clock.now") == (T0 + timedelta(days=1)).isoformat()


class TestWorldQueries:
    def test_scoped_preference_beats_global_and_newest_wins(self) -> None:
        w = _world()
        w.add(Preference(id="p1", created_at=T0, updated_at=T0, key="max_daily_minutes", value=90, stated_at=T0))
        w.add(Preference(id="p2", created_at=T0, updated_at=T0, key="max_daily_minutes", value=60,
                         scope="math101", stated_at=T0 + timedelta(days=1)))
        w.add(Preference(id="p3", created_at=T0, updated_at=T0, key="max_daily_minutes", value=120,
                         stated_at=T0 + timedelta(days=2)))
        assert w.preference("max_daily_minutes") == 120
        assert w.preference("max_daily_minutes", scope="math101") == 60
        assert w.preference("missing", default=7) == 7

    def test_calendar_conflicts_and_free_slots(self) -> None:
        w = _world()
        w.add(CalendarEvent(id="c1", created_at=T0, updated_at=T0, title="class",
                            start=datetime(2026, 11, 3, 18, 0), end=datetime(2026, 11, 3, 19, 0),
                            event_kind="class", fixed=True))
        assert [e.id for e in w.calendar_conflicts(datetime(2026, 11, 3, 18, 30), datetime(2026, 11, 3, 19, 30))] == ["c1"]
        assert w.calendar_conflicts(datetime(2026, 11, 3, 19, 0), datetime(2026, 11, 3, 20, 0)) == []
        slots = w.free_slots(datetime(2026, 11, 3), [TimeWindow(start="17:00", end="21:00")], min_minutes=30)
        assert slots == [(datetime(2026, 11, 3, 17, 0), datetime(2026, 11, 3, 18, 0)),
                         (datetime(2026, 11, 3, 19, 0), datetime(2026, 11, 3, 21, 0))]

    def test_profile_required(self) -> None:
        w = _world()
        with pytest.raises(NotFoundError):
            w.profile()
        w.add(StudentProfile(id="stu", created_at=T0, updated_at=T0, name="Dana", level="cc", program="algebra"))
        assert w.profile().name == "Dana"

    def test_mastery_map(self) -> None:
        w = _world()
        w.add(MasteryState(id="m1", created_at=T0, updated_at=T0, skill_id="a", mastery=0.4))
        assert w.mastery()["a"].mastery == 0.4

    def test_outage_flags(self) -> None:
        w = _world()
        assert w.tool_available("x")
        w.set_tool_outage("x", True)
        assert not w.tool_available("x")

    def test_calendar_event_validation(self) -> None:
        with pytest.raises(ValueError):
            CalendarEvent(id="bad", created_at=T0, updated_at=T0, title="x", start=T0, end=T0)

    def test_actor_enum_roundtrip(self) -> None:
        t = TodoItem(id="t", created_at=T0, updated_at=T0, title="x", created_by=Actor.AGENT)
        assert TodoItem.model_validate_json(t.model_dump_json()).created_by is Actor.AGENT
