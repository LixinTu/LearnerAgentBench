# Coverage matrix

36 tasks · 12 personas (amara, dana, eleanor, jun, kai, liam, marcus, noor, priya, ravi, sofia, theo) · target 60 tasks / 12 personas

## Tasks per family

| family | tasks | personas used | missing capabilities | missing counterfactual conditions |
|---|---|---|---|---|
| A | 6 | amara, dana, eleanor, jun, marcus, priya, theo | — | outdated_memory |
| B | 6 | dana, kai, noor, ravi, theo | — | outdated_memory, updated_calendar_event |
| C | 6 | dana, kai, liam, marcus, noor, priya, ravi | event_driven_replanning | no_memory, conflicting_preferences, updated_calendar_event, new_assessment_result |
| D | 5 | dana, marcus, noor, priya, sofia | — | — |
| E | 6 | dana, jun, priya, ravi, theo | — | outdated_memory, conflicting_preferences, different_persona |
| F | 7 | amara, dana, eleanor, liam, marcus, priya, sofia | event_driven_replanning | correct_memory, missing_tool_access, updated_calendar_event, new_assessment_result |

## Capability × family (number of tasks whose checks tag the capability)

| capability | A | B | C | D | E | F |
|---|---|---|---|---|---|---|
| long_term_memory | 6 | 5 | 6 | 5 | 5 | 5 |
| personalized_planning | 3 | 1 | 1 | 2 | 1 | 1 |
| educational_decision_making | 6 | 5 | 6 | 4 | 6 | 1 |
| tool_use_and_execution | 6 | 6 | 1 | 4 | 6 | 7 |
| proactive_behavior | 6 | 6 | 1 | 4 | 6 | 6 |
| cross_session_consistency | 4 | 1 | 6 | 5 | 2 | 4 |
| event_driven_replanning | 2 | 1 | 0 | 1 | 5 | 0 |
| safety_and_authorization | 4 | 6 | 3 | 3 | 3 | 7 |
| long_horizon_task_completion | 6 | 6 | 6 | 5 | 6 | 7 |

## Counterfactual condition × family (number of tasks with such a variant)

| condition | A | B | C | D | E | F |
|---|---|---|---|---|---|---|
| no_memory | 5 | 5 | 0 | 4 | 3 | 2 |
| correct_memory | 1 | 1 | 1 | 1 | 1 | 0 |
| outdated_memory | 0 | 0 | 1 | 2 | 0 | 1 |
| conflicting_preferences | 1 | 2 | 0 | 1 | 0 | 6 |
| different_persona | 2 | 1 | 4 | 2 | 0 | 2 |
| missing_tool_access | 1 | 1 | 1 | 1 | 1 | 0 |
| updated_calendar_event | 1 | 0 | 0 | 1 | 4 | 0 |
| new_assessment_result | 1 | 1 | 0 | 1 | 1 | 0 |

## Per task

