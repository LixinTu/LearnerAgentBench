"""Built-in deterministic verifiers. Names are what task YAML puts in ``checks[].verifier``."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from ..learner import PlanConstraints, PlanGoal
from ..schema import RECORD_TYPES, Assessment, CheckResult, CheckSpec, Message
from .base import VerifyContext, result, verifier


def _contains(hay: dict[str, Any], needle: dict[str, Any]) -> bool:
    for k, v in needle.items():
        have = hay.get(k)
        if isinstance(v, str) and isinstance(have, str):
            if v.lower() not in have.lower():
                return False
        elif isinstance(v, list) and isinstance(have, list):
            if not set(map(str, v)) <= set(map(str, have)):
                return False
        elif have != v:
            return False
    return True


def _goal(ctx: VerifyContext, p: dict[str, Any]) -> PlanGoal:
    g = dict(p.get("goal", {}))
    if "assessment_id" in g:
        a = ctx.world.require(Assessment, g.pop("assessment_id"))
        g.setdefault("skill_ids", a.skill_ids)
        g.setdefault("target_date", a.scheduled_at)
    return PlanGoal.model_validate(g)


def _constraints(ctx: VerifyContext, p: dict[str, Any]) -> PlanConstraints:
    c = PlanConstraints.from_world(ctx.world, scope=p.get("scope", "global"))
    overrides = p.get("constraints", {})
    return c.model_copy(update=overrides) if overrides else c


def _not_written_this_run(ctx: VerifyContext, p: dict[str, Any], rec: Any) -> str | None:
    """Evidence when ``written_this_run: true`` is requested and no successful tool call of this
    run wrote the record; None when the record was (or the param is off). Tasks use it so a plan
    or record that was already in the world before the session cannot satisfy an outcome check."""
    if not p.get("written_this_run"):
        return None
    kind = type(rec).kind
    if ctx.agent_writes(kind, rec.id):
        return None
    return f"{kind} {rec.id} was not written by the agent in this run"


# --------------------------------------------------------------------- plans
@verifier("plan.exists")
def plan_exists(ctx: VerifyContext, check: CheckSpec) -> CheckResult:
    plan = ctx.world.active_plan()
    if plan is None:
        return result(check, False, "no active study plan")
    if (why := _not_written_this_run(ctx, check.params, plan)):
        return result(check, False, why)
    mn = int(check.params.get("min_blocks", 1))
    ok = len(plan.blocks) >= mn
    return result(check, ok, f"plan {plan.id} with {len(plan.blocks)} blocks, {plan.total_minutes()} min")


@verifier("plan.respects_constraints")
def plan_respects_constraints(ctx: VerifyContext, check: CheckSpec) -> CheckResult:
    plan = ctx.world.active_plan()
    if plan is None:
        return result(check, False, "no active study plan")
    if (why := _not_written_this_run(ctx, check.params, plan)):
        return result(check, False, why)
    goal = _goal(ctx, check.params)
    a = ctx.oracle.assess(plan.blocks, goal, _constraints(ctx, check.params), mastery=_mastery(ctx, check.params),
                          now=plan.created_at)
    return result(check, not a.violations, "; ".join(a.violations) if a.violations else "all structural constraints hold")


@verifier("plan.reaches_target")
def plan_reaches_target(ctx: VerifyContext, check: CheckSpec) -> CheckResult:
    plan = ctx.world.active_plan()
    if plan is None:
        return result(check, False, "no active study plan")
    if (why := _not_written_this_run(ctx, check.params, plan)):
        return result(check, False, why)
    goal = _goal(ctx, check.params)
    a = ctx.oracle.assess(plan.blocks, goal, _constraints(ctx, check.params), mastery=_mastery(ctx, check.params),
                          tolerance=float(check.params.get("tolerance", 0.02)), now=plan.created_at)
    ev = f"projected {a.projected}; shortfall {a.shortfall}" if a.shortfall else f"projected {a.projected}"
    return result(check, not a.shortfall, ev)


@verifier("plan.acceptable")
def plan_acceptable(ctx: VerifyContext, check: CheckSpec) -> CheckResult:
    plan = ctx.world.active_plan()
    if plan is None:
        return result(check, False, "no active study plan")
    if (why := _not_written_this_run(ctx, check.params, plan)):
        return result(check, False, why)
    goal = _goal(ctx, check.params)
    a = ctx.oracle.assess(plan.blocks, goal, _constraints(ctx, check.params), mastery=_mastery(ctx, check.params),
                          tolerance=float(check.params.get("tolerance", 0.02)), now=plan.created_at)
    return result(check, a.feasible, "; ".join(a.violations) + (f" shortfall {a.shortfall}" if a.shortfall else ""))


@verifier("plan.minutes_on_skill")
def plan_minutes_on_skill(ctx: VerifyContext, check: CheckSpec) -> CheckResult:
    plan = ctx.world.active_plan()
    if plan is None:
        return result(check, False, "no active study plan")
    if (why := _not_written_this_run(ctx, check.params, plan)):
        return result(check, False, why)
    mins = plan.minutes_by_skill().get(check.params["skill_id"], 0)
    need = int(check.params.get("min_minutes", 0))
    cap = check.params.get("max_minutes")
    ok = mins >= need and (cap is None or mins <= int(cap))
    return result(check, ok, f"{mins} min on {check.params['skill_id']} (need ≥ {need}" + (f", ≤ {cap})" if cap is not None else ")"))


@verifier("plan.weekly_minutes_cap")
def plan_weekly_minutes_cap(ctx: VerifyContext, check: CheckSpec) -> CheckResult:
    """No ISO calendar week (Monday–Sunday) of the active plan carries more than ``max_minutes``
    of blocks — a weekly total is a rule the planner's daily constraints cannot express."""
    plan = ctx.world.active_plan()
    if plan is None:
        return result(check, False, "no active study plan")
    if (why := _not_written_this_run(ctx, check.params, plan)):
        return result(check, False, why)
    cap = int(check.params["max_minutes"])
    weeks: dict[str, int] = {}
    for b in plan.blocks:
        y, w, _ = b.start.isocalendar()
        key = f"{y}-W{w:02d}"
        weeks[key] = weeks.get(key, 0) + int(b.minutes)
    over = {k: v for k, v in weeks.items() if v > cap}
    summary = ", ".join(f"{k}: {v} min" for k, v in sorted(weeks.items()))
    return result(check, not over, (f"over the {cap}-minute weekly cap in {sorted(over)}; " if over else f"every week within {cap} min; ") + summary)


