# Roadmap and phase status

Each phase is "done" only when the listed criteria hold, the tests in CI pass, the test log is
saved under `docs/logs/`, and the work is committed. Mock-only tests, template files and empty
functions do not count.

| Phase | Scope | Status |
|---|---|---|
| 1 Core infrastructure | schema, World/Store/clock/snapshots, events, learner model + plan oracle, tool layer, world builder, data formats, tests, CI, docs | **done 2026-11-03** |
| 2 Agent runtime | adapter protocol, loop, scripted/LLM adapters, trajectories, interruption/resume, simulated user, event injection, verifiers, runner + CLI, first task, local model end-to-end | **done 2026-11-03** |
| 3 Benchmark dataset | 12 personas, 6 families × ≥10 tasks = 60 validated tasks, counterfactual variants, oracle validation, KT learner model | dataset target reached on 2026-11-03: 63 tasks (every family ≥ 10), 100 variants, 163 oracle runs, 107 negative cases, 12 personas that differ in goals, mastery, strategy, schedule and authorization (tested), 3 skill graphs; every variant is shown to discriminate (`tests/e2e/test_variant_discrimination.py`). Still pending: the trained KT model and variant coverage of all eight conditions in every family (`docs/COVERAGE.md`) |
| 4 Evaluation & baselines | deterministic verifiers, judge interface, failure attribution, 5 baselines, aggregation + CIs + reports | mostly done: 38 verifiers, attribution, reliability test suite (`docs/RELIABILITY.md`), judging audited against real replies (`docs/logs/phase5-new-tasks-local.md`), experiment sweeps and re-runs (`lab sweep`, `lab rerun`, `lab rescore`); judge interface and HTML reports pending |
| 5 Real model experiments | local open model end-to-end, API models (needs budget approval), ablations, failure analysis | local model done for now: baseline of record over all 63 tasks × 4 systems × 3 seeds (756 runs, 3 successes, tool access +0.101 [+0.063, +0.142], memory not separated) plus tool, memory, persona and event ablations and 52 variants: `docs/logs/phase5-new-tasks-local.md`, `phase5-family-c-v2.md`, `phase5-ablations-local.md`. Earlier documents are history. Hosted models need budget approval: not started |
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
- [x] 134 tests including an end-to-end oracle run of every task × variant; `ruff`, `pyright` clean (`docs/logs/phase2-tests.txt`).

## Phase 3 — progress so far (2026-11-03)

- [x] One validated task per family: A01, B01, C01, D01, E01, F01 (`docs/DATASET.md`); each passes `lab validate --oracle` on the base task and every variant.
- [x] Family C infrastructure: scripted student replies (`SimulatedUserSpec.scripted_replies`) and the `tutoring.hint_policy` verifier (answer leak, hint due / early, confirmation, explicit request, worked-example policy) ported from the S1 study.
- [x] Oracles for all six families (`baselines/oracle.py`).
- [x] 2026-11-03: ≥ 10 tasks per family, each with its own failure mechanism (`docs/DATASET.md` names it); 12 personas; the coverage matrix regenerated.
- [ ] Remaining: generators for assignments/assessments, the trained KT learner, variant coverage of all eight counterfactual conditions per family. Family C has no `no_memory` variants: the simulated student's scripted replies would be consumed by the agent's questions, so that condition needs a scripted-reply design of its own.

## Known gaps carried forward

- `KTLearnerModel` raises `NotImplementedError` until a knowledge-tracing model is trained on public data (Phase 3).
- Only one generator (`standard_semester`); assignments and assessments are explicit record seeds.
- Local model runs are slow on the 8 GB laptop GPU (a 5-step episode of qwen2.5:7b takes minutes); the 12k context window limits how many tools a task can expose at once. Hosted models need budget approval.
- `different_persona` variants need a second persona (Phase 3); the LLM judge interface and HTML/Markdown reports are not written yet (Phase 4).
- Calendar `free_slots` uses 15-minute granularity; sub-15-minute events are rounded.
- Preference keys are documented in `docs/DATASET.md` (Phase 3) — until then see `learner/planner.py::PlanConstraints.from_world`.
- `long_horizon_task_completion` now counts outcome checks only (`trajectory.completed` earns no capability score), which leaves it thin: 14 checks, none in families A and B. Good candidates to re-tag at the next re-baseline: A03 `slot_booked_with_approval`, B03 `hr_message_after_approval`. Stored runs keep the tags they ran with, so a re-tag only applies to new runs.
- `task_success` means every hard check, a perfect score and a normal end. Reports should show the count of runs without hard failures next to it.
- At temperature 0 the run seed changes nothing the model sees except the run id in the task observation (record ids are identical), so `seeds: [0, 1, 2]` are near-replays: they average GPU and prompt noise (mean per-task range 0.05, max 0.5 in `baselines_local_v2`) but do not sample a stochastic policy. Compare conditions paired by task over ≥ 3 seeds; a sampling-variance study needs temperature > 0.
- Two tool messages that cost the model many calls and were left alone so runs stay comparable: an unknown skill id does not list the known ones (192 rejected calls on D07), and strict schemas reject `null` for optional fields. Change both at the next re-baseline.
- Keyword checks cannot tell a claim from a fact. They are paired with state checks, and one task (F09) has an explicit check for a false report, but there is no general check for claims without a successful call behind them. A read-through found 16 such claims in 378 acting runs.
- Process checks such as "read memory first" fail a memory-in-prompt system that has no need to read. Paired differences move by at most 0.008, but such a system cannot reach strict success on those 22 tasks.
- This server does not reproduce replies exactly at temperature 0: with a byte-identical first prompt the first action matched in 44 of 72 re-runs. Whether `read_only` really leaks answers more in family C needs a study at temperature above 0.
- Schema echo: the model copies derived fields from tool results into arguments (`minutes` inside `add_blocks`, `event_id: null` on create) — 104 rejected calls in `baselines_local_v2`. The schemas stay strict and the descriptions unchanged until the ablations paired against v2 are done; then revisit the descriptions and re-baseline.
