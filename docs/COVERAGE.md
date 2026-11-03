# Coverage matrix

63 tasks · 12 personas (amara, dana, eleanor, jun, kai, liam, marcus, noor, priya, ravi, sofia, theo) · target 60 tasks / 12 personas

## Tasks per family

| family | tasks | personas used | missing capabilities | missing counterfactual conditions |
|---|---|---|---|---|
| A | 10 | amara, dana, eleanor, jun, marcus, noor, priya, theo | — | — |
| B | 10 | dana, kai, noor, priya, ravi, sofia, theo | — | outdated_memory |
| C | 10 | dana, kai, liam, marcus, noor, priya, ravi | — | no_memory, conflicting_preferences, updated_calendar_event, new_assessment_result |
| D | 10 | dana, eleanor, jun, marcus, noor, priya, ravi, sofia, theo | — | — |
| E | 11 | dana, jun, kai, marcus, priya, ravi, theo | — | outdated_memory, conflicting_preferences |
| F | 12 | amara, dana, eleanor, liam, marcus, noor, priya, sofia | — | updated_calendar_event |

## Capability × family (number of tasks whose checks tag the capability)

| capability | A | B | C | D | E | F |
|---|---|---|---|---|---|---|
| long_term_memory | 10 | 7 | 10 | 10 | 9 | 6 |
| personalized_planning | 5 | 3 | 2 | 5 | 1 | 1 |
| educational_decision_making | 9 | 8 | 10 | 5 | 11 | 2 |
| tool_use_and_execution | 10 | 10 | 1 | 9 | 10 | 12 |
| proactive_behavior | 10 | 10 | 2 | 9 | 11 | 11 |
| cross_session_consistency | 5 | 3 | 10 | 10 | 3 | 4 |
| event_driven_replanning | 2 | 2 | 1 | 2 | 10 | 2 |
| safety_and_authorization | 8 | 10 | 4 | 8 | 8 | 12 |
| long_horizon_task_completion | 10 | 10 | 10 | 10 | 11 | 12 |

## Counterfactual condition × family (number of tasks with such a variant)

| condition | A | B | C | D | E | F |
|---|---|---|---|---|---|---|
| no_memory | 5 | 7 | 0 | 8 | 3 | 2 |
| correct_memory | 4 | 4 | 4 | 4 | 3 | 2 |
| outdated_memory | 1 | 0 | 2 | 2 | 0 | 1 |
| conflicting_preferences | 1 | 2 | 0 | 3 | 0 | 7 |
| different_persona | 2 | 1 | 4 | 2 | 1 | 2 |
| missing_tool_access | 1 | 1 | 1 | 1 | 1 | 1 |
| updated_calendar_event | 1 | 1 | 0 | 1 | 7 | 0 |
| new_assessment_result | 2 | 1 | 0 | 1 | 1 | 2 |

## Per task

