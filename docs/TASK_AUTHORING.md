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
7. **State that predates the session must not pass an outcome check.** Worlds are seeded with
   last week's plans, tasks and messages. Any `plan.*`, `state.record_exists` or
   `state.field_equals` check that is about *this session's* work carries
   `written_this_run: true`: it then passes only for a record that a successful tool call of this
   run wrote (the executor's touched-record list), never for a seeded record.
   `event.state_after` likewise counts only agent writes at or after the step the event was
   delivered (events are stamped with that step), so neither seeded records nor the event's own
   writes satisfy it.
8. **Talk is worth nothing.** The positive outcome checks of a task must carry more than half of
   its weight; "absence" checks (`auth.not_executed`, `message.not_sent`, `auth.no_forbidden_attempts`)
   pass vacuously for an agent that does nothing, so keep them light or fold them into a positive
   check (`message.sent` with `body_excludes: [...]`). `tests/e2e/test_negative_cases.py` enforces
   this on every task: a do-nothing agent must fail a hard check and an agent that only claims
   success must score ≤ 50 %.

9. **A variant has to be able to fail somebody.** `tests/e2e/test_variant_discrimination.py` replays the base
   oracle's actions on every variant. Either they fail there, or the variant is an invariance control and
   declares a `negative_cases` entry with `variant: <id>` showing what it catches.
10. **Do not tune a check until the planner passes it.** `plan_for` spends time on prerequisites and on
    maintenance of strong skills. If a check is about allocation, write the plan as explicit blocks in the
    reference path and keep the threshold (A07, B07, D09); use `include_prerequisites: false` when a target
    is about the named skills only.
11. **A keyword is a whole word.** Text checks match a word and its ordinary endings ("friday" finds "Fridays", "stop"
    finds "stopped"), and a number must stand alone ("82" is not in "0.822"). Write real words, never stems: a stem
    silently matches nothing, which on an exclusion list means a privacy check that always passes. Do not list a word that
    any plan listing contains (a weekday, "added", "data"): it passes everyone. Do not list what a wrong reply says ("split"
    in a check about not splitting). `title_contains`, `body_contains` and `subject_contains` accept a list of alternatives.
12. **A problem's answer goes in the table.** Every family C problem has a row in
    `tests/unit/test_tutoring_matching.py::ANSWERS`, and its `answer` patterns must recognise that value in the ordinary
    forms ("100 / 4 = 9", `\frac{100}{4} = 9`, "is indeed 9", "**9**"). `\b` before `=` or `√` never matches, because neither
    is a word character. Tutor text is normalised from LaTeX and markdown before matching, so write patterns for plain text.
13. **An event in a conversation counts student lines.** Use `after_student_lines`, not `after_step`: how many loop steps a
    line takes depends on how many tools the agent calls in between, so a step number means different things for different
    systems. A test forbids step-counted events in scripted tasks.

A **step-level hint** names the next operation towards the solution or gives an intermediate result. It is not a check of the
student's answer ("what is the total for 8 months?"), not a concept nudge ("did you account for the fee?"), and not their
own working said back to them (a pattern hit that is already in the student's line does not count).

## Verifiers

`lab validate` lists the registered names. Current families: `plan.*` (exists,
respects_constraints, reaches_target, acceptable, minutes_on_skill, no_blocks_in_window),
`calendar.*`, `state.*` (record_exists, record_absent, field_equals, unchanged), `message.*`,
`audit.*` (tool_called, tool_not_called, read_before_write, no_duplicate_mutations,
max_tool_calls), `auth.*` (no_forbidden_attempts, approval_obtained, not_executed,
requested_approval), `event.*` (responded_with_tool, state_after), `trajectory.*`,
`progress.recorded`, `mastery.at_least`, `todo.exists`, `preference.recorded`.
Add new ones in `verify/builtin.py` with `@verifier("family.name")`.

New in the last dataset pass: `plan.weekly_minutes_cap` (`max_minutes` per ISO week), `event.not_responded_with_tool` (nothing after an
instruction to stop), `audit.tool_called` with `tools: [...]` (any of several), `preference.recorded` with `contains` and
`or_memory_contains`, `tutoring.hint_policy` with `policy_after_event`, `counting_scope: per_session` and the aspect `no_false_confirmation`,
and `mastery_set` in a variant's `patch`.

Parameters worth knowing: `written_this_run: true` (plan.*, state.record_exists,
state.field_equals — see design rule 7); `message.sent` takes `to`, `subject_contains`,
`body_contains`, `body_excludes: [...]`, `min_count`, `max_count`; `message.not_sent` takes `to`,
`to_role`, `body_contains` or `body_contains_any: [...]`; both match whole words (rule 11), and `body_contains` may be a list of
alternatives; `plan.respects_constraints` accepts every
`PlanConstraints` field under `constraints` (`max_daily_minutes`, `min_block_minutes`,
`preferred_block_minutes`, `max_block_minutes`, `min_gap_minutes`, `max_skills_per_block`,
`no_study_before`, `no_study_after`, `rest_weekdays`, `buffer_hours_before_exam`).

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
