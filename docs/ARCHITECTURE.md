# Architecture

LearnerAgentBench evaluates an agent that acts **for a student** inside a persistent, simulated
digital environment. This document fixes the module boundaries and the contracts between them.
Everything below the "Status" line is implemented and tested unless marked *planned*.

## 1. Research framing

Question: can an agent keep a student's learning workflow correct — plan, calendar, progress,
communication — as the student's state, schedule and preferences change across sessions, while
respecting the student's standing rules and the authority it was given?

Nine capabilities are scored (`schema.Capability`): long-term memory, personalized planning,
educational decision-making, tool use and execution, proactive behaviour, cross-session
consistency, event-driven replanning, safety and authorization, long-horizon task completion.
Six task families (`schema.TaskFamily`): A exam preparation, B progress monitoring, C adaptive
tutoring and intervention, D multi-session study planning, E event-driven replanning and
follow-up, F privacy, authorization and educational safety.

What makes the benchmark different from its neighbours (TeachArena, EduClaw-Bench, π-Bench,
ProEvent; see `../EducationAgentBench-Plan-Review.md`): the agent is the **student's** agent and
can **write** to the student's world; the environment carries a **learner model** so that the
correct plan after an event is computable and verified without a judge; **memory is a policy**
(standing rules with state, updates, scope) rather than a fact; **authorization** is scored
through the audit log; and every task ships **paired counterfactual variants**.

## 2. Package layout and dependency order

```
schema    typed records (Pydantic, strict). No logic beyond validation.
env       Store (SQLite), VirtualClock, World (typed access + mutation tracking), events, snapshots
learner   TransparentLearnerModel, KTLearnerModel (planned), PlanOracle (build + assess plans)
tools     ToolRegistry, permissions, ToolExecutor (validation → outage → permission → approval →
          idempotency → execute → audit), built-in tools
runtime   agent loop, adapters (scripted oracle, mock, OpenAI-compatible LLM), trajectories,
          interruption/resume, event injection, simulated user            (Phase 2)
tasks     task loading, families, counterfactual variant application        (Phase 2/3)
verify    deterministic verifiers, judge interface, failure attribution    (Phase 4)
harness   runner + CLI (`lab`)                                             (Phase 2)
baselines chatbot / memory-augmented / tool agent / full agent / oracle   (Phase 4)
analysis  aggregation, bootstrap CIs, reports                              (Phase 4)
```

A module may import only from modules above it in this list.

## 3. The World

`env.World` wraps one SQLite database (`env.Store`) and a `VirtualClock`.

* **Records.** Every row is a `schema.Record` subclass with `id`, `created_at`, `updated_at`,
  `version`, `deleted`. Seventeen kinds: student_profile, preference, memory, auth_policy,
  approval_request, mastery, study_session, course, assessment, assessment_result, assignment,
  submission, study_plan, calendar_event, message, todo, tool_call.
* **Mutation.** `add` / `update` / `remove` only. Updates are optimistic (`ConflictError` on a
  stale version); deletes are soft; every create/update/delete is appended to `history`.
  `World.track()` collects the records a block of code touched — the tool layer uses it to
  fill `ToolCallRecord.records_touched`.
* **Time.** All timestamps are virtual. The clock only moves forward (`advance`, `set_time`).
  Event triggers reference virtual time (`at`) or agent steps (`after_step`).
* **Snapshots.** `snapshot(path)` / `World.from_snapshot(path)` (file) and
  `snapshot_bytes()` / `restore_bytes()` (in memory) round-trip the whole state including the
  clock. The harness snapshots at initialisation and at every interruption point.
* **Events.** `env.apply_event(world, ScheduledEvent)` mutates state the way the real system
  would: an assessment result lands in the LMS *and* nudges the hidden learner state *and*
  posts a notification; an exam move updates the assessment and its calendar entry and sends
  an email; a sick day blocks the calendar; a preference update supersedes the old value and
  writes a memory entry. Handlers: grade_posted / assessment_result, exam_rescheduled,
  calendar_change, new_message, sick_day, preference_update, tool_outage, tool_restored,
  approval_decision, deadline_moved, session_boundary, custom.

## 4. The learner model

`learner.TransparentLearnerModel`: per skill, mastery `m ∈ [0,1]` and stability `S` (days).

```
retention(Δ)  = 0.9 ** (Δdays / S)
knowledge(t)  = m · retention(t − last_practiced)
practice(min) : gain = lr · (min/60) · (1 − m_available) · (floor + (1 − floor) · prereq_knowledge)
                S ← S · (1 + growth + spacing · (1 − retention_before))
```

