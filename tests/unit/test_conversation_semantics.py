"""A tutoring session is a conversation: while the scripted student has lines left, a reply (plain text or finish)
is a tutor turn and the next line comes back. Without a script, a final message ends the run as it always did. And an
interrupted sweep run is started over instead of colliding with the database it left behind."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from learneragentbench.env import build_world
from learneragentbench.harness import sweep
from learneragentbench.harness.runner import run_one
from learneragentbench.runtime import ActionListAdapter, AgentLoop, RunSpec
from learneragentbench.runtime.adapters.openai_compatible import OpenAICompatibleAdapter
from learneragentbench.schema import Action, Observation, RunConfig
from learneragentbench.tasks import Dataset
from learneragentbench.tools import REGISTRY, ToolContext, ToolExecutor

DS = Dataset()
TUTORING = "C05_tutor_then_log_it"  # three scripted student lines
PLAIN = "D01_midterm_plan_from_rules"
CFG = RunConfig(model="scripted", adapter="scripted", output_dir="unused")


def _run(task_id: str, actions: list[Action], tmp_path: Path):
    return run_one(DS, task_id, "base", CFG, 0, out_root=tmp_path, adapter_factory=lambda c, t, w, e: ActionListAdapter(list(actions)))


def test_replies_continue_the_conversation_until_the_student_is_done(tmp_path: Path) -> None:
    replies = ["first reply", "second reply", "third reply", "last reply"]
    res = _run(TUTORING, [Action.final(r) for r in replies], tmp_path)
    t = res.trajectory
    assert t.status == "completed" and t.final_message == "last reply"
    assert [s.action.type for s in t.steps] == ["ask_user", "ask_user", "ask_user", "final"]
    assert [s.action.message for s in t.steps] == replies
    lines = DS.load_task(TUTORING).simulated_user.scripted_replies
    assert [s.observation.content for s in t.steps[1:]] == [{"student_says": x} for x in lines]
    by = {c.check_id: c for c in res.verdict.checks}
    assert by["every_line_answered"].passed is True


def test_silence_is_not_a_tutor_turn(tmp_path: Path) -> None:
    """An agent that stops talking leaves the student's remaining lines unanswered."""
    res = _run(TUTORING, [Action.final("One real reply to the first line.")], tmp_path)
    assert [s.action.message for s in res.trajectory.steps] == ["One real reply to the first line.", "", "", ""]
    by = {c.check_id: c for c in res.verdict.checks}
    assert by["every_line_answered"].passed is False and "1 tutor turns for 4" in by["every_line_answered"].evidence
    assert by["hint_at_first_miss"].passed is False


def test_ask_user_and_replies_consume_the_same_script(tmp_path: Path) -> None:
    res = _run(TUTORING, [Action.ask("q1"), Action.final("r2"), Action.ask("q3"), Action.final("end")], tmp_path)
    t = res.trajectory
    assert [s.action.type for s in t.steps] == ["ask_user", "ask_user", "ask_user", "final"]
    assert t.final_message == "end"


def test_a_task_without_a_script_ends_at_the_first_final_message(tmp_path: Path) -> None:
    res = _run(PLAIN, [Action.final("all done"), Action.final("never reached")], tmp_path)
    assert res.trajectory.status == "completed" and res.trajectory.final_message == "all done"
    assert [s.action.type for s in res.trajectory.steps] == ["final"]


def test_the_step_budget_still_ends_a_conversation(tmp_path: Path) -> None:
    t = DS.load_task(TUTORING)
    w = build_world(t.initial_state, DS.load_persona(t.persona_id), DS.load_graph(t.initial_state.skill_graph or "algebra"), task_id=t.task_id)
    ex = ToolExecutor(REGISTRY, ToolContext(w, run_id="r", allowed_tools=t.available_tools))
    spec = RunSpec(run_id="r", task_id=t.task_id, persona_id=t.persona_id, model="m", adapter="a", user_goal=t.user_goal, allowed_tools=t.available_tools,
                   max_steps=2, simulated_user=t.simulated_user)
    traj = AgentLoop(w, ex, ActionListAdapter([Action.final(str(i)) for i in range(9)]), spec, tmp_path).run()
    assert traj.status == "max_steps" and len(traj.steps) == 2


