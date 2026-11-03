"""An adapter for any endpoint that speaks the OpenAI chat-completions API with tool calling:
local Ollama / vLLM / llama.cpp servers or hosted models. No key is required for local
servers. The adapter never calls an endpoint unless it is constructed, so importing it is
free of side effects.

Three meta tools are exposed to the model in addition to the task's tools:
    ask_user(question)   -> Action.ask
    wait(minutes)        -> Action.wait
    finish(summary)      -> Action.final
A reply with no tool call is treated as ``finish`` with the reply text.
"""
from __future__ import annotations

import json
import time
from typing import Any

from ...schema import Action, ModelUsage, Observation, ToolCall
from ..adapter import AdapterError, TaskView

META_TOOLS: list[dict[str, Any]] = [
    {"type": "function", "function": {"name": "ask_user", "description": "Ask the student one clarifying question and wait for the answer.",
                                      "parameters": {"type": "object", "properties": {"question": {"type": "string"}}, "required": ["question"]}}},
    {"type": "function", "function": {"name": "wait", "description": "Let virtual time pass (e.g. to wait for an approval or a reply).",
                                      "parameters": {"type": "object", "properties": {"minutes": {"type": "integer", "minimum": 1, "default": 60}}}}},
    {"type": "function", "function": {"name": "finish", "description": "End the task with a short summary of what you did and what is pending.",
                                      "parameters": {"type": "object", "properties": {"summary": {"type": "string"}}, "required": ["summary"]}}},
]


