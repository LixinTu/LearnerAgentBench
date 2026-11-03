# Agent integration guide

An agent is anything that satisfies `learneragentbench.runtime.AgentAdapter`:

```python
class AgentAdapter(Protocol):
    name: str
    def start(self, view: TaskView) -> None: ...        # called once; view has the goal, tools, time, memory (gated)
    def step(self, observation: Observation) -> Action: ...
    def state(self) -> dict: ...                          # JSON-able; used for interruption/resume
    def restore(self, state: dict) -> None: ...
    def usage(self) -> ModelUsage: ...                    # tokens / calls / cost so far
```

`Action` is one of `tool_call(tool, args)`, `ask_user(message)`, `wait(minutes)`, `final(message)`.
`Observation.type` is one of `task` (first step; `content` is the TaskView), `tool_result`,
`tool_error`, `user_message`, `event`, `resume`, `approval`. Event notices and approval
decisions arrive as `content["notices"]` on the next observation.

## Built-in adapters

| name | what it is | how to select |
|---|---|---|
| `oracle` | reference policy with direct world access (per family / task) | `lab run --adapter oracle --model oracle` |
| `openai_compatible` | any endpoint speaking the OpenAI chat API with tool calling | `lab run --adapter openai_compatible --model <id> --base-url <url>` |
| `ActionListAdapter`, `PolicyAdapter`, `ReplayAdapter` | scripted adapters for tests | Python only |

The `openai_compatible` adapter exposes the task's tools plus three meta tools (`ask_user`,
`wait`, `finish`). A reply with no tool call is treated as `finish`; an empty reply is nudged
once. `--json-fallback` switches to a JSON-in-text protocol for models without native tool
calling. Set `OPENAI_API_KEY` or pass `--base-url` for local servers (no key needed).

### Local model (what the development machine uses)

```bash
bash scripts/setup_local_llm.sh qwen2.5:7b-instruct      # user-space Ollama + model (~6 GB)
~/.local/ollama/serve.sh &                                # 12k context, q8 KV cache
lab run --model qwen2.5:7b-instruct --adapter openai_compatible \
        --base-url http://127.0.0.1:11434/v1 --task D01_midterm_plan_from_rules --out runs/local
lab show runs/local/<run_dir>
```

## What the agent sees — baselines from one model

`RunConfig.memory_access` and `tool_profile` gate the TaskView; the same model becomes four
systems:

| baseline | memory_access | tool_profile | note |
|---|---|---|---|
| Chatbot | `none` | `none` | goal + persona summary only; can only talk |
| Memory-augmented assistant | `full` | `none` | memory notes and transcripts in the prompt; no tools |
| Retrieval + tool agent | `tools` | `full` | memory only through `search_memory` / `get_preferences` |
| Full personalized agent | `full` | `full` | notes in prompt *and* tools |

## Writing your own adapter

Subclass nothing; implement the five methods and register a factory in
`harness/runner.py::default_adapter_factory` (or pass `adapter_factory=` to `run_one`). Keep
`state()` JSON-able: the harness checkpoints it with the world snapshot when a run is
interrupted (`--interrupt-after N`) and hands it back on `lab resume`.

Rules the harness enforces for you: the tool allow-list, outages, permissions and approvals,
idempotent replay of identical writes, and the audit log. Your adapter never touches the world
directly; everything goes through `Action.tool_call`.
