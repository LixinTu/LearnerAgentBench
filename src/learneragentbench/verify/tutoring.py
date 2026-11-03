"""Tutoring-policy verifier (family C): replays a scripted student session against the tutor's
messages and checks a state-dependent hint policy — the same mechanism as the S1 study in
`education-agent-research/s1-eval`, generalised to task parameters.

The tutor's turns are the agent's `ask_user` messages followed by its `final` message, in
order; the student's lines are the task's ``scripted_replies``. Tutor turn *i* answers student
line *i* (line 0 is the user_goal). Everything is regex-based and the evidence is reported.

check params::

    policy: {hint_after_failures: 2, idk_counts_as_attempt: false, no_answer_unless_asked: true,
             show_answer_after_failures: null}
    problems: {P1: {answer: [...regex], intermediate: [...], procedural: [...], conceptual: [...], steps: [...]}}
    script: [{id: P1-A1, kind: attempt|idk|correct|explicit_request, problem: P1}, ...]
    aspect: one of answer_leak | hint_due | hint_early | confirmation | explicit_request | turn_count
    policy_after_event: {event_id: rule_change, policy: {...}}   # optional: the policy for every
        tutor turn taken at or after the loop step at which that event was delivered (a rule that
        changes mid-session); turns before it, and all turns if it never fired, use ``policy``
"""
from __future__ import annotations

import re
from typing import Any

from ..schema import CheckResult, CheckSpec
from .base import VerifyContext, result, verifier

CONFIRM_RE = r"\b(?:correct|right|exactly|yes|well\s+done|nice\s+work|great\s+job|that's\s+it|nailed\s+it|spot\s+on|you\s+got\s+it|perfect|good\s+job)\b"
CONTRADICT_RE = r"\b(?:not\s+quite|not\s+right|incorrect|wrong|try\s+again|doesn't\s+work|isn't\s+right)\b"


def _hits(patterns: list[str], text: str) -> list[str]:
    out = []
    for pat in patterns:
        out += [" ".join(m.group(0).split()) for m in re.finditer(pat, text, re.IGNORECASE)]
    return out


def tutor_turns(ctx: VerifyContext) -> list[str]:
    turns = [s.action.message for s in ctx.trajectory.steps if s.action.type == "ask_user"]
    if ctx.trajectory.status == "completed":
        turns.append(ctx.trajectory.final_message)
    return turns


def tutor_turn_steps(ctx: VerifyContext) -> list[int]:
    """Loop step of each tutor turn (parallel to ``tutor_turns``)."""
    steps = [s.index for s in ctx.trajectory.steps if s.action.type == "ask_user"]
    if ctx.trajectory.status == "completed" and ctx.trajectory.steps:
        steps.append(ctx.trajectory.steps[-1].index)
    return steps


def policy_for_turns(ctx: VerifyContext, params: dict[str, Any]) -> list[dict[str, Any]]:
    """The policy in force at each tutor turn: ``policy`` until the switch event is delivered, then
    ``policy_after_event.policy`` (merged over the base) for turns at or after that step."""
    base = dict(params.get("policy", {}))
    switch = params.get("policy_after_event")
    steps = tutor_turn_steps(ctx)
    if not switch:
        return [base for _ in steps]
    ev_step = ctx.event_step(switch["event_id"])
    later = {**base, **dict(switch.get("policy", {}))}
    return [later if (ev_step is not None and st >= ev_step) else base for st in steps]


def replay(ctx: VerifyContext, params: dict[str, Any]) -> dict[str, Any]:
    """Walk the script and return per-turn findings."""
    policy = params.get("policy", {})
    problems = params["problems"]
    script = params["script"]
    turns = tutor_turns(ctx)
    per_turn = policy_for_turns(ctx, params)
    fails: dict[str, int] = {}
    solved: dict[str, bool] = {}
    allowed: dict[str, bool] = {}
    findings: list[dict[str, Any]] = []
    for i, line in enumerate(script):
        pid, kind = line["problem"], line["kind"]
        reply = turns[i] if i < len(turns) else None
        pol = per_turn[i] if i < len(per_turn) else policy
        hint_after = int(pol.get("hint_after_failures", 2))
        idk_counts = bool(pol.get("idk_counts_as_attempt", False))
        show_after = pol.get("show_answer_after_failures")
        if kind == "attempt" or (kind == "idk" and idk_counts):
            fails[pid] = fails.get(pid, 0) + 1
        elif kind == "correct":
            solved[pid] = True
        elif kind == "explicit_request":
            allowed[pid] = True
        if reply is None:
            n_fail_m = fails.get(pid, 0)
            findings.append({"id": line["id"], "kind": kind, "problem": pid, "missing": True,
                             "hint_due": n_fail_m >= hint_after and not solved.get(pid, False),
                             "answer_allowed": allowed.get(pid, False) or solved.get(pid, False)
                             or (show_after is not None and n_fail_m >= int(show_after))})
            continue
        prob = problems[pid]
        f: dict[str, Any] = {"id": line["id"], "kind": kind, "problem": pid, "missing": False,
                             "answer": _hits(prob.get("answer", []), reply),
                             "intermediate": _hits(prob.get("intermediate", []), reply),
                             "procedural": _hits(prob.get("procedural", []), reply),
                             "conceptual": _hits(prob.get("conceptual", []), reply),
                             "steps": _hits(prob.get("steps", []), reply),
                             "confirm": _hits([CONFIRM_RE], reply), "contradict": _hits([CONTRADICT_RE], reply)}
        n_fail = fails.get(pid, 0)
        answer_due = allowed.get(pid, False) or solved.get(pid, False) or (show_after is not None and n_fail >= int(show_after))
        if prob.get("homework") and not solved.get(pid, False):
            answer_due = False  # school policy: never the final answer on homework, even when asked
        hint_due = n_fail >= hint_after and not solved.get(pid, False)
        f["answer_allowed"] = answer_due
        f["hint_due"] = hint_due
        f["policy"] = {"hint_after_failures": hint_after, "show_answer_after_failures": show_after, "idk_counts_as_attempt": idk_counts}
        f["leak"] = bool(f["answer"]) and not answer_due
        f["early_hint"] = (not hint_due) and kind in ("attempt", "idk") and bool(f["procedural"] or f["intermediate"]) and not answer_due
        f["hint_present"] = bool(f["procedural"])
        findings.append(f)
    return {"turns": len(turns), "expected_turns": len(script), "findings": findings}


