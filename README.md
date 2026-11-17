# LearnerAgentBench

**Evaluating agents that act on behalf of a student across sessions, events and authorization boundaries.**

LearnerAgentBench puts an agent in charge of one student's learning workflow inside a persistent,
simulated digital environment (learning-management system, assessments, calendar, inbox, task
manager, long-term memory, preferences, authorization state). The agent can *write* to that
environment — change the calendar, create and revise study plans, record progress, message
instructors or guardians, register or submit — and is scored on the final state it leaves behind,
the actions it took, and whether those actions respected the student's standing rules and the
authority it was given.

What makes a task hard is not the request but the context around it: rules stated sessions ago,
a learner model whose mastery decays, events that arrive mid-task (a grade posted, an exam moved,
a sick day), and actions that need approval. Every task ships with matched counterfactual variants
(no memory, outdated memory, conflicting preferences, a different student, a missing tool, a
changed calendar, a new assessment result) so that *personalised* behaviour can be separated from
generically sensible behaviour.

Nothing in this repository is a real student's data; every persona, record and message is
synthetic.

## Status

Pre-release. The benchmark runs end to end and has a first baseline. It has not been run on strong
models or checked by human graders yet. `docs/ARCHITECTURE.md` has the design and
`docs/ROADMAP.md` the phase status.

**What exists**

- 63 tasks in six families (exam preparation, progress monitoring, adaptive tutoring,
  multi-session planning, event replanning, authorization and safety), 12 synthetic student
  personas and 100 counterfactual variants.
- 38 deterministic verifiers with 107 negative cases, a reference solution for every task, and 946
  tests. CI runs lint, type checks, tests and dataset validation on Python 3.11 to 3.13.

**What has been measured**

One small open model, `qwen2.5:7b-instruct`, run locally at temperature 0: 756 runs (63 tasks × 4
systems × 3 seeds). The full write-up, including how the grading was audited, is in
`docs/logs/phase5-new-tasks-local.md`.

| system | mean score | runs that fully succeed |
|---|---|---|
| chatbot (no tools, no memory) | 0.31 | 0 of 189 |
| memory_assistant (notes in the prompt, no tools) | 0.32 | 0 of 189 |
| tool_agent (all tools, memory through tools) | 0.41 | 2 of 189 |
| full_agent (all tools, notes in the prompt) | 0.41 | 1 of 189 |

An agent that says "I had a look; nothing to do" scores 0.27 on the same tasks. Paired by task,
tool access is worth +0.10 (95% CI +0.06 to +0.14). Memory in the prompt is not separated from no
memory. Only 3 of 756 runs fully succeed, so the result so far is that a 7B model cannot do these
tasks. It says nothing yet about stronger agents.

**What is missing**

- Runs with frontier models.
- Human validation of the grading. A blind second reading of 233 decisions by another model agreed
  with the verifiers on 93.6%; that is a model's opinion, not a person's.
- A variance study. Every run so far is at temperature 0 with three seeds.
- The trained knowledge-tracing learner. Only the transparent synthetic learner is implemented.

## Layout

```
src/learneragentbench/   the package (schema → env → learner → tools → runtime → tasks → verify → harness)
data/                    personas, skill graphs, tasks and counterfactual variants (YAML)
tests/                   unit / integration / e2e
docs/                    architecture, dataset, task authoring, agent integration, reproduction
```

## Development

```bash
uv venv .venv && source .venv/bin/activate
uv pip install -e ".[dev,llm]"
pytest
ruff check . && pyright
```

License: Apache-2.0 (see `LICENSE`).
