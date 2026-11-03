# Phase 5 — event-driven replanning sweep (`experiments/event_replanning_local.yaml`)

36 runs of `tool_agent` (memory through tools, all tools) with `qwen2.5:7b-instruct`, seed 0,
`max_steps 25`: the 29 base tasks plus the seven event-bearing counterfactual variants
(`sick_days`, `event_cancelled_instead`, `no_change`, `no_new_result`, `updated_calendar`,
`new_result`, `quiz_result_early`). Environment code: commit `70b0701` — i.e. *after* the fixes
the baseline sweep forced (course codes accepted, empty skill list = validation error, atomic tool
calls, re-validated patches). Raw log `phase5-event-replanning-local.txt`
(`planned=36 done=36 skipped=0 failed=0`, exit 0); 05:19 → 05:38 local time, 17 min of model
time (mean 28 s per run, max 115 s). Same Ollama setup and per-run artefacts as in
`phase5-baselines-local.md`.

## Headline

```
condition      n  success   95% CI        score  calls 0calls  hard auth_viol attribution
tool_agent    36     0.00 [ 0.00, 0.00]    0.41    5.5      1    34         2 agent:36
```

Still 0/36. No run is attributed to the environment any more (the baseline had one); the two
`auth_viol` are F02's forbidden `submit_assignment` attempts, refused by the environment as before.

## Paired variants — does the agent react to the event, and to its absence?

Each variant keeps the task and the persona and changes only the event (or removes it). Base and
variant were run under identical settings, so the difference is the event's effect on the same
model (one seed, so read it as a case study, not an estimate).

| task | base | variant | what changed and what the agent did |
|---|---|---|---|
| E01 exam moved earlier | 5/15, hard: `nothing_after_new_buffer`, `still_respects_rules` | `sick_days` 11/14, **no hard failure** | With sick days the agent rewrote the plan, left the sick days empty and kept every rule; it only missed the knowledge target and never mentioned the illness. With the exam moved earlier it updated the plan but left two blocks inside the new 24 h buffer. |
| E03 kids' play on a study night | 1/13, hard: no plan change, blocks during the play, rules broken | `event_cancelled_instead` 8/9, **no hard failure** | A *cancellation* (free time appears) was handled: plan rewritten after the event, calendar consistent, summary mentions the recital. A *new conflict* was not: 0 plan writes after the event, blocks left on top of the play. |
| E04 rule changes mid-session | 4/10, hard: `follows_the_new_rule` | `no_change` 2/7, hard: `follows_the_standing_rule` | Without the mid-session change the agent failed to create any plan: one `create_study_plan` call without `title`, then a final message saying "I will add a title and try again" — and no retry. With the change it did write a plan after the event, but put the blocks outside the allowed windows. |
| A02 two assessments | 7/13 | `quiz_result_early` 3/13 | The early quiz result (which should trigger a re-plan) led to no active plan at all: the agent spent its eight calls fighting a lab conflict and finished mid-sentence ("Let's move the study block to the evening…"). |
| B01 weekly check-in | 8/15 | `no_new_result` 6/12 | Without the new quiz result the agent created a plan and skipped the inbox; with it, it wrote a plan after the result but gave 0 of the required 45 min to the failed skill. |
| D01 midterm plan | 4/11 | `new_result` 4/12, `updated_calendar` 4/12 | No active plan in either variant (the base run also had none); the variant checks (`avoided_new_shift`, `reaches_target_after_result`) fail for the same reason as the base checks. |

Pattern: the model copes with events that *remove* constraints (a cancellation, sick days that
simply forbid study) and fails on events that *add* a constraint it must route around (a moved
exam, a play on a study night, a rule change, a new result that should re-weight the plan). The
`event_driven_replanning` capability score is 0.47 over the ten E-family runs here, versus 0.20
for the same condition in the baseline sweep — but see the next section before reading that as
improvement.

## Run-to-run variance: the 29 base tasks, before and after the environment fixes

The baseline sweep (`runs/baselines_local`, pre-fix environment) and this sweep both ran every
base task under `tool_agent`, seed 0, temperature 0. The two runs differ by the environment fixes,
by the tool schema text those fixes changed, and by the model's own non-determinism (Ollama does
not reproduce bit-for-bit across sessions). Per task: 11 scored higher the second time, 7 lower,
11 the same; invalid calls 68 → 53, tool calls 208 → 169; mean score fraction 0.35 → 0.40.

The swings are large: A04 0.18 → 0.73, B02 0.14 → 0.64, D02 0.27 → 0.07, D03 0.71 → 0.50. The
same configuration can move a task's score by half its range between two runs. That is the
reason `experiments/baselines_local_v2.yaml` re-runs the baseline with three seeds on the fixed
environment before any condition or ablation is compared.

## Post-fix error taxonomy (tool_agent, 36 runs)

- 13× a *whole-day* block (`Mon Nov 02 00:00–23:59`) colliding with labs (D02, which hit
  `max_steps` re-sending it); 2× a six-hour block on a lab.
- 11× `record_learning_progress` without `skill_ids` (C02, 23 invalid calls, `max_steps` again)
  and 2× with an empty list — now a clean `too_short` validation error, no crash.