@verifier("tutoring.hint_policy")
def tutoring_hint_policy(ctx: VerifyContext, check: CheckSpec) -> CheckResult:
    rep = replay(ctx, check.params)
    aspect = check.params.get("aspect", "answer_leak")
    fs = rep["findings"]
    if aspect == "turn_count":
        ok = rep["turns"] >= rep["expected_turns"]
        return result(check, ok, f"{rep['turns']} tutor turns for {rep['expected_turns']} student lines")
    if aspect == "answer_leak":
        bad = [f["id"] for f in fs if not f.get("missing") and f.get("leak")]
        return result(check, not bad, f"final answer stated early at {bad}" if bad else "no early final answer")
    if aspect == "hint_due":
        due = [f for f in fs if f.get("hint_due") and f["kind"] == "attempt"]
        missing = [f["id"] for f in due if f.get("missing") or not f.get("hint_present")]
        if not due:
            return result(check, None, "no turn where a hint was due")
        return result(check, not missing, f"hint missing at {missing}" if missing else f"hint present at {[f['id'] for f in due]}")
    if aspect == "hint_early":
        early = [f["id"] for f in fs if not f.get("missing") and f.get("early_hint")]
        return result(check, not early, f"step-level hint before due at {early}" if early else "no premature hint")
    if aspect == "confirmation":
        corr = [f for f in fs if f["kind"] == "correct"]
        bad = [f["id"] for f in corr if f.get("missing") or (f["contradict"] and not f["confirm"]) or (not f["confirm"] and not f["contradict"])]
        if not corr:
            return result(check, None, "script has no correct attempt")
        return result(check, not bad, f"correct answer not confirmed at {bad}" if bad else "correct answers confirmed")
    if aspect == "forbidden_words":
        words = [w.lower() for w in check.params.get("policy", {}).get("forbidden_words", [])]
        bad = []
        for f, turn in zip(fs, tutor_turns(ctx), strict=False):
            hits = [w for w in words if re.search(rf"\b{re.escape(w)}\b", turn, re.IGNORECASE)]
            if hits:
                bad.append(f"{f['id']}:{hits}")
        return result(check, not bad, f"forbidden words used at {bad}" if bad else "no forbidden words")
    if aspect == "homework_answer_withheld":
        hw = [f for f in fs if f["kind"] == "explicit_request" and check.params["problems"][f["problem"]].get("homework")]
        if not hw:
            return result(check, None, "script has no explicit request on a homework problem")
        bad = [f["id"] for f in hw if f.get("missing") or f.get("answer")]
        return result(check, not bad, f"homework answer given at {bad}" if bad else "homework answer withheld even when asked")
    if aspect == "explicit_request":
        req = [f for f in fs if f["kind"] == "explicit_request" and not check.params["problems"][f["problem"]].get("homework")]
        if not req:
            return result(check, None, "script has no explicit request")
        bad = [f["id"] for f in req if f.get("missing") or not (f["answer"] and f["steps"])]
        return result(check, not bad, f"full solution not given at {bad}" if bad else "full solution given on request")
    if aspect == "answer_shown":
        show_after = check.params.get("policy", {}).get("show_answer_after_failures")
        if show_after is None:
            return result(check, None, "policy has no show_answer_after_failures")
        due = [f for f in fs if f["kind"] == "attempt" and f.get("answer_allowed")]
        if not due:
            return result(check, None, "no turn where the answer was due")
        bad = [f["id"] for f in due if f.get("missing") or not (f["answer"] and f["steps"])]
        return result(check, not bad, f"worked solution missing at {bad}" if bad else f"worked solution shown at {[f['id'] for f in due]}")
    if aspect == "missing_turns":
        miss = [f["id"] for f in fs if f.get("missing")]
        return result(check, not miss, f"no tutor reply for {miss}" if miss else "every student line was answered")
    return result(check, None, f"unknown aspect {aspect!r}")
