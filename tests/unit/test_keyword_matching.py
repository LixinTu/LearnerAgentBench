"""Keyword checks match whole words. Each negative case below passed a real run under substring matching."""
from __future__ import annotations

import pytest

from learneragentbench.tasks import Dataset
from learneragentbench.verify.text import mentions, mentions_any, mentions_one_of


@pytest.mark.parametrize(("keyword", "text"), [
    ("lab", "your calendar shows no available slot"),
    ("lab", "review the course syllabus"),
    ("late", "first, calculate 3x"),
    ("late", "check your latest class material"),
    ("mom", "no emails require action at the moment"),
    ("on call", "the analyze_skill_gaps function call failed"),
    ("down", "per-skill breakdown"),
    ("sign", "for when it's assigned"),
    ("moved", "removed conflicting blocks"),
    ("data", "skills descriptive and data_types"),
    ("82", "knowledge: 0.078, gap: 0.822"),
    ("78", "knowledge: 0.078"),
    ("45", "reduced to 450 minutes"),
    ("40", "total study time is 540 minutes"),
    ("40", "from 19:40 to 20:10"),
    ("12", "due 2026-11-12"),
    ("82", "a score of 82.5"),
    ("november 1", "the midterm on November 14th"),
    ("nov 1", "the new exam date of Nov 12"),
    ("9th", "Sunday (19th)"),
    ("5:30", "from 15:30 to 16:30"),
    ("40 minutes", "total study time is 540 minutes"),
])
def test_part_of_another_word_or_number_does_not_count(keyword: str, text: str) -> None:
    assert not mentions(keyword, text)


@pytest.mark.parametrize(("keyword", "text"), [
    ("lab", "it clashes with your lab."),
    ("friday", "excluding Fridays"),
    ("sunday", "Sundays are off"),
    ("stop", "you asked me to stop"),
    ("stop", "I stopped as you asked"),
    ("skip", "I skipped the graphs block"),
    ("log", "you logged two blocks"),
    ("log", "not in your log"),
    ("shift", "your shifts stay"),
    ("schedule", "the exam is scheduled"),
    ("no change", "No changes were needed"),
    ("82", "your grade is 82/100"),
    ("82", "a score of 82."),
    ("82", "(82%)"),
    ("45", "the $45 practice set"),
    ("45", "$45.00"),
    ("november 9", "the new date is November 9th."),
    ("november 1", "the grant ran until November 1."),
    ("november 1", "it expired on November 1st"),
    ("12th", "Thursday the 12th"),
    ("on-call", "your on-call weeks"),
    ("clinical", "a non-clinical day"),
    ("you're on track", "You're on track for the midterm"),
])
def test_the_word_and_its_ordinary_endings_count(keyword: str, text: str) -> None:
    assert mentions(keyword, text)


def test_mentions_any_lists_what_it_found() -> None:
    assert mentions_any(["lab", "shift", 82], "Your shift clashes; the grade is 82.") == ["shift", "82"]


def test_symbols_sit_right_against_the_number() -> None:
    assert mentions("%", "you got 64%") and mentions("/100", "a grade of 64/100")
    assert not mentions("%", "you passed") and not mentions("/100", "a grade of B")


def test_alternatives_are_accepted_for_titles_and_bodies() -> None:
    assert mentions_one_of(["reimburse", "reimbursement"], "Reimbursement form to HR")
    assert mentions_one_of("mock", "Mock exam tonight")
    assert not mentions_one_of(["reimburse", "reimbursement"], "Review reimbursing")


@pytest.mark.parametrize("private", ["your accommodation letter", "her accommodations", "the Accessibility Services office", "she is accommodated",
                                     "ADHD", "extended time", "a separate room"])
def test_the_private_words_of_f05_are_still_caught_whole(private: str) -> None:
    """The exclusion list held stems (`accommodat`), which whole-word matching would have stopped catching: a privacy check
    that passes silently is the worst way for this to fail."""
    t = Dataset().load_task("F05_message_without_the_private_part")
    words = next(c.params["body_excludes"] for c in t.checks if c.id == "message_clean")
    assert mentions_any(words, f"Dear Dr. Lind, {private}, and I will miss the lab.")
    assert not mentions_any(words, "Dear Dr. Lind, I have an appointment and will miss the lab.")


def test_keyword_lists_contain_no_stems_or_blanks() -> None:
    """A keyword has to be something a sentence can contain: a stem like "reimburs" never matches now."""
    ds = Dataset()
    for tid in ds.task_ids():
        t = ds.load_task(tid)
        checks = [*t.checks, *[c for v in t.variants for c in v.checks_add]]
        for c in checks:
            if c.verifier in ("trajectory.final_mentions", "trajectory.final_not_mentions"):
                words = list(c.params.get("any_of", [])) + list(c.params.get("none_of", []))
                for w in words:
                    assert str(w).strip(), f"{tid}/{c.id}: a blank keyword"
                    assert str(w).lower() not in {"reimburs", "authoriz", "authoris", "approv", "accommodat", "accessib"}, f"{tid}/{c.id}: {w} is a stem"
