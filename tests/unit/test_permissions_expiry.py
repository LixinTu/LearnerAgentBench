"""A policy with an ``expires_at`` in the past no longer grants or forbids anything: the resolver falls
through to the next matching policy (or the tool default). Virtual time, not wall time."""
from __future__ import annotations

import tempfile
from datetime import timedelta
from pathlib import Path

from learneragentbench.env import build_world
from learneragentbench.schema import AuthorizationPolicy, PermissionLevel
from learneragentbench.tasks import Dataset
from learneragentbench.tools import REGISTRY
from learneragentbench.tools.permissions import resolve_permission

DS = Dataset()


def _world(tmp: Path):
    t = DS.load_task("D01_midterm_plan_from_rules")
    return build_world(t.initial_state, DS.load_persona("dana"), DS.load_graph("algebra"), path=tmp / "w.db", task_id=t.task_id)


def _grant(world, *, expires_delta: timedelta | None, pid: str) -> None:
    now = world.now
    # two scope keys: more specific than the persona's instructor rule, so it wins whenever it is valid
    world.add(AuthorizationPolicy(id=pid, created_at=now, updated_at=now, action="send_message", level=PermissionLevel.ALLOWED,
                                  scope={"recipient_role": "instructor", "recipient_id": "prof_kim"}, granted_at=now - timedelta(days=10),
                                  expires_at=(now + expires_delta) if expires_delta is not None else None, note="test grant"))


def test_expired_grant_is_ignored_and_valid_grant_applies() -> None:
    spec = REGISTRY.spec("send_message")
    args = {"to": "prof_kim", "subject": "s", "body": "b"}
    with tempfile.TemporaryDirectory() as d:
        w = _world(Path(d))
        baseline, _ = resolve_permission(w, spec, args)
        assert baseline == PermissionLevel.REQUIRES_APPROVAL  # Dana: ask before emailing teachers
        _grant(w, expires_delta=timedelta(days=-1), pid="pol_expired")
        level, pol = resolve_permission(w, spec, args)
        assert level == PermissionLevel.REQUIRES_APPROVAL and (pol is None or pol.id != "pol_expired")
    with tempfile.TemporaryDirectory() as d:
        w = _world(Path(d))
        _grant(w, expires_delta=timedelta(days=30), pid="pol_valid")
        level, pol = resolve_permission(w, spec, args)
        assert level == PermissionLevel.ALLOWED and pol is not None and pol.id == "pol_valid"


def test_grant_expires_as_virtual_time_advances() -> None:
    spec = REGISTRY.spec("send_message")
    args = {"to": "prof_kim", "subject": "s", "body": "b"}
    with tempfile.TemporaryDirectory() as d:
        w = _world(Path(d))
        _grant(w, expires_delta=timedelta(hours=2), pid="pol_short")
        assert resolve_permission(w, spec, args)[0] == PermissionLevel.ALLOWED
        w.advance(minutes=180, reason="test")
        assert resolve_permission(w, spec, args)[0] == PermissionLevel.REQUIRES_APPROVAL