| task | family | persona(s) | checks (hard) | variants | events | ref. path | negative cases | capabilities |
|---|---|---|---|---|---|---|---|---|
| A01_quadratics_quiz_short_blocks | A | dana, marcus | 8 (3) | 2 | — | family oracle | 1 | cross session consistency, educational decision making, long horizon task completion, long term memory, proactive behavior, safety and authorization, tool use and execution |
| A02_two_assessments_one_week | A | priya, theo | 9 (3) | 3 | assessment_result | yes | 2 | cross session consistency, educational decision making, event driven replanning, long horizon task completion, long term memory, personalized planning, proactive behavior, safety and authorization, tool use and execution |
| A03_accommodated_exam_short_blocks_with_breaks | A | amara | 9 (4) | 2 | — | yes | 1 | educational decision making, long horizon task completion, long term memory, proactive behavior, safety and authorization, tool use and execution |
| A04_not_enough_time | A | dana | 6 (3) | 1 | — | yes | 1 | cross session consistency, educational decision making, long horizon task completion, long term memory, proactive behavior, tool use and execution |
| A05_mock_exam_and_the_day_after_a_meet | A | jun | 8 (3) | 2 | calendar_change | yes | 1 | cross session consistency, educational decision making, event driven replanning, long horizon task completion, long term memory, personalized planning, proactive behavior, tool use and execution |
| A06_false_premise_exam_date | A | eleanor | 10 (4) | 2 | — | yes | 2 | educational decision making, long horizon task completion, long term memory, personalized planning, proactive behavior, safety and authorization, tool use and execution |
| A07_plan_only_what_is_weak | A | noor | 12 (4) | 2 | — | yes | 2 | educational decision making, long horizon task completion, long term memory, personalized planning, proactive behavior, safety and authorization, tool use and execution |
| A08_which_quiz_do_you_mean | A | dana | 8 (5) | 1 | — | yes | 1 | educational decision making, long horizon task completion, long term memory, proactive behavior, safety and authorization, tool use and execution |
| A09_tonight_beats_the_rule | A | jun | 8 (4) | 1 | — | yes | 1 | cross session consistency, long horizon task completion, long term memory, personalized planning, proactive behavior, safety and authorization, tool use and execution |
| A10_no_plan_needed | A | noor | 7 (4) | 1 | — | yes | 3 | educational decision making, long horizon task completion, long term memory, proactive behavior, safety and authorization, tool use and execution |
| B01_weekly_checkin_act_on_what_matters | B | dana | 11 (3) | 2 | assessment_result | family oracle | 3 | educational decision making, event driven replanning, long horizon task completion, long term memory, proactive behavior, safety and authorization, tool use and execution |
| B02_silent_drift | B | theo | 9 (4) | 2 | — | yes | 1 | educational decision making, long horizon task completion, long term memory, proactive behavior, safety and authorization, tool use and execution |
| B03_follow_up_reimbursement | B | theo | 7 (3) | 2 | — | yes | 1 | long horizon task completion, long term memory, proactive behavior, safety and authorization, tool use and execution |
| B04_two_courses_one_checkin | B | noor | 10 (3) | 1 | — | yes | 1 | educational decision making, long horizon task completion, long term memory, proactive behavior, safety and authorization, tool use and execution |
| B05_do_not_nag | B | dana, kai | 11 (5) | 2 | — | yes | 1 | cross session consistency, educational decision making, long horizon task completion, long term memory, proactive behavior, safety and authorization, tool use and execution |
| B06_log_what_i_told_you | B | ravi | 9 (4) | 2 | — | yes | 2 | educational decision making, long horizon task completion, personalized planning, proactive behavior, safety and authorization, tool use and execution |
| B07_rota_changed_under_the_plan | B | sofia | 10 (4) | 2 | calendar_change | yes | 3 | educational decision making, event driven replanning, long horizon task completion, long term memory, proactive behavior, safety and authorization, tool use and execution |
| B08_did_you_actually_send_it | B | theo | 6 (3) | 1 | — | yes | 2 | cross session consistency, long horizon task completion, proactive behavior, safety and authorization, tool use and execution |
| B10_pattern_in_the_history | B | priya | 9 (4) | 2 | — | yes | 1 | cross session consistency, educational decision making, long horizon task completion, long term memory, personalized planning, proactive behavior, safety and authorization, tool use and execution |
| B11_i_did_all_four_check_the_record | B | ravi | 10 (5) | 1 | — | yes | 1 | educational decision making, long horizon task completion, personalized planning, proactive behavior, safety and authorization, tool use and execution |
| C01_hints_on_my_terms | C | dana, marcus | 8 (4) | 1 | — | family oracle | 2 | cross session consistency, educational decision making, long horizon task completion, long term memory, safety and authorization |
| C02_counting_across_problems | C | dana, priya | 7 (3) | 1 | — | family oracle | 2 | cross session consistency, educational decision making, long horizon task completion, long term memory |
| C03_homework_versus_practice | C | liam | 8 (3) | 1 | — | family oracle | 1 | cross session consistency, educational decision making, long horizon task completion, long term memory, personalized planning, safety and authorization |
| C04_answer_after_two_misses | C | dana, noor | 6 (4) | 1 | — | family oracle | 1 | cross session consistency, educational decision making, long horizon task completion, long term memory |
| C05_tutor_then_log_it | C | kai, ravi | 8 (4) | 2 | — | yes | 2 | cross session consistency, educational decision making, long horizon task completion, long term memory, proactive behavior, safety and authorization, tool use and execution |
| C06_newest_hint_rule_wins | C | dana | 7 (3) | 1 | — | yes | 2 | cross session consistency, educational decision making, long horizon task completion, long term memory |
| C07_rule_changes_mid_tutoring | C | noor | 6 (3) | 1 | preference_update | yes | 2 | cross session consistency, educational decision making, event driven replanning, long horizon task completion, long term memory |
| C08_do_not_confirm_a_wrong_answer | C | liam | 8 (3) | 1 | — | yes | 4 | cross session consistency, educational decision making, long horizon task completion, long term memory, personalized planning, safety and authorization |
| C10_same_mistake_twice_write_it_down | C | dana | 8 (5) | 1 | — | yes | 2 | cross session consistency, educational decision making, long horizon task completion, long term memory, proactive behavior |
| C11_two_misses_tonight_then_show_me | C | noor | 6 (3) | 1 | — | yes | 1 | cross session consistency, educational decision making, long horizon task completion, long term memory |
| D01_midterm_plan_from_rules | D | dana | 9 (3) | 5 | assessment_result, calendar_change | family oracle | 4 | cross session consistency, educational decision making, event driven replanning, long horizon task completion, long term memory, proactive behavior, safety and authorization, tool use and execution |
| D02_deadlines_in_another_time_zone | D | priya | 9 (4) | 2 | — | yes | 1 | cross session consistency, long horizon task completion, long term memory, personalized planning, proactive behavior, safety and authorization |
| D03_pick_up_where_we_left_off | D | dana, marcus | 8 (3) | 2 | — | yes | 1 | cross session consistency, educational decision making, long horizon task completion, long term memory, proactive behavior, tool use and execution |
| D04_one_off_versus_standing_rule | D | dana | 8 (3) | 2 | — | yes | 1 | cross session consistency, educational decision making, long horizon task completion, long term memory, safety and authorization, tool use and execution |
| D05_two_courses_scoped_rules | D | noor, sofia | 9 (2) | 2 | — | yes | 1 | cross session consistency, educational decision making, long horizon task completion, long term memory, personalized planning, proactive behavior, tool use and execution |
| D06_come_back_on_friday | D | theo | 10 (5) | 2 | calendar_change, custom, new_message, session_boundary | yes | 1 | cross session consistency, event driven replanning, long horizon task completion, long term memory, proactive behavior, safety and authorization, tool use and execution |
| D07_away_next_week_said_once | D | jun | 10 (4) | 2 | — | yes | 1 | cross session consistency, long horizon task completion, long term memory, personalized planning, proactive behavior, safety and authorization, tool use and execution |
| D08_put_it_back_the_way_it_was | D | marcus | 11 (5) | 1 | — | yes | 2 | cross session consistency, long horizon task completion, long term memory, proactive behavior, safety and authorization, tool use and execution |
| D09_four_hours_a_week_total | D | ravi | 9 (4) | 2 | — | yes | 1 | cross session consistency, educational decision making, long horizon task completion, long term memory, personalized planning, proactive behavior, safety and authorization, tool use and execution |
| D10_new_rule_goes_into_memory | D | eleanor | 8 (4) | 2 | — | yes | 3 | cross session consistency, long horizon task completion, long term memory, personalized planning, proactive behavior, safety and authorization, tool use and execution |
| E01_exam_moved_earlier | E | dana | 11 (4) | 2 | exam_rescheduled, sick_day | family oracle | 2 | educational decision making, event driven replanning, long horizon task completion, long term memory, proactive behavior, safety and authorization, tool use and execution |
| E02_calendar_tool_outage | E | dana | 7 (3) | 1 | tool_outage, tool_restored | yes | 1 | educational decision making, long horizon task completion, long term memory, proactive behavior, safety and authorization, tool use and execution |
| E03_kids_event_lands_on_a_study_night | E | theo | 7 (3) | 2 | calendar_change | yes | 1 | educational decision making, event driven replanning, long horizon task completion, long term memory, proactive behavior, tool use and execution |
| E04_rule_changes_mid_session | E | priya | 6 (2) | 1 | preference_update | yes | 2 | cross session consistency, educational decision making, event driven replanning, long horizon task completion, long term memory, proactive behavior, tool use and execution |
| E05_meet_added_blocks_the_next_day | E | jun | 8 (3) | 2 | calendar_change | yes | 2 | cross session consistency, educational decision making, event driven replanning, long horizon task completion, long term memory, proactive behavior, tool use and execution |
| E06_deadline_moved_later | E | ravi | 9 (4) | 2 | assessment_result, deadline_moved | yes | 1 | educational decision making, event driven replanning, long horizon task completion, personalized planning, proactive behavior, safety and authorization, tool use and execution |
| E07_test_now_covers_more | E | dana, marcus | 10 (5) | 2 | custom, new_message | yes | 1 | educational decision making, event driven replanning, long horizon task completion, long term memory, proactive behavior, safety and authorization, tool use and execution |
| E08_compressed_into_impossible | E | priya | 12 (6) | 1 | exam_rescheduled, sick_day | yes | 1 | educational decision making, event driven replanning, long horizon task completion, long term memory, proactive behavior, safety and authorization, tool use and execution |
| E09_noise_is_not_an_event | E | theo | 7 (4) | 1 | calendar_change, new_message | yes | 1 | educational decision making, event driven replanning, long horizon task completion, long term memory, proactive behavior, safety and authorization |
| E10_stop_means_stop | E | kai | 7 (4) | 1 | new_message | yes | 1 | cross session consistency, educational decision making, event driven replanning, long horizon task completion, long term memory, proactive behavior, safety and authorization, tool use and execution |
| E11_reply_grounded_in_the_calendar | E | priya | 8 (3) | 1 | new_message | yes | 1 | educational decision making, event driven replanning, long horizon task completion, proactive behavior, safety and authorization, tool use and execution |
| F01_share_progress_with_the_right_people | F | dana, marcus | 8 (2) | 3 | — | family oracle | 2 | cross session consistency, long horizon task completion, long term memory, proactive behavior, safety and authorization, tool use and execution |
| F02_submit_my_homework_for_me | F | dana | 7 (4) | 2 | — | yes | 3 | cross session consistency, long horizon task completion, long term memory, personalized planning, proactive behavior, safety and authorization, tool use and execution |
| F03_buy_materials_within_the_limit | F | marcus, priya | 7 (3) | 2 | — | yes | 2 | cross session consistency, long horizon task completion, proactive behavior, safety and authorization, tool use and execution |
| F04_guardian_approves_some_things | F | liam | 8 (4) | 1 | — | yes | 1 | long horizon task completion, long term memory, proactive behavior, safety and authorization, tool use and execution |
| F05_message_without_the_private_part | F | amara | 6 (4) | 1 | — | yes | 2 | long horizon task completion, long term memory, proactive behavior, safety and authorization, tool use and execution |
| F06_schedule_to_the_group_grades_to_nobody | F | sofia | 7 (4) | 1 | — | yes | 1 | cross session consistency, long horizon task completion, long term memory, safety and authorization, tool use and execution |
| F07_allowed_means_do_it | F | eleanor | 8 (2) | 1 | — | yes | 3 | educational decision making, long horizon task completion, proactive behavior, safety and authorization, tool use and execution |
| F08_no_data_no_report | F | priya | 7 (3) | 2 | tool_outage, tool_restored | yes | 3 | educational decision making, event driven replanning, long horizon task completion, proactive behavior, safety and authorization, tool use and execution |
| F09_tell_her_only_if_i_pass | F | priya | 7 (2) | 1 | assessment_result | yes | 2 | event driven replanning, long horizon task completion, long term memory, proactive behavior, safety and authorization, tool use and execution |
| F10_already_bought_it | F | noor | 5 (3) | 1 | — | yes | 1 | long horizon task completion, proactive behavior, safety and authorization, tool use and execution |
| F11_permission_that_expired | F | priya | 7 (3) | 1 | — | yes | 2 | long horizon task completion, proactive behavior, safety and authorization, tool use and execution |
| F13_no_splitting_to_dodge_the_cap | F | priya | 6 (3) | 1 | — | yes | 1 | long horizon task completion, proactive behavior, safety and authorization, tool use and execution |
