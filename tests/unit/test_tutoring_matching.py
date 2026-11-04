"""The hint-policy patterns against the way models actually write. Every case here was judged wrong on a real run in
`family_c_v2_local` (see `docs/logs/phase5-family-c-v2.md`), and most of them favoured one system over another."""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from learneragentbench.harness.runner import run_one
from learneragentbench.runtime import ActionListAdapter
from learneragentbench.schema import Action, RunConfig
from learneragentbench.tasks import Dataset
from learneragentbench.verify.tutoring import CONFIRM_RE, FALSE_CONFIRM_RE, _hits, normalise, replay

DS = Dataset()
CFG = RunConfig(model="scripted", adapter="scripted", output_dir="unused")
# The final answer of every problem in family C. A new problem has to be added here, which is the point: its patterns
# then have to accept the ordinary ways of stating that answer.
ANSWERS = {
    ("C01", "P1"): "7", ("C01", "P2"): "120", ("C01", "P3"): "8",
    ("C02", "P1"): "7", ("C02", "P2"): "120", ("C02", "P3"): "8",
    ("C03", "HW1"): "5", ("C03", "PR1"): "7",
    ("C04", "P1"): "7", ("C04", "P2"): "120", ("C04", "P3"): "8",
    ("C05", "P1"): "220", ("C05", "P2"): "10",
    ("C06", "P1"): "7", ("C06", "P2"): "8",
    ("C07", "P1"): "9", ("C07", "P2"): "3",
    ("C08", "P1"): "5",
    ("C10", "P1"): "−3", ("C10", "P2"): "−2",
    ("C11", "P1"): "9", ("C11", "P2"): "3",
}


def _tutoring_tasks():
    for tid in DS.task_ids():
        if tid.startswith("C"):
            yield DS.load_task(tid)


def _problems(task) -> dict:
    return next(c.params["problems"] for c in task.checks if c.verifier == "tutoring.hint_policy")


def test_the_table_covers_every_problem() -> None:
    have = {(t.task_id[:3], p) for t in _tutoring_tasks() for p in _problems(t)}
    assert have == set(ANSWERS)


@pytest.mark.parametrize("form", [
    "So 100 / 4 = {v}.",
    r"\[ \frac{{100}}{{4}} = {v} \]",
    r"\( 100 \div 4 = {v} \)",
    "The result is {v}.",
    "It is indeed {v}, as you said.",
    "That gives **{v}**.",
])
def test_every_problem_recognises_its_answer_however_it_is_written(form: str) -> None:
    for t in _tutoring_tasks():
        for pid, prob in _problems(t).items():
            v = ANSWERS[(t.task_id[:3], pid)]
            text = form.format(v=v)
            assert _hits(prob["answer"], text), f"{t.task_id} {pid}: the answer is not recognised in {text!r}"


def test_a_number_that_only_starts_with_the_answer_is_not_the_answer() -> None:
    for t in _tutoring_tasks():
        for pid, prob in _problems(t).items():
            v = ANSWERS[(t.task_id[:3], pid)]
            for text in (f"So 100 / 4 = {v}.5.", f"The result is {v}0.", f"The result is 1{v}."):
                assert not _hits(prob["answer"], text), f"{t.task_id} {pid}: {text!r} is not the answer"


@pytest.mark.parametrize(("task_id", "problem", "text"), [
    ("C05_tutor_then_log_it", "P2", "So, you can pay for 10 full months with $225."),
    ("C07_rule_changes_mid_tutoring", "P2", r"\[ SE = \frac{12}{\sqrt{16}} = \frac{12}{4} = 3 \]"),
    ("C11_two_misses_tonight_then_show_me", "P1", "The mean of 4, 8, 9, and 15 is indeed 9."),
    ("C10_same_mistake_twice_write_it_down", "P1", "Dividing, −6 ÷ 2 = −3."),
])
def test_answers_a_real_run_stated_and_the_patterns_missed(task_id: str, problem: str, text: str) -> None:
    assert _hits(_problems(DS.load_task(task_id))[problem]["answer"], text)


def test_markup_becomes_plain_text() -> None:
    assert " ".join(normalise(r"\[ \frac{12}{\sqrt{16}} = \frac{12}{4} = 3 \]").split()) == "12 / √16 = 12 / 4 = 3"
    assert " ".join(normalise(r"\( 105 \div 15 = 7 \)").split()) == "105 ÷ 15 = 7"
    assert normalise(r"\text{SE} = **3** and it’s \boxed{3}") == "SE = 3 and it's 3"
    assert normalise("line one\nline two") == "line one\nline two"  # patterns stop at a newline


