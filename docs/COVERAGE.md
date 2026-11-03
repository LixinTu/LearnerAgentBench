# Coverage matrix

29 tasks · 9 personas (amara, dana, jun, liam, marcus, noor, priya, sofia, theo) · target 60 tasks / 12 personas

## Tasks per family

| family | tasks | personas used | missing capabilities | missing counterfactual conditions |
|---|---|---|---|---|
| A | 5 | amara, dana, jun, marcus, priya, theo | — | correct_memory, outdated_memory |
| B | 4 | dana, noor, theo | personalized_planning, cross_session_consistency | outdated_memory, different_persona, missing_tool_access, updated_calendar_event |
| C | 4 | dana, liam, marcus, noor, priya | tool_use_and_execution, proactive_behavior, event_driven_replanning | no_memory, outdated_memory, conflicting_preferences, missing_tool_access, updated_calendar_event, new_assessment_result |
| D | 5 | dana, marcus, noor, priya, sofia | — | correct_memory |
| E | 5 | dana, jun, priya, theo | personalized_planning | outdated_memory, conflicting_preferences, different_persona, new_assessment_result |
| F | 6 | amara, dana, liam, marcus, priya, sofia | educational_decision_making, event_driven_replanning | correct_memory, outdated_memory, missing_tool_access, updated_calendar_event, new_assessment_result |

## Capability × family (number of tasks whose checks tag the capability)

| capability | A | B | C | D | E | F |
|---|---|---|---|---|---|---|
| long_term_memory | 5 | 4 | 4 | 5 | 5 | 5 |
| personalized_planning | 2 | 0 | 1 | 2 | 0 | 1 |
| educational_decision_making | 5 | 3 | 4 | 4 | 5 | 0 |
| tool_use_and_execution | 5 | 4 | 0 | 4 | 5 | 6 |
| proactive_behavior | 5 | 4 | 0 | 4 | 5 | 5 |
| cross_session_consistency | 4 | 0 | 4 | 5 | 2 | 4 |
| event_driven_replanning | 2 | 1 | 0 | 1 | 4 | 0 |
| safety_and_authorization | 3 | 4 | 2 | 3 | 2 | 6 |
| long_horizon_task_completion | 5 | 4 | 4 | 5 | 5 | 6 |

## Counterfactual condition × family (number of tasks with such a variant)

| condition | A | B | C | D | E | F |
|---|---|---|---|---|---|---|
| no_memory | 4 | 3 | 0 | 4 | 3 | 2 |
| correct_memory | 0 | 1 | 1 | 0 | 1 | 0 |
| outdated_memory | 0 | 0 | 0 | 2 | 0 | 0 |
| conflicting_preferences | 1 | 2 | 0 | 1 | 0 | 6 |
| different_persona | 2 | 0 | 3 | 2 | 0 | 2 |
| missing_tool_access | 1 | 0 | 0 | 1 | 1 | 0 |
| updated_calendar_event | 1 | 0 | 0 | 1 | 3 | 0 |
| new_assessment_result | 1 | 1 | 0 | 1 | 0 | 0 |

## Per task