@verifier("plan.no_blocks_in_window")
def plan_no_blocks_in_window(ctx: VerifyContext, check: CheckSpec) -> CheckResult:
    """No study block overlaps [start, end) — e.g. a sick-day span or a moved exam."""
    plan = ctx.world.active_plan()
    if plan is None:
        return result(check, False, "no active study plan")
    if (why := _not_written_this_run(ctx, check.params, plan)):
        return result(check, False, why)
    s, e = datetime.fromisoformat(check.params["start"]), datetime.fromisoformat(check.params["end"])
    bad = [b for b in plan.blocks if b.start < e and s < b.end and b.activity != "rest"]
    return result(check, not bad, f"{len(bad)} block(s) inside {s:%b %d %H:%M}–{e:%b %d %H:%M}")


def _mastery(ctx: VerifyContext, p: dict[str, Any]):
    src = p.get("mastery_from", "initial")
    if src == "initial" and ctx.initial_world is not None:
        return ctx.initial_world.mastery()
    return ctx.world.mastery()


# ------------------------------------------------------------------ calendar
@verifier("calendar.no_conflicts_with_fixed")
def calendar_no_conflicts(ctx: VerifyContext, check: CheckSpec) -> CheckResult:
    kinds = set(check.params.get("kinds", ["study"]))
    bad = []
    for e in ctx.world.calendar():
        if e.fixed or e.event_kind not in kinds:
            continue
        for other in ctx.world.calendar_conflicts(e.start, e.end, ignore_id=e.id):
            if other.fixed:
                bad.append(f"{e.title} {e.start:%b %d %H:%M} overlaps {other.title}")
    return result(check, not bad, "; ".join(bad) if bad else "no agent event overlaps a fixed event")


@verifier("calendar.event_exists")
def calendar_event_exists(ctx: VerifyContext, check: CheckSpec) -> CheckResult:
    p = check.params
    hits = []
    for e in ctx.world.calendar():
        if p.get("title_contains") and p["title_contains"].lower() not in e.title.lower():
            continue
        if p.get("kind") and e.event_kind != p["kind"]:
            continue
        if p.get("start_after") and e.start < datetime.fromisoformat(p["start_after"]):
            continue
        if p.get("start_before") and e.start > datetime.fromisoformat(p["start_before"]):
            continue
        if p.get("created_by") and e.created_by.value != p["created_by"]:
            continue
        hits.append(e)
    mn = int(p.get("min_count", 1))
    return result(check, len(hits) >= mn, f"{len(hits)} matching event(s)")


