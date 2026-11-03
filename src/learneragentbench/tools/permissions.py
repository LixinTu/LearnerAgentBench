"""Resolve what the agent may do: policies in the world override tool defaults.

A policy matches a call when its ``action`` is the tool name (or ``*``) and every key in its
``scope`` matches the call. Supported scope keys:

    recipient_role   role of the contact in ``to`` (send_message)
    recipient_id     contact id in ``to``
    course_id        course of the assignment / assessment
    max_amount       amount <= max (purchase)
    event_kind       calendar event kind

The most specific matching policy (most scope keys) wins; ties go to the most recent. A policy
whose ``expires_at`` has passed (virtual time) is ignored.
"""
from __future__ import annotations

from typing import Any

from ..env.world import World
from ..schema import AuthorizationPolicy, PermissionLevel
from .registry import ToolSpec


def _scope_matches(scope: dict[str, Any], facts: dict[str, Any]) -> bool:
    for key, want in scope.items():
        if key == "max_amount":
            if facts.get("amount") is None or float(facts["amount"]) > float(want):
                return False
            continue
        have = facts.get(key)
        if isinstance(want, list):
            if have not in want:
                return False
        elif have != want:
            return False
    return True


def call_facts(world: World, tool: str, args: dict[str, Any]) -> dict[str, Any]:
    """Facts about a call that policies can be scoped on."""
    facts: dict[str, Any] = dict(args)
    to = args.get("to")
    if isinstance(to, str):
        contact = world.profile().contact(to) if world.list(type(world.profile())) else None
        facts["recipient_id"] = to
        facts["recipient_role"] = contact.role if contact else "unknown"
    if "assignment_id" in args:
        from ..schema import Assignment
        a = world.get(Assignment, str(args["assignment_id"]))
        if a is not None:
            facts["course_id"] = a.course_id
    if "assessment_id" in args:
        from ..schema import Assessment
        a2 = world.get(Assessment, str(args["assessment_id"]))
        if a2 is not None:
            facts["course_id"] = a2.course_id
    return facts


def resolve_permission(world: World, spec: ToolSpec, args: dict[str, Any]) -> tuple[PermissionLevel, AuthorizationPolicy | None]:
    facts = call_facts(world, spec.name, args)
    best: AuthorizationPolicy | None = None
    for pol in world.policies():
        if pol.action not in (spec.name, "*"):
            continue
        if pol.expires_at is not None and pol.expires_at <= world.now:
            continue  # a grant with an expiry is gone once the clock passes it
        if not _scope_matches(pol.scope, facts):
            continue
        if best is None or len(pol.scope) > len(best.scope) or (
            len(pol.scope) == len(best.scope) and pol.granted_at > best.granted_at
        ):
            best = pol
    if best is None:
        return spec.default_permission, None
    return best.level, best