Prerequisites gate learning (practising a skill whose prerequisites are weak is less effective).
`PlanOracle.assess(blocks, goal, constraints)` is the function verifiers use: it checks the
structural constraints (windows, daily cap, rest days, calendar conflicts, buffer before the
target, block length, overlaps) and simulates the plan forward to see whether every target
skill (and weak prerequisite) reaches the target knowledge by the target date. **Any plan that
passes `assess` is acceptable** — tasks never compare against a single golden plan.
`PlanOracle.build` is the reference policy (greedy forward scheduler) used to prove a task is
satisfiable and as the Oracle baseline.

`learner.KTLearnerModel` is the planned trained knowledge-tracing learner; it raises until a
checkpoint exists so that nothing can silently substitute for it.

## 5. Tools

`tools.REGISTRY` holds 28 built-in tools (14 read, 13 write, 1 meta). Every call goes through
`tools.ToolExecutor.call(name, args)`:

1. tool exists and is in the task's allow-list, else `unknown_tool`
2. not under an injected outage, else `outage`
3. arguments validate against the tool's Pydantic model, else `error` (validation)
4. permission resolved from `AuthorizationPolicy` rows (most specific scope wins) or the tool's
   default: read tools and the student's own workspace (plans, calendar, tasks, progress,
   memory, preferences) are `allowed`; `send_message` and `book_slot` are
   `requires_approval`; `submit_assignment` and `purchase` are `forbidden`
5. `requires_approval`: an `ApprovalRequest` is found or created for (tool, normalised args);
   the call returns `pending_approval` until the simulated student decides; `denied` afterwards
6. idempotency: a mutating call whose key (declared fields, else all args) matches an earlier
   successful call in the same run is replayed, not re-executed
7. execute inside `World.track()`; failures are classified (`not_found`, `conflict`,
   `validation`, `internal`)
8. one `ToolCallRecord` per call — including every failure — with step, virtual and wall time,
   permission level, approval id, idempotency key, mutation flag and touched records.

Verifiers read the audit log, never the agent's text, to score tool correctness,
authorization and duplicate actions.

## 6. Runtime (Phase 2)

`runtime.AgentAdapter` protocol: `start(task_view)`, `step(observation) → Action`,
`state()` / `restore(state)` for resume. Actions: `tool_call`, `ask_user`, `final`, `wait`.
The loop: observation → adapter → (tool call → executor → observation) … with max steps,
event injection between steps (virtual time or step triggers), simulated-user replies to
`ask_user` and approval requests (`SimulatedUserSpec`), trajectory recording (JSONL + final
`Trajectory`), interruption after any step with world snapshot + adapter state, and resume.

Adapters: `scripted` (task-specific oracle policies for validation), `mock` (replay), and
`openai_compatible` (any endpoint speaking the OpenAI chat API with tool calling — local
Ollama/vLLM/llama.cpp or hosted models; a JSON-action fallback for models without native tool
calling).

## 7. Tasks and counterfactuals (Phase 3)

`schema.TaskSpec` is the unit of the dataset (YAML under `data/tasks/<family>/`). It fixes the
persona, the initial state (generator + explicit records + mastery overrides), prior sessions
and memory, hidden constraints, the tool allow-list, the event timeline, checks (with `hard`
failure conditions and capability tags), rubrics, capability requirements, the simulated user,
seeds, and **variants**: each `VariantSpec` is a named counterfactual condition
(no_memory, correct_memory, outdated_memory, conflicting_preferences, different_persona,
missing_tool_access, updated_calendar_event, new_assessment_result) with a `StatePatch` and
the checks it adds or removes. Runs of a task and its variants share seeds so that pairs can be
compared directly.

## 8. Verification (Phase 4)

Deterministic verifiers inspect final state, the audit log, the event log and the trajectory:
plan acceptable (`PlanOracle.assess`), calendar consistency, task completion (expected final
state assertions), authorization (forbidden attempts, approvals obtained before acting,
scope respected), duplicates/invalid actions, event response (state changed after the event
in the required way), memory-dependent decisions (the decision matches what the standing
rule requires). Judges (LLM or human) are used only for rubric items marked as such and never
for task success. `Verdict.failure_attribution` separates agent failure from environment or
harness failure (internal tool errors, outages the task did not inject, model API errors).

## 9. Status

Phase 1 (this document's sections 3–5): implemented; see docs/logs/phase1-tests.txt for the test run. Phases 2–6: see
`docs/ROADMAP.md`.