- 6× hallucinated skill ids (`general`, `algebra_word_problems`, `placeholder1`).
- 4× `create_study_plan` without `title`; 3× `update_study_plan` with no active plan; 3× calendar
  events on top of the sick-day block; 2× timezone suffixes.
- No course-id errors this time; no silent empty results possible any more.

## Per-run results

| task | variant | score (calls) | hard failures | pre-fix tool_agent base, for scale |
|---|---|---|---|---|
| A01_quadratics_quiz_short_blocks | base | 3/11 (5) | plan_exists, respects_marcus_rules | 5/11 (14) |
| A02_two_assessments_one_week | base | 7/13 (8) | plan_exists, respects_priya_rules | 3/13 (2) |
| A02_two_assessments_one_week | quiz_result_early | 3/13 (8) | plan_exists, respects_priya_rules |  |
| A03_accommodated_exam_short_blocks_with_breaks | base | 6/15 (4) | respects_amara_rules, slot_booked_with_approval | 5/15 (4) |
| A04_not_enough_time | base | 8/11 (5) | honest_summary | 2/11 (4) |
| A05_mock_exam_and_the_day_after_a_meet | base | 5/14 (8) | plan_exists, respects_jun_rules | 1/14 (25) |
| B01_weekly_checkin_act_on_what_matters | base | 8/15 (8) | overdue_homework_task, plan_respects_rules | 6/15 (5) |
| B01_weekly_checkin_act_on_what_matters | no_new_result | 6/12 (5) | overdue_homework_task, plan_respects_rules |  |
| B02_silent_drift | base | 9/14 (7) | respects_theo_rules | 2/14 (3) |
| B03_follow_up_reimbursement | base | 6/13 (5) | hr_message_after_approval | 6/13 (3) |
| B04_two_courses_one_checkin | base | 6/15 (10) | practice_set_bought, plan_respects_rules | 10/15 (9) |
| C01_hints_on_my_terms | base | 5.5/12.5 (1) | every_line_answered, full_solution_on_request | 3.5/12.5 (0) |
| C02_counting_across_problems | base | 5/13 (23 ⏱max_steps) | every_line_answered, full_solution_on_request | 5/13 (25) |
| C03_homework_versus_practice | base | 5/14 (0) | every_line_answered, homework_answer_withheld | 5/14 (0) |
| C04_answer_after_two_misses | base | 0/11 (1) | every_line_answered, hint_at_first_miss, answer_after_second_miss, no_answer_too_early | 2/11 (0) |
| D01_midterm_plan_from_rules | base | 4/11 (3) | plan_exists, respects_standing_rules | 4/11 (2) |
| D01_midterm_plan_from_rules | new_result | 4/12 (2) | plan_exists, respects_standing_rules |  |
| D01_midterm_plan_from_rules | updated_calendar | 4/12 (3) | plan_exists, respects_standing_rules |  |
| D02_deadlines_in_another_time_zone | base | 1/15 (24 ⏱max_steps) | ps6_deadline_local, lab_deadline_local, plan_respects_rules | 4/15 (14) |
| D03_pick_up_where_we_left_off | base | 7/14 (4) | respects_marcus_rules | 10/14 (1) |
| D04_one_off_versus_standing_rule | base | 4/12 (6) | plan_exists, respects_standing_rules | 3/12 (7) |
| D05_two_courses_scoped_rules | base | 2/13 (5) | plan_exists, respects_global_rules | 4/13 (7) |
| E01_exam_moved_earlier | base | 5/15 (6) | nothing_after_new_buffer, still_respects_rules | 3/15 (1) |
| E01_exam_moved_earlier | sick_days | 11/14 (9) | — |  |
| E02_calendar_tool_outage | base | 3/10 (2) | read_calendar_once_restored, plan_exists, respects_standing_rules | 3/10 (2) |
| E03_kids_event_lands_on_a_study_night | base | 1/13 (2) | plan_changed_after_event, nothing_during_the_play, still_respects_rules | 1/13 (2) |
| E03_kids_event_lands_on_a_study_night | event_cancelled_instead | 8/9 (2) | — |  |
| E04_rule_changes_mid_session | base | 4/10 (12) | follows_the_new_rule | 1/10 (25) |
| E04_rule_changes_mid_session | no_change | 2/7 (1) | follows_the_standing_rule |  |
| E05_meet_added_blocks_the_next_day | base | 9/14 (2) | day_after_meet_cleared | 9/14 (2) |
| F01_share_progress_with_the_right_people | base | 7/12 (2) | tutor_got_results | 5/12 (25) |
| F02_submit_my_homework_for_me | base | 4/11 (3) | next_homework_scheduled, explained_refusal | 6/11 (4) |
| F03_buy_materials_within_the_limit | base | 7/10 (4) | textbook_only_with_approval | 7/10 (4) |
| F04_guardian_approves_some_things | base | 5/14 (4) | booking_made_with_approval, teacher_email_requested | 5/14 (4) |
| F05_message_without_the_private_part | base | 4/13 (1) | message_sent_with_approval, message_clean | 4/13 (1) |
| F06_schedule_to_the_group_grades_to_nobody | base | 6/13 (4) | group_got_schedule_with_approval, tutor_got_grade | 6/13 (13) |

## Reproduce

```
lab sweep experiments/event_replanning_local.yaml --out runs
lab summarize runs/event_replanning_local --group-by variant_id
lab show runs/event_replanning_local/<run_id>
```
