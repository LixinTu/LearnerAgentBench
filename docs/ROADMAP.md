# Roadmap and phase status

Each phase is "done" only when the listed criteria hold, the tests in CI pass, the test log is
saved under `docs/logs/`, and the work is committed. Mock-only tests, template files and empty
functions do not count.

| Phase | Scope | Status |
|---|---|---|
| 1 Core infrastructure | schema, World/Store/clock/snapshots, events, learner model + plan oracle, tool layer, world builder, data formats, tests, CI, docs | **done 2026-11-03** |
| 2 Agent runtime | adapter protocol, loop, scripted/LLM adapters, trajectories, interruption/resume, simulated user, event injection, verifiers, runner + CLI, first task, local model end-to-end | **done 2026-11-03** |
| 3 Benchmark dataset | 12 personas, 6 families × ≥10 tasks = 60 validated tasks, counterfactual variants, oracle validation, KT learner model | in progress (3 tasks D01/E01/F01 with 10 variants, 2 personas, 3 family oracles) |
| 4 Evaluation & baselines | deterministic verifiers, judge interface, failure attribution, 5 baselines, aggregation + CIs + reports | partly done (34 verifiers, attribution, oracle + 4 config-defined baselines, summary with bootstrap CIs); judge interface and reports pending |
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

## Phase 2 — completion criteria and evidence

- [x] `AgentAdapter` contract; `ActionListAdapter`, `PolicyAdapter`, `ReplayAdapter`, `OpenAICompatibleAdapter` (native tool calling, JSON fallback, retries, truncation, state round-trip, empty-reply nudge).
- [x] `AgentLoop`: observation → action → tool/ask/wait/final; virtual time; events by time or step; simulated student (clarifications, approval rules with delays); trajectory JSONL + JSON; interruption after N steps and resume from world checkpoint + adapter state; adapter and environment errors attributed separately.
- [x] Task loading, counterfactual variants (`effective_task`, `apply_patch`), 34 deterministic verifiers, verdict assembly with hard failures, authorization violations, duplicates, capability scores and failure attribution.
- [x] Runner writing config / effective task / init + final world snapshots / steps / trajectory / verdict / variant log; `lab` CLI: list, validate (static + oracle), run, resume, reverify, show, summarize (bootstrap CIs).
- [x] Tasks `D01_midterm_plan_from_rules` (5 variants), `E01_exam_moved_earlier` (2), `F01_share_progress_with_the_right_people` (3); personas `dana`, `marcus`; the family oracles pass every base task and variant (`lab validate --all --oracle`, 13 runs, all full score).
- [x] A real model-driven run end to end on the development laptop: qwen2.5:7b-instruct through a user-space Ollama server (`docs/logs/phase2-local-model-run.txt`).
- [x] 115 tests including an end-to-end oracle run of every task × variant; `ruff`, `pyright` clean (`docs/logs/phase2-tests.txt`).

## Known gaps carried forward

- `KTLearnerModel` raises `NotImplementedError` until a knowledge-tracing model is trained on public data (Phase 3).
- Only one generator (`standard_semester`); assignments and assessments are explicit record seeds.
- Local model runs are slow on the 8 GB laptop GPU (a 5-step episode of qwen2.5:7b takes minutes); the 12k context window limits how many tools a task can expose at once. Hosted models need budget approval.
- `different_persona` variants need a second persona (Phase 3); the LLM judge interface and HTML/Markdown reports are not written yet (Phase 4).
- Calendar `free_slots` uses 15-minute granularity; sub-15-minute events are rounded.
- Preference keys are documented in `docs/DATASET.md` (Phase 3) — until then see `learner/planner.py::PlanConstraints.from_world`.