class OpenAICompatibleAdapter:
    name = "openai_compatible"

    def __init__(self, model: str, *, base_url: str | None = None, api_key: str | None = None,
                 temperature: float = 0.0, max_tokens: int = 1024, max_history_chars: int = 60_000,
                 retries: int = 3, timeout: float = 180.0, extra_body: dict[str, Any] | None = None,
                 json_fallback: bool = False, seed: int | None = None) -> None:
        try:
            from openai import OpenAI
        except ImportError as exc:  # pragma: no cover
            raise AdapterError("the 'openai' package is required: uv pip install -e '.[llm]'") from exc
        self.model = model
        self.client = OpenAI(base_url=base_url, api_key=api_key or "not-needed", timeout=timeout)
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.max_history_chars = max_history_chars
        self.retries = retries
        self.extra_body = extra_body or {}
        self.json_fallback = json_fallback
        self.seed = seed
        self.messages: list[dict[str, Any]] = []
        self.tools: list[dict[str, Any]] = []
        self._usage = ModelUsage()
        self._last_tool_call_id: str | None = None
        self._nudged = False

    # ------------------------------------------------------------------ setup
    def start(self, view: TaskView) -> None:
        self.tools = [*view.tools, *META_TOOLS]
        system = view.instructions
        if view.persona_summary:
            system += f"\n\nAbout the student: {view.persona_summary}"
        if view.memory_notes:
            system += "\n\nWhat you remember from earlier sessions:\n" + "\n".join(f"- {m}" for m in view.memory_notes)
        if view.history:
            system += "\n\nTranscripts of earlier sessions:\n" + "\n".join(
                f"[{h.session_id} {h.started_at:%Y-%m-%d}] " + " / ".join(f"{t.role}: {t.text}" for t in h.turns)
                for h in view.history)
        system += f"\n\nToday is {view.now:%A %Y-%m-%d %H:%M}. You have at most {view.max_steps} steps."
        if self.json_fallback:
            system += ("\n\nRespond ONLY with a JSON object: {\"tool\": <name>, \"args\": {...}} using one of the "
                       "listed tools (including ask_user, wait, finish).\nTools:\n" + json.dumps(self.tools))
        self.messages = [{"role": "system", "content": system},
                         {"role": "user", "content": view.user_goal}]

    # ------------------------------------------------------------------- step
    def step(self, observation: Observation) -> Action:
        if observation.type != "task":
            self._append_observation(observation)
        self._truncate()
        resp = self._complete()
        choice = resp.choices[0]
        msg = choice.message
        if getattr(resp, "usage", None):
            self._usage.prompt_tokens += getattr(resp.usage, "prompt_tokens", 0) or 0
            self._usage.completion_tokens += getattr(resp.usage, "completion_tokens", 0) or 0
        self._usage.calls += 1
        tool_calls = list(getattr(msg, "tool_calls", None) or [])
        content = msg.content or ""
        if tool_calls:
            tc = tool_calls[0]
            self.messages.append({"role": "assistant", "content": content or None,
                                  "tool_calls": [{"id": tc.id, "type": "function",
                                                  "function": {"name": tc.function.name, "arguments": tc.function.arguments}}]})
            self._last_tool_call_id = tc.id
            try:
                args = json.loads(tc.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {"_raw": tc.function.arguments}
            if not isinstance(args, dict):
                args = {} if args is None else {"_raw": args}
            return self._to_action(tc.function.name, args, content)
        self.messages.append({"role": "assistant", "content": content})
        self._last_tool_call_id = None
        if self.json_fallback:
            parsed = _parse_json_action(content)
            if parsed is not None:
                return self._to_action(parsed[0], parsed[1], "")
        if not content.strip() and not self._nudged:
            # An empty reply is almost always a formatting slip, not a decision to stop: ask once.
            self._nudged = True
            self.messages.append({"role": "user", "content": "Your reply was empty. Continue: call a tool, ask the "
                                  "student with ask_user, or call finish with a summary of what you did."})
            return self.step(Observation(type="task", content={}, step=observation.step, virtual_time=observation.virtual_time))
        self._nudged = False
        return Action.final(content.strip() or "(no summary)")

    def _to_action(self, name: str, args: dict[str, Any], reasoning: str) -> Action:
        if name == "finish":
            return Action(type="final", message=str(args.get("summary", "")), reasoning=reasoning)
        if name == "ask_user":
            return Action(type="ask_user", message=str(args.get("question", "")), reasoning=reasoning)
        if name == "wait":
            return Action(type="wait", wait_minutes=int(args.get("minutes", 60) or 60), reasoning=reasoning)
        return Action(type="tool_call", tool_call=ToolCall(tool=name, args=args), reasoning=reasoning)

    def _append_observation(self, obs: Observation) -> None:
        content = dict(obs.content) if isinstance(obs.content, dict) else obs.content
        line = content.pop("student_says", None) if isinstance(content, dict) else None
        if line is not None:
            # The student's own words, as written: JSON would turn "2x = −6" into "2x = \\u22126".
            text = f"{line}\n\n{json.dumps(content, default=str)}" if content else str(line)
        else:
            text = json.dumps(obs.content, default=str)
        if self._last_tool_call_id and obs.type in ("tool_result", "tool_error"):
            self.messages.append({"role": "tool", "tool_call_id": self._last_tool_call_id, "content": text})
        elif self._last_tool_call_id:
            # a meta tool (ask_user / wait) was called; close it with a tool message
            self.messages.append({"role": "tool", "tool_call_id": self._last_tool_call_id, "content": text})
        else:
            self.messages.append({"role": "user", "content": text})
        self._last_tool_call_id = None

    def _truncate(self) -> None:
        total = sum(len(str(m.get("content") or "")) for m in self.messages)
        while total > self.max_history_chars and len(self.messages) > 4:
            removed = self.messages.pop(2)
            total -= len(str(removed.get("content") or ""))
            # keep tool_call / tool pairs consistent
            if removed.get("tool_calls") and len(self.messages) > 2 and self.messages[2].get("role") == "tool":
                total -= len(str(self.messages.pop(2).get("content") or ""))

    def _complete(self):
        last: Exception | None = None
        for attempt in range(self.retries):
            try:
                kwargs: dict[str, Any] = dict(model=self.model, messages=self.messages, temperature=self.temperature,
                                              max_tokens=self.max_tokens)
                if self.tools and not self.json_fallback:
                    kwargs["tools"] = self.tools
                if self.seed is not None:
                    kwargs["seed"] = int(self.seed)
                if self.extra_body:
                    kwargs["extra_body"] = self.extra_body
                return self.client.chat.completions.create(**kwargs)
            except Exception as exc:
                last = exc
                time.sleep(min(2 ** attempt, 8))
        raise AdapterError(f"model call failed after {self.retries} attempts: {type(last).__name__}: {last}")

    # ------------------------------------------------------------------ state
    def state(self) -> dict[str, Any]:
        return {"messages": self.messages, "usage": self._usage.model_dump(), "last_tool_call_id": self._last_tool_call_id}

    def restore(self, state: dict[str, Any]) -> None:
        self.messages = list(state.get("messages", self.messages))
        self._usage = ModelUsage.model_validate(state.get("usage", {}))
        self._last_tool_call_id = state.get("last_tool_call_id")

    def usage(self) -> ModelUsage:
        return self._usage


def _parse_json_action(text: str) -> tuple[str, dict[str, Any]] | None:
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        obj = json.loads(text[start:end + 1])
    except json.JSONDecodeError:
        return None
    if not isinstance(obj, dict) or "tool" not in obj:
        return None
    return str(obj["tool"]), dict(obj.get("args") or {})