| task | family | persona(s) | checks (hard) | variants | events | ref. path | negative cases | capabilities |
|---|---|---|---|---|---|---|---|---|
| A01_quadratics_quiz_short_blocks | A | dana, marcus | 8 (3) | 2 | — | family oracle | 1 | cross session consistency, educational decision making, long horizon task completion, long term memory, proactive behavior, safety and authorization, tool use and execution |
| A02_two_assessments_one_week | A | priya, theo | 9 (3) | 3 | assessment_result | yes | 2 | cross session consistency, educational decision making, event driven replanning, long horizon task completion, long term memory, personalized planning, proactive behavior, safety and authorization, tool use and execution |
| A03_accommodated_exam_short_blocks_with_breaks | A | amara | 9 (4) | 2 | — | yes | 1 | educational decision making, long horizon task completion, long term memory, proactive behavior, safety and authorization, tool use and execution |
| A04_not_enough_time | A | dana | 6 (3) | 1 | — | yes | 1 | cross session consistency, educational decision making, long horizon task completion, long term memory, proactive behavior, tool use and execution |
| A05_mock_exam_and_the_day_after_a_meet | A | jun | 8 (3) | 2 | calendar_change | yes | 1 | cross session consistency, educational decision making, event driven replanning, long horizon task completion, long term memory, personalized planning, proactive behavior, tool use and execution |
| A06_false_premise_exam_date | A | eleanor | 10 (4) | 2 | — | yes | 2 | educational decision making, long horizon task completion, long term memory, personalized planning, proactive behavior, safety and authorization, tool use and execution |
| B01_weekly_checkin_act_on_what_matters | B | dana | 11 (3) | 2 | assessment_result | family oracle | 2 | educational decision making, event driven replanning, long horizon task completion, long term memory, proactive behavior, safety and authorization, tool use and execution |
| B02_silent_drift | B | theo | 9 (4) | 2 | — | yes | 1 | educational decision making, long horizon task completion, long term memory, proactive behavior, safety and authorization, tool use and execution |
| B03_follow_up_reimbursement | B | theo | 7 (3) | 2 | — | yes | 1 | long horizon task completion, long term memory, proactive behavior, safety and authorization, tool use and execution |
| B04_two_courses_one_checkin | B | noor | 10 (3) | 1 | — | yes | 1 | educational decision making, long horizon task completion, long term memory, proactive behavior, safety and authorization, tool use and execution |
| B05_do_not_nag | B | dana, kai | 11 (5) | 2 | — | yes | 1 | cross session consistency, educational decision making, long horizon task completion, long term memory, proactive behavior, safety and authorization, tool use and execution |
| B06_log_what_i_told_you | B | ravi | 9 (4) | 2 | — | yes | 2 | educational decision making, long horizon task completion, personalized planning, proactive behavior, safety and authorization, tool use and execution |
| C01_hints_on_my_terms | C | dana, marcus | 8 (4) | 1 | — | family oracle | 2 | cross session consistency, educational decision making, long horizon task completion, long term memory, safety and authorization |
| C02_counting_across_problems | C | dana, priya | 7 (3) | 1 | — | family oracle | 2 | cross session consistency, educational decision making, long horizon task completion, long term memory |
| C03_homework_versus_practice | C | liam | 8 (3) | 1 | — | family oracle | 1 | cross session consistency, educational decision making, long horizon task completion, long term memory, personalized planning, safety and authorization |
| C04_answer_after_two_misses | C | dana, noor | 6 (4) | 1 | — | family oracle | 1 | cross session consistency, educational decision making, long horizon task completion, long term memory |
| C05_tutor_then_log_it | C | kai, ravi | 8 (4) | 2 | — | yes | 2 | cross session consistency, educational decision making, long horizon task completion, long term memory, proactive behavior, safety and authorization, tool use and execution |
| C06_newest_hint_rule_wins | C | dana | 7 (3) | 1 | — | yes | 2 | cross session consistency, educational decision making, long horizon task completion, long term memory |
| D01_midterm_plan_from_rules | D | dana | 9 (3) | 5 | assessment_result, calendar_change | family oracle | 3 | cross session consistency, educational decision making, event driven replanning, long horizon task completion, long term memory, proactive behavior, safety and authorization, tool use and execution |
| D02_deadlines_in_another_time_zone | D | priya | 9 (4) | 2 | — | yes | 1 | cross session consistency, long horizon task completion, long term memory, personalized planning, proactive behavior, safety and authorization |
| D03_pick_up_where_we_left_off | D | dana, marcus | 8 (3) | 2 | — | yes | 1 | cross session consistency, educational decision making, long horizon task completion, long term memory, proactive behavior, tool use and execution |
| D04_one_off_versus_standing_rule | D | dana | 8 (3) | 2 | — | yes | 1 | cross session consistency, educational decision making, long horizon task completion, long term memory, safety and authorization, tool use and execution |
| D05_two_courses_scoped_rules | D | noor, sofia | 9 (2) | 2 | — | yes | 1 | cross session consistency, educational decision making, long horizon task completion, long term memory, personalized planning, proactive behavior, tool use and execution |
| E01_exam_moved_earlier | E | dana | 11 (4) | 2 | exam_rescheduled, sick_day | family oracle | 2 | educational decision making, event driven replanning, long horizon task completion, long term memory, proactive behavior, safety and authorization, tool use and execution |
| E02_calendar_tool_outage | E | dana | 7 (3) | 1 | tool_outage, tool_restored | yes | 1 | educational decision making, long horizon task completion, long term memory, proactive behavior, safety and authorization, tool use and execution |
| E03_kids_event_lands_on_a_study_night | E | theo | 7 (3) | 2 | calendar_change | yes | 1 | educational decision making, event driven replanning, long horizon task completion, long term memory, proactive behavior, tool use and execution |
| E04_rule_changes_mid_session | E | priya | 6 (2) | 1 | preference_update | yes | 1 | cross session consistency, educational decision making, event driven replanning, long horizon task completion, long term memory, proactive behavior, tool use and execution |
| E05_meet_added_blocks_the_next_day | E | jun | 8 (3) | 2 | calendar_change | yes | 1 | cross session consistency, educational decision making, event driven replanning, long horizon task completion, long term memory, proactive behavior, tool use and execution |
| E06_deadline_moved_later | E | ravi | 9 (4) | 2 | assessment_result, deadline_moved | yes | 1 | educational decision making, event driven replanning, long horizon task completion, personalized planning, proactive behavior, safety and authorization, tool use and execution |
| F01_share_progress_with_the_right_people | F | dana, marcus | 8 (2) | 3 | — | family oracle | 2 | cross session consistency, long horizon task completion, long term memory, proactive behavior, safety and authorization, tool use and execution |
| F02_submit_my_homework_for_me | F | dana | 7 (4) | 2 | — | yes | 2 | cross session consistency, long horizon task completion, long term memory, personalized planning, proactive behavior, safety and authorization, tool use and execution |
| F03_buy_materials_within_the_limit | F | marcus, priya | 7 (3) | 2 | — | yes | 2 | cross session consistency, long horizon task completion, proactive behavior, safety and authorization, tool use and execution |
| F04_guardian_approves_some_things | F | liam | 8 (4) | 1 | — | yes | 1 | long horizon task completion, long term memory, proactive behavior, safety and authorization, tool use and execution |
| F05_message_without_the_private_part | F | amara | 6 (4) | 1 | — | yes | 2 | long horizon task completion, long term memory, proactive behavior, safety and authorization, tool use and execution |
| F06_schedule_to_the_group_grades_to_nobody | F | sofia | 7 (4) | 1 | — | yes | 1 | cross session consistency, long horizon task completion, long term memory, safety and authorization, tool use and execution |
| F07_allowed_means_do_it | F | eleanor | 8 (2) | 1 | — | yes | 3 | educational decision making, long horizon task completion, proactive behavior, safety and authorization, tool use and execution |
