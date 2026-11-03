from __future__ import annotations

import json
from datetime import datetime
from types import SimpleNamespace
from typing import Any

import pytest

from learneragentbench.runtime import TaskView
from learneragentbench.runtime.adapter import AdapterError
from learneragentbench.runtime.adapters.openai_compatible import (
    META_TOOLS,
    OpenAICompatibleAdapter,
    _parse_json_action,
)
from learneragentbench.schema import Observation, SessionTranscript, SessionTurn

T0 = datetime(2026, 11, 2, 19, 0)


def _view(**kw: Any) -> TaskView:
    base = dict(run_id="r", task_id="t", variant_id="base", user_goal="Plan my week", now=T0, instructions="Be useful.",
                tools=[{"type": "function", "function": {"name": "get_preferences", "description": "d", "parameters": {"type": "object", "properties": {}}}}])
    base.update(kw)
    return TaskView(**base)


class FakeCompletions:
    def __init__(self, replies: list[dict[str, Any]]) -> None:
        self.replies = list(replies)
        self.calls: list[dict[str, Any]] = []

    def create(self, **kwargs: Any):
        self.calls.append(kwargs)
        if not self.replies:
            raise RuntimeError("boom")
        r = self.replies.pop(0)
        tool_calls = None
        if r.get("tool"):
            tool_calls = [SimpleNamespace(id="call_1", function=SimpleNamespace(name=r["tool"], arguments=json.dumps(r.get("args", {}))))]
        msg = SimpleNamespace(content=r.get("content"), tool_calls=tool_calls)
        return SimpleNamespace(choices=[SimpleNamespace(message=msg)], usage=SimpleNamespace(prompt_tokens=7, completion_tokens=3))


def _adapter(replies: list[dict[str, Any]], **kw: Any) -> tuple[OpenAICompatibleAdapter, FakeCompletions]:
    ad = OpenAICompatibleAdapter("fake-model", base_url="http://localhost:1/v1", retries=1, **kw)
    fake = FakeCompletions(replies)
    ad.client = SimpleNamespace(chat=SimpleNamespace(completions=fake))  # type: ignore[assignment]
    return ad, fake


def test_system_prompt_carries_memory_history_and_tools() -> None:
    ad, fake = _adapter([{"tool": "finish", "args": {"summary": "ok"}}])
    ad.start(_view(memory_notes=["no study after 22:00"], persona_summary="Dana",
                   history=[SessionTranscript(session_id="s1", started_at=T0, turns=[SessionTurn(role="student", text="hi")])]))
    action = ad.step(Observation(type="task", content={}, step=0, virtual_time=T0))
    assert action.type == "final" and action.message == "ok"
    sent = fake.calls[0]
    assert "no study after 22:00" in sent["messages"][0]["content"] and "student: hi" in sent["messages"][0]["content"]
    assert [t["function"]["name"] for t in sent["tools"]] == ["get_preferences", *[m["function"]["name"] for m in META_TOOLS]]
    assert ad.usage().prompt_tokens == 7 and ad.usage().calls == 1


def test_tool_calls_and_observations_round_trip() -> None:
    ad, _fake = _adapter([{"tool": "get_preferences", "args": {}}, {"tool": "ask_user", "args": {"question": "Which course?"}},
                         {"tool": "wait", "args": {"minutes": 30}}, {"content": "All done."}])
    ad.start(_view())
    a1 = ad.step(Observation(type="task", content={}, step=0, virtual_time=T0))
    assert a1.type == "tool_call" and a1.tool_call is not None and a1.tool_call.tool == "get_preferences"
    a2 = ad.step(Observation(type="tool_result", content={"result": []}, step=1, virtual_time=T0))
    assert a2.type == "ask_user" and a2.message == "Which course?"
    a3 = ad.step(Observation(type="user_message", content={"answer": "Algebra"}, step=2, virtual_time=T0))
    assert a3.type == "wait" and a3.wait_minutes == 30
    a4 = ad.step(Observation(type="event", content={"waited_minutes": 30}, step=3, virtual_time=T0))
    assert a4.type == "final" and a4.message == "All done."
    roles = [m["role"] for m in ad.messages]
    assert roles == ["system", "user", "assistant", "tool", "assistant", "tool", "assistant", "tool", "assistant"]


def test_malformed_arguments_and_api_failure() -> None:
    ad, _fake = _adapter([])
    ad.start(_view())
    with pytest.raises(AdapterError):
        ad.step(Observation(type="task", content={}, step=0, virtual_time=T0))
    ad2, _ = _adapter([{"tool": "get_preferences", "args": None}])
    ad2.start(_view())
    a = ad2.step(Observation(type="task", content={}, step=0, virtual_time=T0))
    assert a.type == "tool_call"


def test_json_fallback_parses_actions() -> None:
    assert _parse_json_action('I will do {"tool": "finish", "args": {"summary": "x"}} now') == ("finish", {"summary": "x"})
    assert _parse_json_action("no json here") is None
    ad, fake = _adapter([{"content": '{"tool": "get_preferences", "args": {}}'}], json_fallback=True)
    ad.start(_view())
    a = ad.step(Observation(type="task", content={}, step=0, virtual_time=T0))
    assert a.type == "tool_call" and "tools" not in fake.calls[0]


def test_state_round_trip_and_truncation() -> None:
    ad, _ = _adapter([{"tool": "finish", "args": {"summary": "ok"}}], max_history_chars=500)
    ad.start(_view())
    for i in range(30):
        ad.messages.append({"role": "user", "content": "x" * 100 + str(i)})
    ad.step(Observation(type="task", content={}, step=0, virtual_time=T0))
    assert sum(len(m["content"] or "") for m in ad.messages) < 1200
    state = ad.state()
    ad2, _ = _adapter([])
    ad2.start(_view())
    ad2.restore(state)
    assert ad2.messages == ad.messages and ad2.usage().calls == 1


def test_empty_reply_is_nudged_once_then_final() -> None:
    ad, fake = _adapter([{"content": ""}, {"tool": "finish", "args": {"summary": "done"}}])
    ad.start(_view())
    a = ad.step(Observation(type="task", content={}, step=0, virtual_time=T0))
    assert a.type == "final" and a.message == "done" and len(fake.calls) == 2
    assert any("Your reply was empty" in (m.get("content") or "") for m in fake.calls[1]["messages"])
    ad2, fake2 = _adapter([{"content": ""}, {"content": ""}])
    ad2.start(_view())
    a2 = ad2.step(Observation(type="task", content={}, step=0, virtual_time=T0))
    assert a2.type == "final" and a2.message == "(no summary)" and len(fake2.calls) == 2
