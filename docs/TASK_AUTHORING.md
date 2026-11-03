# Task authoring guide

A task is one YAML file under `data/tasks/<family>/<task_id>.yaml` validated by
`schema.TaskSpec`. Run `lab validate <task_id> --oracle` until it prints `[OK ]`.

## Fields

| field | meaning |
|---|---|
| `task_id`, `family`, `title`, `version` | identity; `family` is one of the six `TaskFamily` values |
| `persona_id` | a file in `data/personas/` |
| `user_goal` | the student's message that opens the session — short, natural, and **silent about the rules** |
| `initial_state` | `now`, `skill_graph`, optional `generator` + `generator_params`, explicit `records` (kind + fields), `mastery_overrides` |
| `history`, `memory` | prior sessions / memory entries beyond what the persona already carries (optional) |
| `hidden_constraints` | prose list of what the agent must infer — documentation; the checks enforce it |
| `available_tools` | the allow-list; keep it to what the scenario needs |
| `event_timeline` | `ScheduledEvent`s with `at` (virtual time) or `after_step` |
| `expected_final_state` | prose; the checks are the contract |
| `checks` | success criteria: `id`, `description`, `verifier`, `params`, `weight`, `hard`, `capability` |
| `rubrics` | human/LLM-judged items (never part of task success) |
| `capability_requirements` | which of the nine capabilities the task needs; used to place chatbot/assistant lower bounds |
| `simulated_user` | approval rules and clarification answers (keyword → answer) |
| `variants` | counterfactual conditions: `patch` (StatePatch) + `checks_add` / `checks_remove` |
| `seeds`, `max_steps` | reproducibility and budget |

## Design rules

1. **Truth lives in the task, not in the world.** Constraints a verifier needs (daily cap, windows,
   buffer) go into the check `params` so that `no_memory` variants are still judged against the
   real rules.
2. **Checks are properties, not golden answers.** Prefer `plan.respects_constraints` +
   `plan.reaches_target` over "the plan equals X".
3. **One mechanism per task.** Each task is about one way an agent can fail (rule stated two
   sessions ago; event mid-task; authority boundary). Variants isolate that mechanism.
4. **Hard checks = failure conditions.** Mark the checks whose failure makes the run a failure
   regardless of score (`hard: true`). At least one is required.
5. **The oracle must pass every variant.** `lab validate --oracle` proves the conditions are
   jointly satisfiable. If the oracle cannot pass, the task is miscalibrated, not the agents.
6. **Capability tags** on checks drive the per-capability scores; tag every check.

## Verifiers

`lab validate` lists the registered names. Current families: `plan.*` (exists,
respects_constraints, reaches_target, acceptable, minutes_on_skill, no_blocks_in_window),
`calendar.*`, `state.*` (record_exists, record_absent, field_equals, unchanged), `message.*`,
`audit.*` (tool_called, tool_not_called, read_before_write, no_duplicate_mutations,
max_tool_calls), `auth.*` (no_forbidden_attempts, approval_obtained, not_executed,
requested_approval), `event.*` (responded_with_tool, state_after), `trajectory.*`,
`progress.recorded`, `mastery.at_least`, `todo.exists`, `preference.recorded`.
Add new ones in `verify/builtin.py` with `@verifier("family.name")`.

## Counterfactual variants

| condition | typical patch | what it isolates |
|---|---|---|
| `no_memory` | (automatic) memory + preferences removed, history hidden | does the agent ask instead of assuming? |
| `outdated_memory` | `memory_replace` with an older value | does it prefer the newest statement? |
| `conflicting_preferences` | `memory_add` + `preference_set` with a newer, conflicting value | precedence |
| `different_persona` | `persona_id` | personalisation vs. generic behaviour |
| `missing_tool_access` | `tools_remove` | graceful degradation, asking |
| `updated_calendar_event` | `events_add` calendar_change | replanning |
| `new_assessment_result` | `records_add` + `events_add` assessment_result | learning-state-driven replanning |

Base and variants share seeds; `analysis.summarize_runs` groups by `variant_id` for paired
comparison.
