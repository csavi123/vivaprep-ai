"""Free quiz checks on hand-made questions. No API calls, no database."""

from evals.run_quiz_eval import check_question

CHUNKS = {"s07-c001", "s07-c002"}


def make_question(**changes) -> dict:
    """A valid mcq question; pass keyword arguments to break one thing."""
    question = {
        "question_type": "mcq",
        "question": "What is the ceiling on RAG quality?",
        "options": ["Retrieval quality", "Prompt length", "Model size", "Temperature"],
        "correct_answer": "Retrieval quality",
        "key_points": ["the model only sees what was retrieved", "retrieval limits the answer"],
        "difficulty": "medium",
        "source_chunk_id": "s07-c001",
    }
    question.update(changes)
    return question


def test_valid_mcq_passes_everything():
    checks = check_question(make_question(), "medium", CHUNKS)
    assert checks["real_chunk"] and checks["difficulty_matches"] and checks["key_points_2_to_4"]
    assert checks["mcq_4_options"] and checks["mcq_answer_in_options"]
    assert checks["open_no_options"] is None          # doesn't apply to mcq


def test_invented_chunk_id_fails():
    checks = check_question(make_question(source_chunk_id="s07-c999"), "medium", CHUNKS)
    assert checks["real_chunk"] is False


def test_answer_not_word_for_word_in_options_fails():
    checks = check_question(make_question(correct_answer="retrieval quality"), "medium", CHUNKS)
    assert checks["mcq_answer_in_options"] is False


def test_duplicate_options_fail():
    options = ["Retrieval quality", "Retrieval quality", "Model size", "Temperature"]
    checks = check_question(make_question(options=options), "medium", CHUNKS)
    assert checks["mcq_4_options"] is False


def test_viva_with_options_fails():
    checks = check_question(make_question(question_type="viva"), "medium", CHUNKS)
    assert checks["open_no_options"] is False
    assert checks["mcq_4_options"] is None            # doesn't apply to viva