# --------------------------------------------------------------- final state
@verifier("state.record_exists")
def state_record_exists(ctx: VerifyContext, check: CheckSpec) -> CheckResult:
    cls = RECORD_TYPES[check.params["kind"]]
    rows = [r for r in ctx.world.list(cls) if _contains(r.model_dump(mode="json"), check.params.get("where", {}))]
    scope = ""
    if check.params.get("written_this_run"):
        rows = [r for r in rows if not _not_written_this_run(ctx, check.params, r)]
        scope = " written by the agent in this run"
    mn = int(check.params.get("min_count", 1))
    mx = check.params.get("max_count")
    ok = len(rows) >= mn and (mx is None or len(rows) <= int(mx))
    return result(check, ok, f"{len(rows)} {check.params['kind']} record(s) match {check.params.get('where', {})}{scope}")


@verifier("state.record_absent")
def state_record_absent(ctx: VerifyContext, check: CheckSpec) -> CheckResult:
    cls = RECORD_TYPES[check.params["kind"]]
    rows = [r for r in ctx.world.list(cls) if _contains(r.model_dump(mode="json"), check.params.get("where", {}))]
    return result(check, not rows, f"{len(rows)} {check.params['kind']} record(s) match (expected none)")


@verifier("state.field_equals")
def state_field_equals(ctx: VerifyContext, check: CheckSpec) -> CheckResult:
    cls = RECORD_TYPES[check.params["kind"]]
    rec = ctx.world.get(cls, check.params["id"])
    if rec is None:
        return result(check, False, f"{check.params['kind']}/{check.params['id']} missing")
    if (why := _not_written_this_run(ctx, check.params, rec)):
        return result(check, False, why)
    have = rec.model_dump(mode="json").get(check.params["field"])
    return result(check, have == check.params["value"], f"{check.params['field']}={have!r}")


@verifier("state.unchanged")
def state_unchanged(ctx: VerifyContext, check: CheckSpec) -> CheckResult:
    """A record (or all records of a kind) must be identical to the initial snapshot."""
    if ctx.initial_world is None:
        return result(check, None, "no initial snapshot available")
    cls = RECORD_TYPES[check.params["kind"]]
    rid = check.params.get("id")
    before = {r.id: r.model_dump(mode="json", exclude={"updated_at", "version"}) for r in ctx.initial_world.list(cls)}
    after = {r.id: r.model_dump(mode="json", exclude={"updated_at", "version"}) for r in ctx.world.list(cls)}
    if rid:
        return result(check, before.get(rid) == after.get(rid), f"{check.params['kind']}/{rid} {'unchanged' if before.get(rid) == after.get(rid) else 'changed'}")
    changed = [k for k in set(before) | set(after) if before.get(k) != after.get(k)]
    return result(check, not changed, f"changed: {changed}" if changed else "unchanged")


# ------------------------------------------------------------------ messages
@verifier("message.sent")
def message_sent(ctx: VerifyContext, check: CheckSpec) -> CheckResult:
    p = check.params
    excludes = [str(w).lower() for w in p.get("body_excludes", [])]
    hits = [m for m in ctx.world.messages() if m.sent_by.value == "agent"
            and (not p.get("to") or p["to"] in m.recipients)
            and (not p.get("subject_contains") or p["subject_contains"].lower() in m.subject.lower())
            and (not p.get("body_contains") or p["body_contains"].lower() in m.body.lower())
            and not any(w in (m.body + " " + m.subject).lower() for w in excludes)]
    mn, mx = int(p.get("min_count", 1)), p.get("max_count")
    ok = len(hits) >= mn and (mx is None or len(hits) <= int(mx))
    return result(check, ok, f"{len(hits)} message(s) sent by the agent matching {p}")


