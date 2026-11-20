"""Quiz generation: turn random chunks of one session into a Quiz (schemas.py).

Shared by two callers, so it lives here and not in the agent's folder:
  - api/main.py              POST /quiz (the Quiz tab form calls the function directly)
  - agents/vivaprep_tutor    the agent gets generate_quiz as a tool (chat)

Importing this file loads nothing heavy: no BGE-M3 (the quiz reads chunks with plain SQL)
and no ADK. That keeps the API light and its Docker image free of ADK.
"""

import random
from typing import Literal

from llm import ask
from rag.search import get_session_chunks
from schemas import Quiz

# Instructions for generate_quiz(): Claude turns the sampled passages into a Quiz (schemas.py).
# The 4 {placeholders} are filled with .format() in generate_quiz().
QUIZ_PROMPT_TEMPLATE = """You write quiz questions for a student of an AI engineering course.
Write exactly {num_questions} questions using ONLY the course passages below.

Question type: {question_type}
- mcq: a multiple-choice question
- short: answered in 1-2 sentences
- viva: an oral-exam question that asks the student to explain why or how
- mixed: use a mix of mcq, short and viva

Difficulty: {difficulty}
- easy: recall a fact or definition stated directly in a passage
- medium: explain why or how, or connect two ideas from a passage
- hard: apply an idea to a new situation, or weigh a trade-off
Every question must have this difficulty.

Rules:
1. Base each question on ONE passage. Set source_chunk_id to that passage's label exactly, e.g. s01-c010.
2. Use only facts from the passages. Do not add facts from your own knowledge.
3. For mcq: give exactly 4 options, exactly one correct, copy correct_answer word for word from the correct option,
   make the wrong options plausible.
4. For short and viva: set options to an empty list and write correct_answer as a 2-3 sentence model answer.
5. key_points: 2-4 short ideas a good answer must contain, each stated in the passage.
6. Test understanding of ideas. Do not ask about headings, section numbers or trivia.
7. Do not test the same idea twice.

<passages>
{passages}
</passages>"""


def format_passages(chunks: list[dict]) -> str:
    """Turn chunks into labelled blocks that Claude can cite by chunk_id.

    A helper, not a tool: it is not in the agent's tools list, so Claude never sees it.
    """
    blocks = []
    for chunk in chunks:
        label = f"[{chunk['chunk_id']}]"            # e.g. [s01-c010]: the exact text Claude copies into source_chunk_id
        block = label + "\n" + chunk["text"]
        blocks.append(block)

    # A blank line between blocks, so Claude can see where one passage ends and the next starts
    return "\n\n".join(blocks)


def generate_quiz(
    session: int,
    num_questions: int = 5,
    question_type: Literal["mixed", "mcq", "short", "viva"] = "mixed",
    difficulty: Literal["easy", "medium", "hard"] = "medium",
) -> dict:
    """Write a practice quiz from one session of the AI engineering course.

    Use this when the student asks to be quizzed or tested on a session.

    session: the session number (1 to 17).
    num_questions: how many questions to write, 1 to 10.
    question_type: "mcq", "short", "viva", or "mixed" for a mix of all three.
    difficulty: "easy", "medium" or "hard".

    Returns the questions with their answer key (correct_answer, key_points).
    Show the student the questions and options only. Do NOT reveal correct_answer
    or key_points until the student has answered.
    """
    # 1. Get every chunk of the session, in reading order
    chunks = get_session_chunks(session)

    # 2. Guard clause: no chunks means the session doesn't exist, so don't call Claude (no cost)
    if not chunks:
        return {"status": "no_chunks", "session": session, "questions": []}

    # 3. Pick random chunks, so each quiz tests different parts of the session.
    #    min(): a session can have fewer chunks than the questions asked for.
    how_many = min(num_questions, len(chunks))
    sampled = random.sample(chunks, how_many)

    # 4. Fill the 4 placeholders of the prompt
    prompt = QUIZ_PROMPT_TEMPLATE.format(
        num_questions=num_questions,
        question_type=question_type,
        difficulty=difficulty,
        passages=format_passages(sampled),
    )

    # 5. Ask Claude for a Quiz (llm.ask logs tokens and cost)
    result = ask(prompt, output_format=Quiz)
    if result.parsed is None:
        # Happens if Claude hits max_tokens mid-JSON (same case as rag/answer.py)
        return {
            "status": "error",
            "session": session,
            "questions": [],
            "message": f"No structured quiz (stop_reason={result.stop_reason})",
        }
    quiz = result.parsed

    # 6. Return plain dicts: ADK sends tool results to Claude as JSON,
    #    and .model_dump() turns each Pydantic object into a plain dict
    questions = []
    for question in quiz.questions:
        questions.append(question.model_dump())

    return {"status": "ok", "session": session, "questions": questions, "cost_usd": result.cost_usd}
