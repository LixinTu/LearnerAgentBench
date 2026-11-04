"""A policy with an ``expires_at`` in the past no longer grants or forbids anything: the resolver falls
through to the next matching policy (or the tool default). Virtual time, not wall time."""
from __future__ import annotations

import tempfile
from datetime import timedelta
from pathlib import Path

from learneragentbench.env import build_world
from learneragentbench.schema import AuthorizationPolicy, PermissionLevel
from learneragentbench.tasks import Dataset
from learneragentbench.tools import REGISTRY, ToolContext, ToolExecutor
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


def _executor(tmp: Path):
    world = _world(tmp)
    return world, ToolExecutor(REGISTRY, ToolContext(world, run_id="r"))


def test_a_message_to_someone_who_does_not_exist_is_not_a_question_of_approval(tmp_path: Path) -> None:
    """Models write `dr.cho` when the contact is `advisor_cho`. They used to be told to wait for the student's approval,
    and the student then denied a message to nobody, so the real problem never reached them."""
    world, ex = _executor(tmp_path)
    r = ex.call("send_message", {"to": "dr.cho", "subject": "s", "body": "b"})
    assert r.status == "error"
    assert "no contact dr.cho" in (r.error or "") and "get_student_profile" in (r.error or "")
    assert world.approvals() == []  # the student is not bothered


def test_a_real_contact_without_a_grant_still_needs_approval(tmp_path: Path) -> None:
    world, ex = _executor(tmp_path)
    spec = REGISTRY.spec("send_message")
    who = next(c.id for c in world.profile().contacts if resolve_permission(world, spec, {"to": c.id})[0] == PermissionLevel.REQUIRES_APPROVAL)
    r = ex.call("send_message", {"to": who, "subject": "s", "body": "b"})
    assert r.status == "pending_approval"
    assert len(world.approvals()) == 1


def test_booking_an_exam_that_does_not_exist_is_not_a_question_of_approval(tmp_path: Path) -> None:
    world, ex = _executor(tmp_path)
    r = ex.call("book_slot", {"kind": "exam_slot", "target_id": "exam_1234567890", "slot_start": "2026-11-20T09:00:00", "slot_end": "2026-11-20T11:00:00"})
    assert r.status == "error"
    assert "no assessment" in (r.error or "")
    assert world.approvals() == []


def test_a_forbidden_tool_stays_forbidden_whatever_it_names(tmp_path: Path) -> None:
    _, ex = _executor(tmp_path)
    r = ex.call("submit_assignment", {"assignment_id": "nothing_like_this", "content": "x"})
    assert r.status == "forbidden"
