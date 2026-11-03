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

Status: **pre-release, under construction.** See `docs/ARCHITECTURE.md` for the design and
`docs/ROADMAP.md` for phase status. Nothing in this repository is a real student's data; every
persona, record and message is synthetic.

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
