# Dataset

Everything under `data/` is synthetic. No persona, record, message or transcript describes a real
person. Files are YAML validated by `schema.TaskSpec`, `env.seed.PersonaBundle` and
`schema.SkillGraph`; `lab validate --all --oracle` must pass before a task is counted.

## Personas (`data/personas/`)

| id | who | what makes them different |
|---|---|---|
| `dana` | adult community-college student retaking algebra, evening work shifts | 90 min/day in 45-min blocks, nothing after 22:00, Sundays off, 24 h buffer before exams; grades never to parents, tutor allowed; Socratic hint policy (hint after two failures, "I don't know" not an attempt) |
| `marcus` | high-school junior, basketball three afternoons a week, involved parent | 60 min/day in 30-min blocks (20 min minimum), mornings or after practice, nothing after 21:00, Friday nights off; dad always allowed, teachers only after approval; worked-example policy (show the solution after one miss) |

A persona file carries: `profile` (contacts with roles, weekly availability windows, goals),
`preferences` (structured keys, see below), `memory` (what was said in earlier sessions, typed
by `MemoryKind`), `policies` (authorization grants and prohibitions), `history` (transcripts of
those sessions) and `mastery_defaults` per skill.

## Preference keys the planner understands

| key | type | meaning |
|---|---|---|
| `max_daily_minutes` | int | daily study cap |
| `min_block_minutes`, `preferred_block_minutes` | int | block length |
| `no_study_before`, `no_study_after` | "HH:MM" | daily limits |
| `rest_weekdays` | list[int] | 0 = Monday … 6 = Sunday |
| `buffer_hours_before_exam` | int | no study inside this window before an assessment |
| `hint_policy` | object | tutoring: `hint_after_consecutive_failures`, `idk_counts_as_attempt`, `no_final_answer_unless_asked`, `show_answer_after_failures`, `counting_scope` |
| `share_grades_with` | list[contact id] | who may receive results (policies enforce it) |

Preferences are scoped (`global` or a course id); the most recent active statement wins and a
course scope beats global.

## Skill graphs (`data/skills/`)

`algebra`: 12 skills with prerequisite edges (order of operations → fractions / linear equations
→ inequalities, word problems, graphing → systems, functions; exponents → polynomials →
factoring → quadratics). The learner model gates practice by prerequisite knowledge.

## Tasks (`data/tasks/<family>/`)

| task | family | persona | mechanism | variants |
|---|---|---|---|---|
| `A01_quadratics_quiz_short_blocks` | A exam preparation | marcus | short blocks around practice; weak prerequisites first | no_memory, other_student (dana) |
| `B01_weekly_checkin_act_on_what_matters` | B progress monitoring | dana | vague request; overdue work, weak quiz, inbox offer, result posted mid-session | no_memory, no_new_result |
| `C01_hints_on_my_terms` | C adaptive tutoring | dana | state-dependent hint policy over a scripted three-problem session | other_student (marcus: worked examples) |
| `D01_midterm_plan_from_rules` | D multi-session planning | dana | rules from two earlier sessions, never restated | no_memory, updated_calendar, new_result, relaxed_cap, no_memory_tool |
| `E01_exam_moved_earlier` | E event-driven replanning | dana | exam moved four days earlier mid-session; active plan must be reworked | no_memory, sick_days |
| `F01_share_progress_with_the_right_people` | F authorization | dana | one allowed and one forbidden recipient in the same request | no_memory, rule_relaxed, other_student (marcus) |

Counts: 6 tasks, 15 variants, 21 oracle-validated runs, 2 personas. Target for the first
release: 60 tasks (≥ 10 per family), 12 personas.

## Files a run produces (`runs/<run_id>/`)

`config.json`, `task_effective.json`, `variant_log.json`, `world_init.db`, `world_final.db`
(SQLite; open with any client), `steps.jsonl`, `trajectory.json`, `verdict.json`, and for
interrupted runs `world_checkpoint.db` + `loop_state.json`.