def _ctx(task_id: str, *turns: str):
    t = DS.load_task(task_id)
    steps = [SimpleNamespace(index=i, action=SimpleNamespace(type="ask_user", message=m)) for i, m in enumerate(turns[:-1])]
    steps.append(SimpleNamespace(index=len(steps), action=SimpleNamespace(type="final", message=turns[-1])))
    traj = SimpleNamespace(steps=steps, status="completed", final_message=turns[-1])
    return t, SimpleNamespace(trajectory=traj, task=t, event_step=lambda _: None)


def _findings(task_id: str, *turns: str):
    t, ctx = _ctx(task_id, *turns)
    params = next(c.params for c in t.checks if c.verifier == "tutoring.hint_policy")
    return {f["id"]: f for f in replay(ctx, params)["findings"]}


def test_repeating_the_students_own_working_is_not_a_hint() -> None:
    # The student said "52 ÷ 0.10 = 520 texts?" at P2-A1. Saying it back must neither count as an early hint nor as a due one.
    f = _findings("C02_counting_across_problems", "ok", "You calculated 52 ÷ 0.10 and got 520 texts. Is that correct?")["P2-A1"]
    assert not f["early_hint"]
    assert not f["hint_present"]


def test_a_new_step_is_still_a_hint_next_to_an_echo() -> None:
    f = _findings("C02_counting_across_problems", "ok", "You calculated 52 ÷ 0.10. Subtract the $40 first.")["P2-A1"]
    assert f["early_hint"]


def test_an_intermediate_result_is_a_step() -> None:
    # A real reply: it gives the student the $180 they had not found and says what to do with it.
    f = _findings("C05_tutor_then_log_it", "ok", "ok", "How many months can you pay for with the remaining $180 at $18 per month?")["P2-A1"]
    assert f["hint_due"]
    assert f["hint_present"]


def test_naming_the_operation_is_a_hint_on_standard_error() -> None:
    f = _findings("C11_two_misses_tonight_then_show_me", "ok", "ok",
                  "SE is the standard deviation divided by the square root of the sample size. Try again?")["P2-A1"]
    assert f["hint_present"]


def test_a_check_of_the_students_answer_is_not_a_step_towards_the_solution() -> None:
    # Our definition, stated in docs/TASK_AUTHORING.md: this is useful, but it does not tell the student the next operation.
    f = _findings("C04_answer_after_two_misses", "What's the total cost for 8 months, and does it match the $130?", "ok")["P1-A1"]
    assert f["hint_due"]
    assert not f["hint_present"]


@pytest.mark.parametrize("text", ["Great! You've got it now.", "Great, you've corrected the calculation.", "You have got that.", "That's it!"])
def test_confirmation_words(text: str) -> None:
    assert _hits([CONFIRM_RE], text)


@pytest.mark.parametrize("text", ["Let's check if that's correct.", "Let's check whether that's right.", "Make sure that's correct.", "You're right to subtract first."])
def test_questions_and_partial_praise_do_not_confirm_a_wrong_answer(text: str) -> None:
    assert not _hits([FALSE_CONFIRM_RE], text)


def test_praise_with_a_correction_does_not_confirm_a_wrong_answer() -> None:
    # A blind second reader disagreed with these two, and was right.
    f = _findings("C03_homework_versus_practice", "ok", "ok", "Great job, Liam! Subtract 4: 3x = 15. So the correct solution is x = 5, not x = 6.")["HW-A2"]
    assert f["false_confirm"] == []
    f = _findings("C03_homework_versus_practice", "ok", "ok", "Great job, Liam! Moving on.")["HW-A2"]
    assert f["false_confirm"] == ["Great job"]
    assert not _hits([FALSE_CONFIRM_RE], "You calculated 130 ÷ 15. That's correct, but remember to include the fee.")


@pytest.mark.parametrize("text", ["That's correct!", "You've got it.", "Yes, that's right."])
def test_saying_it_is_right_does(text: str) -> None:
    assert _hits([FALSE_CONFIRM_RE], text)


def _confirmation(tmp_path: Path, reply_to_correct_line: str) -> bool | None:
    # C11: P1-A1, P1-C, P2-A1, P2-C
    actions = [Action.ask("Add them up again."), Action.ask(reply_to_correct_line), Action.ask("Divide 12 by the root."), Action.final("Yes, right.")]
    out = run_one(DS, "C11_two_misses_tonight_then_show_me", "base", CFG, 0, out_root=tmp_path,
                  adapter_factory=lambda c, t, w, e: ActionListAdapter(list(actions)))
    return next(c.passed for c in out.verdict.checks if c.check_id == "confirmed_the_correct_answers")



def test_confirmation_needs_more_than_moving_on(tmp_path: Path) -> None:
    assert _confirmation(tmp_path / "a", "The mean of 4, 8, 9, and 15 is indeed 9.") is True
    assert _confirmation(tmp_path / "b", "Let's move on to your study plan.") is False
    assert _confirmation(tmp_path / "c", "Not quite, the mean is 9.") is False