class _Fake:
    """An OpenAI-compatible client answering with a queue of plain texts or finish calls."""

    def __init__(self, replies):
        self.replies = list(replies)
        self.requests = []
        self.chat = self
        self.completions = self

    def create(self, **kw):
        self.requests.append(json.loads(json.dumps(kw["messages"], default=str)))
        kind, text = self.replies.pop(0)
        calls = None
        if kind == "finish":
            fn = type("F", (), {"name": "finish", "arguments": json.dumps({"summary": text})})
            calls = [type("C", (), {"id": f"call_{len(self.requests)}", "type": "function", "function": fn})]
        msg = type("M", (), {"content": None if calls else text, "tool_calls": calls, "reasoning_content": None})
        usage = type("U", (), {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2})
        return type("R", (), {"choices": [type("Ch", (), {"message": msg, "finish_reason": "stop"})], "usage": usage})


def test_the_model_sees_the_student_line_after_a_plain_reply_and_after_finish(tmp_path: Path) -> None:
    fake = _Fake([("text", "plain reply"), ("finish", "finish reply"), ("text", "third"), ("text", "last")])
    res = run_one(DS, TUTORING, "base", RunConfig(model="m", adapter="openai_compatible", output_dir="unused", adapter_params={"base_url": "http://x/v1"}), 0, out_root=tmp_path,
                  adapter_factory=lambda c, t, w, e: _with_client(fake))
    assert res.trajectory.status == "completed" and res.trajectory.final_message == "last"
    lines = DS.load_task(TUTORING).simulated_user.scripted_replies
    second, third = fake.requests[1], fake.requests[2]
    assert second[-1] == {"role": "user", "content": lines[0]}  # as written, not escaped JSON
    assert "—" in second[-1]["content"]
    # after a finish call the tool call is answered, so the history stays valid for a strict server
    assert third[-1]["role"] == "tool" and third[-1]["content"] == lines[1]
    assert third[-2]["tool_calls"][0]["id"] == third[-1]["tool_call_id"]


def test_a_notice_travels_with_the_student_line() -> None:
    ad = OpenAICompatibleAdapter(model="m", base_url="http://x/v1", api_key="k")
    ad.messages = []
    ad._last_tool_call_id = None
    ad._append_observation(Observation(type="user_message", content={"student_says": "2x = −6", "notices": ["rule changed"]}, step=1, virtual_time=datetime(2026, 11, 2)))
    assert ad.messages[-1]["content"].startswith("2x = −6\n\n") and "rule changed" in ad.messages[-1]["content"]


def _with_client(fake) -> OpenAICompatibleAdapter:
    ad = OpenAICompatibleAdapter(model="m", base_url="http://x/v1", api_key="k")
    ad.client = fake
    return ad


def test_sweep_restarts_a_run_that_was_interrupted(tmp_path: Path) -> None:
    exp = tmp_path / "e.yaml"
    exp.write_text("name: resume\nmodel: oracle\nadapter: oracle\ntasks: [D01_midterm_plan_from_rules]\nconditions: {oracle: {}}\n", encoding="utf-8")
    logs: list[str] = []
    rid = "resume__oracle__D01_midterm_plan_from_rules__base__s0__oracle"
    # what a killed run leaves behind: a populated world database and no verdict
    res = run_one(DS, "D01_midterm_plan_from_rules", "base", RunConfig(model="oracle", adapter="oracle", output_dir="unused"), 0, out_root=tmp_path / "resume", run_id=rid)
    assert (res.out_dir / "world.db").is_file()
    (res.out_dir / "verdict.json").unlink()
    out = sweep.run_sweep(exp, out_root=tmp_path, log=logs.append)
    assert out["done"] == 1 and out["failed"] == 0
    assert any("removed an unfinished earlier attempt" in m for m in logs)
    assert json.loads((res.out_dir / "verdict.json").read_text(encoding="utf-8"))["task_success"] is True
    # a finished run is never touched
    again = sweep.run_sweep(exp, out_root=tmp_path, log=logs.append)
    assert again["skipped"] == 1 and again["done"] == 0
