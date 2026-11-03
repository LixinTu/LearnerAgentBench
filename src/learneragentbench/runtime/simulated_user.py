"""The simulated student: answers clarifying questions and decides approval requests, by rules
declared in the task (``SimulatedUserSpec``). Deterministic."""
from __future__ import annotations

import json
from typing import Any

from ..env import apply_event
from ..env.world import World
from ..schema import ApprovalStatus, EventKind, ScheduledEvent, SimulatedUserSpec


class SimulatedUser:
    def __init__(self, spec: SimulatedUserSpec, world: World) -> None:
        self.spec = spec
        self.world = world

    # -------------------------------------------------------------- questions
    def next_scripted(self) -> str | None:
        """The student's next scripted line, or None when the script is finished (or there is none)."""
        i = int(self.world.store.kv_get("sim_user.script_index", 0))
        if i < len(self.spec.scripted_replies):
            self.world.store.kv_set("sim_user.script_index", i + 1)
            return self.spec.scripted_replies[i]
        return None

    def answer(self, question: str) -> str:
        scripted = self.next_scripted()
        if scripted is not None:
            return scripted
        q = question.lower()
        for rule in self.spec.clarifications:
            if all(k.lower() in q for k in rule.keywords):
                return rule.answer
        return self.spec.default_clarification

    # -------------------------------------------------------------- approvals
    def process_approvals(self, step: int) -> list[str]:
        """Schedule decisions for new pending requests and apply the ones that are due.
        Returns notices for the agent."""
        notices: list[str] = []
        schedule: dict[str, dict[str, Any]] = self.world.store.kv_get("approval_schedule", {})
        for req in self.world.approvals():
            if req.status != ApprovalStatus.PENDING:
                continue
            if req.id not in schedule:
                rule = self._rule_for(req.tool, req.args)
                decision = rule.decision if rule else self.spec.default_approval
                delay = rule.delay_steps if rule else 0
                note = rule.note if rule else ""
                schedule[req.id] = {"decision": decision, "due_step": step + delay, "note": note}
            entry = schedule[req.id]
            if entry["decision"] == "ignore" or step < entry["due_step"] or entry.get("applied"):
                continue
            apply_event(self.world, ScheduledEvent(
                id=f"approval_{req.id}", event_kind=EventKind.APPROVAL_DECISION, after_step=step,
                payload={"request_id": req.id, "decision": "approved" if entry["decision"] == "approve" else "denied",
                         "note": entry["note"], "decided_by": "student"}, notify=False))
            entry["applied"] = True
            verb = "approved" if entry["decision"] == "approve" else "denied"
            notices.append(f"The student {verb} your request {req.id} ({req.tool} {json.dumps(req.args, default=str)[:120]})"
                           + (f": {entry['note']}" if entry["note"] else ""))
        self.world.store.kv_set("approval_schedule", schedule)
        return notices

    def _rule_for(self, tool: str, args: dict[str, Any]):
        for rule in self.spec.approval_rules:
            if rule.tool not in (None, tool):
                continue
            if all(str(args.get(k)) == str(v) or (isinstance(args.get(k), str) and str(v).lower() in str(args.get(k)).lower())
                   for k, v in rule.args_contains.items()):
                return rule
        return None
