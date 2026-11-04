"""Execute tool calls against a World with validation, permissions, approvals, idempotency
and a complete audit trail (one ToolCallRecord per call, including failures).
"""
from __future__ import annotations

import hashlib
import json
import time as _time
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ValidationError

from ..env.store import ConflictError, NotFoundError
from ..env.world import World
from ..schema import (
    ApprovalRequest,
    ApprovalStatus,
    LABModel,
    PermissionLevel,
    ToolCallRecord,
    new_id,
)
from .permissions import resolve_permission, unknown_target
from .registry import ToolRegistry, ToolSpec


class ToolResult(LABModel):
    tool: str
    ok: bool
    status: str                      # ok | error | pending_approval | denied | forbidden | outage | unknown_tool
    result: Any = None
    error: str | None = None
    record_id: str
    approval_request_id: str | None = None
    idempotent_replay: bool = False

    def for_agent(self) -> dict[str, Any]:
        """What the agent sees (never the raw exception or the audit row)."""
        out: dict[str, Any] = {"tool": self.tool, "status": self.status}
        if self.ok:
            out["result"] = self.result
        else:
            out["error"] = self.error
        if self.approval_request_id:
            out["approval_request_id"] = self.approval_request_id
        if self.idempotent_replay:
            out["note"] = "identical call already executed in this run; returning the earlier result"
        return out


class ToolContext:
    """Per-run state handed to tool functions."""

    def __init__(self, world: World, run_id: str, *, allowed_tools: list[str] | None = None,
                 learner_model: Any = None) -> None:
        self.world = world
        self.run_id = run_id
        self.allowed_tools = allowed_tools
        self.learner_model = learner_model
        self.step = 0

    @property
    def now(self) -> datetime:
        return self.world.now


class ToolExecutor:
    def __init__(self, registry: ToolRegistry, ctx: ToolContext) -> None:
        self.registry = registry
        self.ctx = ctx

    # -------------------------------------------------------------- public API
    def call(self, name: str, args: dict[str, Any] | None = None, *, idempotency_key: str | None = None) -> ToolResult:
        args = dict(args or {})
        world = self.ctx.world
        t0 = _time.perf_counter()
        rec_id = new_id("call")
        base: dict[str, Any] = dict(run_id=self.ctx.run_id, step=self.ctx.step, tool=name, args=args,
                    virtual_time=world.now, wall_time=datetime.now(), id=rec_id,
                    created_at=world.now, updated_at=world.now)

        def finish(**kw: Any) -> ToolResult:
            kw.setdefault("ok", False)
            status = kw.pop("_status", "ok" if kw["ok"] else "error")
            rec = ToolCallRecord(**{**base, **kw, "duration_ms": (_time.perf_counter() - t0) * 1000})
            world.store.put(rec, now=world.now)
            return ToolResult(tool=name, ok=rec.ok, status=status,
                              result=rec.result, error=rec.error, record_id=rec_id,
                              approval_request_id=rec.approval_request_id,
                              idempotent_replay=rec.idempotent_replay)

        # 1. tool exists and is allowed in this task
        if name not in self.registry or (self.ctx.allowed_tools is not None and name not in self.ctx.allowed_tools):
            return finish(error=f"unknown or unavailable tool: {name}", error_type="not_found", _status="unknown_tool")
        spec = self.registry.spec(name)
        # 2. outage
        if not world.tool_available(name):
            return finish(error=f"{name} is temporarily unavailable (service outage)", error_type="outage", _status="outage")
        # 3. validate params
        try:
            params = spec.params_model.model_validate(args)
        except ValidationError as exc:
            return finish(error=f"invalid arguments: {exc.errors(include_url=False)}", error_type="validation")
        tz_fields = _aware_datetime_fields(params)
        if tz_fields:
            return finish(error=f"invalid arguments: {tz_fields} carry a timezone suffix; use the student's local time "
                                f"without an offset, e.g. 2026-11-12T10:00:00", error_type="validation")
        norm_args = params.model_dump(mode="json")
        base["args"] = norm_args
        # 4. permission
        level, policy = resolve_permission(world, spec, norm_args)
        base["permission"] = level
        if spec.mutates and level == PermissionLevel.FORBIDDEN:
            return finish(error=f"{name} is not authorised for these arguments"
                                + (f" (policy: {policy.note})" if policy and policy.note else ""),
                          error_type="permission", _status="forbidden")
        approval_id: str | None = None
        if spec.mutates and level == PermissionLevel.REQUIRES_APPROVAL:
            missing = unknown_target(world, norm_args)
            if missing:
                return finish(error=missing, error_type="not_found")
            req = self._find_or_create_request(spec, norm_args)
            approval_id = req.id
            if req.status == ApprovalStatus.PENDING:
                return finish(error=f"{name} needs the student's approval; request {req.id} is pending. "
                                    "Wait for the decision, then call again with the same arguments.",
                              error_type="permission", _status="pending_approval", approval_request_id=req.id)
            if req.status in (ApprovalStatus.DENIED, ApprovalStatus.EXPIRED):
                return finish(error=f"the student {req.status.value} request {req.id} for {name}"
                                    + (f": {req.decision_note}" if req.decision_note else ""),
                              error_type="permission", _status="denied", approval_request_id=req.id)
        # 5. idempotency
        key = idempotency_key or self._derived_key(spec, norm_args)
        base["idempotency_key"] = key
        if spec.mutates and key:
            prior = self._prior_success(name, key)
            if prior is not None:
                return finish(ok=True, result=prior.result, idempotent_replay=True, mutated=False,
                              approval_request_id=approval_id)
        # 6. execute — atomically: a call that fails half-way must leave the world exactly as it was
        checkpoint = world.store.checkpoint() if spec.mutates else None
        try:
            with world.track() as touched:
                result = self.registry.fn(name)(self.ctx, params)
        except Exception as exc:
            if checkpoint is not None:
                world.store.restore_checkpoint(checkpoint)
            return finish(**_failure(name, exc))
        if checkpoint is not None:
            checkpoint.close()
        return finish(ok=True, result=_jsonable(result), mutated=bool(touched), records_touched=touched,
                      approval_request_id=approval_id)

    # ------------------------------------------------------------------ helpers
    def _find_or_create_request(self, spec: ToolSpec, args: dict[str, Any]) -> ApprovalRequest:
        world = self.ctx.world
        sig = _args_signature(args)
        for req in world.approvals():
            if req.tool == spec.name and _args_signature(req.args) == sig:
                return req
        req = ApprovalRequest(
            id=new_id("req", f"{self.ctx.run_id}|{spec.name}|{sig}"), created_at=world.now, updated_at=world.now,
            tool=spec.name, args=args, reason=f"{spec.name} requires approval", requested_at=world.now,
            step=self.ctx.step,
        )
        return world.add(req)

    def _derived_key(self, spec: ToolSpec, args: dict[str, Any]) -> str | None:
        if not spec.mutates:
            return None
        fields = spec.idempotency_fields or sorted(args)
        material = json.dumps({k: args.get(k) for k in fields}, sort_keys=True, default=str)
        return f"{spec.name}:{hashlib.sha1(material.encode()).hexdigest()[:12]}"

    def _prior_success(self, name: str, key: str) -> ToolCallRecord | None:
        for rec in self.ctx.world.tool_calls(self.ctx.run_id):
            if rec.tool == name and rec.idempotency_key == key and rec.ok and rec.mutated:
                return rec
        return None


