# Roadmap and phase status

Each phase is "done" only when the listed criteria hold, the tests in CI pass, the test log is
saved under `docs/logs/`, and the work is committed. Mock-only tests, template files and empty
functions do not count.

| Phase | Scope | Status |
|---|---|---|
| 1 Core infrastructure | schema, World/Store/clock/snapshots, events, learner model + plan oracle, tool layer, world builder, data formats, tests, CI, docs | **done 2026-11-03** |
| 2 Agent runtime | adapter protocol, loop, scripted/mock/LLM adapters, trajectories, interruption/resume, simulated user, event injection, runner CLI | in progress |
| 3 Benchmark dataset | 12 personas, 6 families × ≥10 tasks = 60 validated tasks, counterfactual variants, oracle validation, KT learner model | not started |
| 4 Evaluation & baselines | deterministic verifiers, judge interface, failure attribution, 5 baselines, aggregation + CIs + reports | not started |
| 5 Real model experiments | local open model end-to-end, API models (needs budget approval), ablations, failure analysis | not started |
| 6 Open-source release | docs (dataset, authoring, integration, reproduction), third-party notices, research report | not started |

## Phase 1 — completion criteria and evidence

- [x] Strict typed records for every entity (`schema/`, 17 record kinds, task spec, trajectory, verdict).
- [x] Persistent world with versioning, history, soft delete, optimistic concurrency, snapshots to bytes and file, virtual clock.
- [x] Thirteen event kinds that mutate state and post notifications.
- [x] Transparent learner model with forgetting, prerequisite gating and plan simulation; plan oracle that builds and assesses plans.
- [x] Tool layer: 28 tools; validation, outages, policy-based permissions with scopes, approval requests, idempotent replay, complete audit log.
- [x] World builder from persona + skill-graph YAML + task initial-state spec; one persona (`dana`) and one skill graph (`algebra`).
- [x] 62 tests (unit + integration), `ruff` and `pyright` clean, CI workflow.

## Known gaps carried forward

- `KTLearnerModel` raises `NotImplementedError` until a knowledge-tracing model is trained on public data (Phase 3).
- Only one generator (`standard_semester`); assignments and assessments are explicit record seeds.
- No local language-model runtime is installed on the development machine yet (Phase 2 will add an OpenAI-compatible adapter and a user-space Ollama install; ~2 GB runtime + ~5 GB model download).
- Calendar `free_slots` uses 15-minute granularity; sub-15-minute events are rounded.
- Preference keys are documented in `docs/DATASET.md` (Phase 3) — until then see `learner/planner.py::PlanConstraints.from_world`.
