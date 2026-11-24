"""The 4 possible outcomes of an abstention case. No API calls."""

from evals.run_abstention_eval import outcome


def test_abstained_when_it_should():
    assert outcome("abstain", in_course=False) == "correct"


def test_answered_when_it_should():
    assert outcome("answer", in_course=True) == "correct"


def test_answered_off_topic_is_false_answer():
    assert outcome("abstain", in_course=True) == "false_answer"


def test_refused_course_question_is_false_refusal():
    assert outcome("answer", in_course=False) == "false_refusal"
