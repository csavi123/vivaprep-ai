"""Are the generated quizzes valid? (Phase 3, step 3b-1: free checks, no judge yet)

There is no "right quiz" to compare with, so this is reference-free: every question is checked
against the rules QUIZ_PROMPT_TEMPLATE (rag/quiz.py) promises, using plain code.

Grid: 4 sessions x 5 questions, question_type="mixed", difficulty="medium" = 20 questions.
random.seed() before each quiz makes the sampled chunks the same every run; only Claude varies.

Run from the repo root:
    python -m evals.run_quiz_eval
"""

import json
import random
from datetime import datetime
from pathlib import Path

from rag.quiz import generate_quiz
from rag.search import get_session_chunks

SESSIONS = [1, 7, 10, 14]
NUM_QUESTIONS = 5
QUESTION_TYPE = "mixed"
DIFFICULTY = "medium"
REPORTS_DIR = Path(__file__).parent / "reports"

CHECK_NAMES = [
    "real_chunk",           # source_chunk_id is a chunk of the requested session (rule 1)
    "difficulty_matches",   # difficulty is what was asked for
    "key_points_2_to_4",    # 2-4 key points (rule 5)
    "mcq_4_options",        # mcq: exactly 4 options, no duplicates (rule 3)     - n/a for short/viva
    "mcq_answer_in_options",# mcq: correct_answer is word for word one option   - n/a for short/viva
    "open_no_options",      # short/viva: options is empty (rule 4)             - n/a for mcq
]


def check_question(question: dict, difficulty: str, session_chunk_ids: set) -> dict:
    """Run the free checks on one question. Each check is True, False, or None (doesn't apply)."""
    checks = {}
    checks["real_chunk"] = question["source_chunk_id"] in session_chunk_ids
    checks["difficulty_matches"] = question["difficulty"] == difficulty
    checks["key_points_2_to_4"] = 2 <= len(question["key_points"]) <= 4

    if question["question_type"] == "mcq":
        options = question["options"]
        checks["mcq_4_options"] = len(options) == 4 and len(set(options)) == 4
        checks["mcq_answer_in_options"] = question["correct_answer"] in options
        checks["open_no_options"] = None
    else:
        checks["mcq_4_options"] = None
        checks["mcq_answer_in_options"] = None
        checks["open_no_options"] = len(question["options"]) == 0

    return checks


if __name__ == "__main__":
    stamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    REPORTS_DIR.mkdir(exist_ok=True)
    out_file = REPORTS_DIR / f"quiz_{stamp}.jsonl"

    records = []            # one per question
    quiz_problems = []      # quiz-level problems: wrong count, repeated questions, errors
    total_cost = 0.0

    for session in SESSIONS:
        # Same seed per session -> same sampled chunks every run (fair comparison between runs)
        random.seed(1000 + session)
        quiz = generate_quiz(session, num_questions=NUM_QUESTIONS,
                             question_type=QUESTION_TYPE, difficulty=DIFFICULTY)

        if quiz["status"] != "ok":
            quiz_problems.append(f"session {session}: status {quiz['status']}")
            print(f"session {session}: {quiz['status']}")
            continue
        total_cost = total_cost + quiz["cost_usd"]
        questions = quiz["questions"]

        # Quiz-level check 1: exactly NUM_QUESTIONS questions
        if len(questions) != NUM_QUESTIONS:
            quiz_problems.append(f"session {session}: {len(questions)} questions, asked for {NUM_QUESTIONS}")

        # Quiz-level check 2: no repeated question text (rule 7)
        texts = []
        for q in questions:
            texts.append(q["question"].strip().lower())
        if len(set(texts)) != len(texts):
            quiz_problems.append(f"session {session}: repeated question")

        # Question-level checks, with the session's chunks as the list of allowed source ids
        chunk_text_by_id = {}
        for chunk in get_session_chunks(session):
            chunk_text_by_id[chunk["chunk_id"]] = chunk["text"]

        for number, q in enumerate(questions, start=1):
            checks = check_question(q, DIFFICULTY, set(chunk_text_by_id))
            failed = []
            for name in CHECK_NAMES:
                if checks[name] is False:
                    failed.append(name)
            status = "ok" if len(failed) == 0 else "FAILED " + ", ".join(failed)
            print(f"session {session} q{number} [{q['question_type']}] {q['source_chunk_id']}: {status}")

            records.append({
                "session": session,
                "number": number,
                "question": q,
                "checks": checks,
                # saved for step 3b-2 (the judge reads the source passage)
                "source_text": chunk_text_by_id.get(q["source_chunk_id"]),
            })

    # Summary: pass rate per check, counting only questions the check applies to
    print(f"\n--- Summary: {len(records)} questions from {len(SESSIONS)} quizzes ---")
    for name in CHECK_NAMES:
        applies = 0
        passed = 0
        for r in records:
            value = r["checks"][name]
            if value is None:
                continue
            applies = applies + 1
            if value:
                passed = passed + 1
        print(f"{name:<22} {passed}/{applies}")

    types = {}
    for r in records:
        t = r["question"]["question_type"]
        types[t] = types.get(t, 0) + 1
    print(f"Question types: {types}")
    print(f"Quiz-level problems: {quiz_problems if quiz_problems else 'none'}")
    print(f"Cost: ${total_cost:.4f}")

    with out_file.open("w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"Saved -> {out_file}")