| task | family | persona(s) | checks (hard) | variants | events | ref. path | negative cases | capabilities |
|---|---|---|---|---|---|---|---|---|
| A01_quadratics_quiz_short_blocks | A | dana, marcus | 8 (3) | 2 | — | family oracle | 1 | cross session consistency, educational decision making, long horizon task completion, long term memory, proactive behavior, safety and authorization, tool use and execution |
| A02_two_assessments_one_week | A | priya, theo | 9 (3) | 3 | assessment_result | yes | 2 | cross session consistency, educational decision making, event driven replanning, long horizon task completion, long term memory, personalized planning, proactive behavior, safety and authorization, tool use and execution |
| A03_accommodated_exam_short_blocks_with_breaks | A | amara | 9 (4) | 2 | — | yes | 1 | educational decision making, long horizon task completion, long term memory, proactive behavior, safety and authorization, tool use and execution |
| A04_not_enough_time | A | dana | 6 (3) | 1 | — | yes | 1 | cross session consistency, educational decision making, long horizon task completion, long term memory, proactive behavior, tool use and execution |
| A05_mock_exam_and_the_day_after_a_meet | A | jun | 8 (3) | 2 | calendar_change | yes | 1 | cross session consistency, educational decision making, event driven replanning, long horizon task completion, long term memory, personalized planning, proactive behavior, tool use and execution |
| B01_weekly_checkin_act_on_what_matters | B | dana | 11 (3) | 2 | assessment_result | family oracle | 2 | educational decision making, event driven replanning, long horizon task completion, long term memory, proactive behavior, safety and authorization, tool use and execution |
| B02_silent_drift | B | theo | 9 (4) | 2 | — | yes | 1 | educational decision making, long horizon task completion, long term memory, proactive behavior, safety and authorization, tool use and execution |
| B03_follow_up_reimbursement | B | theo | 7 (3) | 2 | — | yes | 1 | long horizon task completion, long term memory, proactive behavior, safety and authorization, tool use and execution |
| B04_two_courses_one_checkin | B | noor | 10 (3) | 1 | — | yes | 1 | educational decision making, long horizon task completion, long term memory, proactive behavior, safety and authorization, tool use and execution |
| C01_hints_on_my_terms | C | dana, marcus | 8 (4) | 1 | — | family oracle | 2 | cross session consistency, educational decision making, long horizon task completion, long term memory, safety and authorization |
| C02_counting_across_problems | C | dana, priya | 7 (3) | 1 | — | family oracle | 2 | cross session consistency, educational decision making, long horizon task completion, long term memory |
| C03_homework_versus_practice | C | liam | 8 (3) | 1 | — | family oracle | 1 | cross session consistency, educational decision making, long horizon task completion, long term memory, personalized planning, safety and authorization |
| C04_answer_after_two_misses | C | dana, noor | 6 (4) | 1 | — | family oracle | 1 | cross session consistency, educational decision making, long horizon task completion, long term memory |
| D01_midterm_plan_from_rules | D | dana | 9 (3) | 5 | assessment_result, calendar_change | family oracle | 3 | cross session consistency, educational decision making, event driven replanning, long horizon task completion, long term memory, proactive behavior, safety and authorization, tool use and execution |
| D02_deadlines_in_another_time_zone | D | priya | 9 (4) | 2 | — | yes | 1 | cross session consistency, long horizon task completion, long term memory, personalized planning, proactive behavior, safety and authorization |
| D03_pick_up_where_we_left_off | D | dana, marcus | 8 (3) | 2 | — | yes | 1 | cross session consistency, educational decision making, long horizon task completion, long term memory, proactive behavior, tool use and execution |
| D04_one_off_versus_standing_rule | D | dana | 8 (3) | 1 | — | yes | 1 | cross session consistency, educational decision making, long horizon task completion, long term memory, safety and authorization, tool use and execution |
| D05_two_courses_scoped_rules | D | noor, sofia | 9 (2) | 2 | — | yes | 1 | cross session consistency, educational decision making, long horizon task completion, long term memory, personalized planning, proactive behavior, tool use and execution |
| E01_exam_moved_earlier | E | dana | 11 (4) | 2 | exam_rescheduled, sick_day | family oracle | 2 | educational decision making, event driven replanning, long horizon task completion, long term memory, proactive behavior, safety and authorization, tool use and execution |
| E02_calendar_tool_outage | E | dana | 7 (3) | 1 | tool_outage, tool_restored | yes | 1 | educational decision making, long horizon task completion, long term memory, proactive behavior, safety and authorization, tool use and execution |
| E03_kids_event_lands_on_a_study_night | E | theo | 7 (3) | 2 | calendar_change | yes | 1 | educational decision making, event driven replanning, long horizon task completion, long term memory, proactive behavior, tool use and execution |
| E04_rule_changes_mid_session | E | priya | 6 (2) | 1 | preference_update | yes | 1 | cross session consistency, educational decision making, event driven replanning, long horizon task completion, long term memory, proactive behavior, tool use and execution |
| E05_meet_added_blocks_the_next_day | E | jun | 8 (3) | 2 | calendar_change | yes | 1 | cross session consistency, educational decision making, event driven replanning, long horizon task completion, long term memory, proactive behavior, tool use and execution |
| F01_share_progress_with_the_right_people | F | dana, marcus | 8 (2) | 3 | — | family oracle | 2 | cross session consistency, long horizon task completion, long term memory, proactive behavior, safety and authorization, tool use and execution |
| F02_submit_my_homework_for_me | F | dana | 7 (2) | 2 | — | yes | 2 | cross session consistency, long horizon task completion, long term memory, personalized planning, proactive behavior, safety and authorization, tool use and execution |
| F03_buy_materials_within_the_limit | F | marcus, priya | 7 (3) | 2 | — | yes | 2 | cross session consistency, long horizon task completion, proactive behavior, safety and authorization, tool use and execution |
| F04_guardian_approves_some_things | F | liam | 8 (3) | 1 | — | yes | 1 | long horizon task completion, long term memory, proactive behavior, safety and authorization, tool use and execution |
| F05_message_without_the_private_part | F | amara | 8 (5) | 1 | — | yes | 2 | long horizon task completion, long term memory, proactive behavior, safety and authorization, tool use and execution |
| F06_schedule_to_the_group_grades_to_nobody | F | sofia | 7 (4) | 1 | — | yes | 1 | cross session consistency, long horizon task completion, long term memory, safety and authorization, tool use and execution |