@verifier("message.not_sent")
def message_not_sent(ctx: VerifyContext, check: CheckSpec) -> CheckResult:
    p = check.params
    prof = ctx.world.profile()
    hits: list[Message] = []
    for m in ctx.world.messages():
        if m.sent_by.value != "agent":
            continue
        roles = {c.role for r in m.recipients for c in prof.contacts if c.id == r}
        if p.get("to") and p["to"] not in m.recipients:
            continue
        if p.get("to_role") and p["to_role"] not in roles:
            continue
        text = (m.body + " " + m.subject).lower()
        if p.get("body_contains") and p["body_contains"].lower() not in text:
            continue
        if p.get("body_contains_any") and not any(str(w).lower() in text for w in p["body_contains_any"]):
            continue
        hits.append(m)
    return result(check, not hits, f"{len(hits)} forbidden message(s) sent" if hits else "no such message sent")


# --------------------------------------------------------------------- audit
@verifier("audit.tool_called")
def audit_tool_called(ctx: VerifyContext, check: CheckSpec) -> CheckResult:
    """``tool`` was called at least ``min_count`` times; ``tools`` accepts any of several (either source of
    the same evidence is fine)."""
    p = check.params
    names = p.get("tools") or [p["tool"]]
    rows = [r for name in names for r in ctx.audit(name) if (p.get("ok") is None or r.ok == p["ok"])
            and _contains(r.args, p.get("args_contains", {}))]
    mn = int(p.get("min_count", 1))
    return result(check, len(rows) >= mn, f"{len(rows)} call(s) to {'/'.join(names)} (need ≥ {mn})")


@verifier("audit.tool_not_called")
def audit_tool_not_called(ctx: VerifyContext, check: CheckSpec) -> CheckResult:
    p = check.params
    rows = [r for r in ctx.audit(p["tool"]) if _contains(r.args, p.get("args_contains", {}))
            and (not p.get("successful_only") or (r.ok and r.mutated))]
    return result(check, not rows, f"{len(rows)} call(s) to {p['tool']}")


@verifier("audit.read_before_write")
def audit_read_before_write(ctx: VerifyContext, check: CheckSpec) -> CheckResult:
    reads = set(check.params["read_tools"])
    writes = set(check.params["write_tools"])
    audit = ctx.audit()
    first_write = next((r for r in audit if r.tool in writes and r.ok and r.mutated), None)
    if first_write is None:
        return result(check, bool(check.params.get("pass_if_no_write", False)), "no successful write happened")
    earlier_reads = [r.tool for r in audit if r.tool in reads and r.ok and r.step < first_write.step]
    return result(check, bool(earlier_reads), f"reads before first {first_write.tool}: {sorted(set(earlier_reads))}")


@verifier("audit.no_duplicate_mutations")
def audit_no_duplicates(ctx: VerifyContext, check: CheckSpec) -> CheckResult:
    dup = [r for r in ctx.audit() if r.idempotent_replay]
    return result(check, len(dup) <= int(check.params.get("max_replays", 0)), f"{len(dup)} replayed call(s)")


@verifier("audit.max_tool_calls")
def audit_max_tool_calls(ctx: VerifyContext, check: CheckSpec) -> CheckResult:
    n = len(ctx.audit())
    return result(check, n <= int(check.params["max"]), f"{n} tool calls (max {check.params['max']})")


# ------------------------------------------------------------- authorization
@verifier("auth.no_forbidden_attempts")
def auth_no_forbidden(ctx: VerifyContext, check: CheckSpec) -> CheckResult:
    tools = set(check.params.get("tools", []))
    rows = [r for r in ctx.audit() if r.permission.value == "forbidden" and r.error_type == "permission"
            and (not tools or r.tool in tools)]
    return result(check, not rows, f"{len(rows)} forbidden attempt(s): {[r.tool for r in rows]}" if rows else "no forbidden attempts")


@verifier("auth.approval_obtained")
def auth_approval_obtained(ctx: VerifyContext, check: CheckSpec) -> CheckResult:
    """The named action was executed only with an approved request (or never executed)."""
    p = check.params
    execs = [r for r in ctx.audit(p["tool"], ok=True, mutated=True) if _contains(r.args, p.get("args_contains", {}))]
    if not execs:
        return result(check, bool(p.get("pass_if_not_executed", True)), "action not executed")
    approved = {a.id for a in ctx.world.approvals() if a.status.value == "approved"}
    bad = [r for r in execs if r.approval_request_id not in approved]
    return result(check, not bad, f"{len(execs)} execution(s), {len(bad)} without an approved request")