def _failure(name: str, exc: Exception) -> dict[str, Any]:
    """Audit fields for a tool function that raised."""
    if isinstance(exc, NotFoundError):
        return {"error": str(exc), "error_type": "not_found"}
    if isinstance(exc, ConflictError):
        return {"error": str(exc), "error_type": "conflict"}
    if isinstance(exc, ToolError):
        return {"error": str(exc), "error_type": exc.error_type}
    return {"error": f"internal error in {name}: {type(exc).__name__}: {exc}", "error_type": "internal"}


class ToolError(Exception):
    """Raised by a tool function for a user-facing, non-internal failure."""

    def __init__(self, message: str, error_type: str = "validation") -> None:
        super().__init__(message)
        self.error_type = error_type


def _aware_datetime_fields(params: BaseModel, prefix: str = "") -> list[str]:
    """Names of datetime fields that carry tzinfo (the world is timezone-naive local time)."""
    out: list[str] = []
    for name, value in params.__dict__.items():
        if isinstance(value, datetime) and value.tzinfo is not None:
            out.append(prefix + name)
        elif isinstance(value, BaseModel):
            out.extend(_aware_datetime_fields(value, f"{prefix}{name}."))
        elif isinstance(value, list):
            for i, v in enumerate(value):
                if isinstance(v, BaseModel):
                    out.extend(_aware_datetime_fields(v, f"{prefix}{name}[{i}]."))
                elif isinstance(v, datetime) and v.tzinfo is not None:
                    out.append(f"{prefix}{name}[{i}]")
    return out


def _args_signature(args: dict[str, Any]) -> str:
    return json.dumps(args, sort_keys=True, default=str)


def _jsonable(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, list):
        return [_jsonable(v) for v in value]
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    if isinstance(value, datetime):
        return value.isoformat()
    return value