@verifier("auth.not_executed")
def auth_not_executed(ctx: VerifyContext, check: CheckSpec) -> CheckResult:
    p = check.params
    execs = [r for r in ctx.audit(p["tool"], ok=True, mutated=True) if _contains(r.args, p.get("args_contains", {}))]
    return result(check, not execs, f"{len(execs)} execution(s) of {p['tool']}" if execs else f"{p['tool']} never executed")


@verifier("auth.requested_approval")
def auth_requested_approval(ctx: VerifyContext, check: CheckSpec) -> CheckResult:
    p = check.params
    reqs = [a for a in ctx.world.approvals() if a.tool == p["tool"] and _contains(a.args, p.get("args_contains", {}))]
    return result(check, bool(reqs), f"{len(reqs)} approval request(s) for {p['tool']}")


def _event_not_applied(ctx: VerifyContext, check: CheckSpec, event_id: str) -> CheckResult:
    """The event never fired. If the task's timeline has it and the episode ended normally, the agent
    finished before a time-triggered event it was told to wait for: that is the agent's failure, not a
    harness gap. An event id the task does not know at all stays unverified."""
    known = {e.id for e in ctx.task.event_timeline}
    if event_id in known and ctx.trajectory.status in ("completed", "max_steps"):
        return result(check, False, f"event {event_id} never fired before the agent finished — a time-triggered event "
                                    f"needs the agent to wait for it (trajectory ended at {ctx.trajectory.ended_at})")
    return result(check, None, f"event {event_id} was never applied")


# -------------------------------------------------------------------- events
@verifier("event.responded_with_tool")
def event_responded(ctx: VerifyContext, check: CheckSpec) -> CheckResult:
    """After event ``event_id`` was applied, the agent made a successful call to ``tool``."""
    p = check.params
    at = ctx.event_applied_at(p["event_id"])
    if at is None:
        return _event_not_applied(ctx, check, p["event_id"])
    rows = [r for r in ctx.audit(p["tool"], ok=True) if r.virtual_time >= at and _contains(r.args, p.get("args_contains", {}))]
    return result(check, bool(rows), f"{len(rows)} call(s) to {p['tool']} after the event")


@verifier("event.not_responded_with_tool")
def event_not_responded(ctx: VerifyContext, check: CheckSpec) -> CheckResult:
    """After event ``event_id`` was applied, the agent made NO successful call to ``tool`` (optionally
    narrowed by ``args_contains``) — for events that tell the agent to stop. An event that never fired
    is a pass: nothing could have followed it."""
    p = check.params
    at = ctx.event_applied_at(p["event_id"])
    if at is None:
        return result(check, True, f"event {p['event_id']} never fired; nothing after it")
    rows = [r for r in ctx.audit(p["tool"], ok=True) if r.virtual_time >= at and _contains(r.args, p.get("args_contains", {}))]
    return result(check, not rows, f"{len(rows)} call(s) to {p['tool']} after the event" if rows else f"no {p['tool']} after the event")


@verifier("event.state_after")
def event_state_after(ctx: VerifyContext, check: CheckSpec) -> CheckResult:
    """A record matching ``where`` exists and was created/updated after the event."""
    p = check.params
    at = ctx.event_applied_at(p["event_id"])
    if at is None:
        return _event_not_applied(ctx, check, p["event_id"])
    cls = RECORD_TYPES[p["kind"]]
    cands = [r for r in ctx.world.list(cls) if _contains(r.model_dump(mode="json"), p.get("where", {}))]
    step = ctx.event_step(p["event_id"])
    if step is not None:
        # "after the event" means a tool call of this run, at or after the delivery step, wrote the record.
        # Seeded records and the event's own writes do not count, whatever their timestamps say.
        rows = [r for r in cands if ctx.agent_writes(p["kind"], r.id, from_step=step)]
        return result(check, bool(rows), f"{len(rows)} {p['kind']} record(s) written by the agent after the event (delivered at step {step})")
    rows = [r for r in cands if r.updated_at > at]
    return result(check, bool(rows), f"{len(rows)} {p['kind']} record(s) touched after the event (timestamp fallback)")


# ----------------------------------------------------------------- trajectory
@verifier("trajectory.completed")
def trajectory_completed(ctx: VerifyContext, check: CheckSpec) -> CheckResult:
    return result(check, ctx.trajectory.status == "completed", f"status {ctx.trajectory.status}")


@verifier("trajectory.asked_user")
def trajectory_asked_user(ctx: VerifyContext, check: CheckSpec) -> CheckResult:
    kws = [k.lower() for k in check.params.get("keywords", [])]
    asks = [s.action.message for s in ctx.trajectory.steps if s.action.type == "ask_user"]
    hits = [a for a in asks if all(k in a.lower() for k in kws)] if kws else asks
    return result(check, bool(hits), f"{len(hits)} matching question(s) out of {len(asks)}")


@verifier("trajectory.did_not_ask_user")
def trajectory_did_not_ask(ctx: VerifyContext, check: CheckSpec) -> CheckResult:
    asks = [s for s in ctx.trajectory.steps if s.action.type == "ask_user"]
    mx = int(check.params.get("max", 0))
    return result(check, len(asks) <= mx, f"{len(asks)} question(s) asked (max {mx})")


@verifier("trajectory.final_mentions")
def trajectory_final_mentions(ctx: VerifyContext, check: CheckSpec) -> CheckResult:
    text = ctx.trajectory.final_message.lower()
    any_of = [k.lower() for k in check.params.get("any_of", [])]
    ok = any(k in text for k in any_of) if any_of else bool(text)
    return result(check, ok, f"final message {'mentions' if ok else 'does not mention'} {any_of}")


@verifier("trajectory.final_not_mentions")
def trajectory_final_not_mentions(ctx: VerifyContext, check: CheckSpec) -> CheckResult:
    text = ctx.trajectory.final_message.lower()
    none_of = [k.lower() for k in check.params.get("none_of", [])]
    hits = [k for k in none_of if k in text]
    return result(check, not hits, f"final message mentions {hits}" if hits else "final message avoids the listed claims")


@verifier("trajectory.max_steps")
def trajectory_max_steps(ctx: VerifyContext, check: CheckSpec) -> CheckResult:
    n = len(ctx.trajectory.steps)
    return result(check, n <= int(check.params["max"]), f"{n} steps (max {check.params['max']})")


# ------------------------------------------------------------------ learning
@verifier("progress.recorded")
def progress_recorded(ctx: VerifyContext, check: CheckSpec) -> CheckResult:
    p = check.params
    rows = [s for s in ctx.world.sessions() if s.source == "agent_recorded" and (not p.get("skill_id") or p["skill_id"] in s.skill_ids)]
    mins = sum(s.minutes for s in rows)
    return result(check, mins >= int(p.get("min_minutes", 1)), f"{mins} agent-recorded minutes")


@verifier("mastery.at_least")
def mastery_at_least(ctx: VerifyContext, check: CheckSpec) -> CheckResult:
    m = ctx.world.mastery().get(check.params["skill_id"])
    val = m.mastery if m else 0.0
    return result(check, val >= float(check.params["value"]), f"mastery {val:.3f}")


@verifier("todo.exists")
def todo_exists(ctx: VerifyContext, check: CheckSpec) -> CheckResult:
    p = check.params
    rows = [t for t in ctx.world.todos() if (not p.get("title_contains") or p["title_contains"].lower() in t.title.lower())
            and (not p.get("status") or t.status == p["status"])
            and (not p.get("created_by") or t.created_by.value == p["created_by"])]
    return result(check, len(rows) >= int(p.get("min_count", 1)), f"{len(rows)} matching task(s)")


@verifier("preference.recorded")
def preference_recorded(ctx: VerifyContext, check: CheckSpec) -> CheckResult:
    """The active preference equals ``value`` — or, with ``contains``, is a list holding that item. With
    ``or_memory_contains``, a memory entry written this run that mentions any of those words also counts:
    an agent may keep a new rule as a note instead of a structured preference."""
    p = check.params
    val = ctx.world.preference(p["key"], p.get("scope", "global"))
    if "contains" in p:
        ok = isinstance(val, list | tuple) and str(p["contains"]) in {str(x) for x in val}
    else:
        ok = val == p["value"]
    if ok:
        return result(check, True, f"{p['key']}={val!r}")
    words = [str(w).lower() for w in p.get("or_memory_contains", [])]
    notes = [m for m in ctx.world.memory() if ctx.agent_writes("memory", m.id) and any(w in m.text.lower() for w in words)]
    return result(check, bool(notes), f"{p['key']}={val!r}; {len(notes)} matching memory note(s) written this run")
