from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class TutorAnswer(BaseModel):
    answer: str
    key_points: list[str]


class LLMResult(BaseModel):
    text:str
    input_tokens: int
    output_tokens: int
    cost_usd: float
    latency_s: float
    stop_reason: str
    parsed: BaseModel | None = None

class ConceptVerdict(BaseModel):
    concept: str      # the key concept being checked, copied from the test case
    covered: bool     # True if the answer covers it, False if not
    reason: str       # one short sentence explaining why


class JudgeVerdict(BaseModel):
    verdicts: list[ConceptVerdict]    # one ConceptVerdict per key concept


class Citation(BaseModel):
    block: int        # number of the context block the claim came from (1 to k); checked in rag/answer.py
    quote: str        # a short exact quote from that block that supports the answer


class GroundedAnswer(BaseModel):
    answer: str                  # the answer, written only from the context blocks
    citations: list[Citation]    # the blocks the answer relied on; empty if in_course is False
    in_course: bool              # False if the context doesn't contain the answer (the tutor abstains)


class RagResult(BaseModel):
    # Built by our code in rag/answer.py, NOT sent to Claude as a schema.
    # It keeps everything the eval (Step 5) and the app (M6) need for one question.
    question: str
    answer: GroundedAnswer                 # what Claude returned, with only the valid citations kept
    chunks: list[dict]                     # the chunks search() retrieved, in block order (block 1 = chunks[0])
    invalid_citations: list[Citation]      # citations to a block number that wasn't in the context
    cost_usd: float                        # from llm.ask(), for cost tracking
    latency_s: float                       # from llm.ask(), for latency tracking


class AskRequest(BaseModel):
    # The JSON body a client sends to POST /ask (the API's INPUT; RagResult is its OUTPUT).
    # FastAPI validates it before our code runs: a bad request gets a 422 and never costs a Claude call.

    # Remove spaces at the start and end first, so "   " becomes "" and fails min_length below
    model_config = ConfigDict(str_strip_whitespace=True)

    # min_length=3: no empty or one-letter questions (the UI checks this too, but the API can't trust its clients)
    # max_length=1000: caps the cost of one call; a real study question is well under 1000 characters
    question: str = Field(min_length=3, max_length=1000)

    # session: search only this session's chunks. Optional: None (or not sent) = search all sessions,
    # so clients that never send it (the current UI, the evals) keep working.
    # ge=1: sessions start at 1, so 0 or negatives get a 422 before any search or Claude call.
    # No le= (upper limit): a new session in the database shouldn't need a code change here.
    session: int | None = Field(default=None, ge=1)


class QuizQuestion(BaseModel):
    """One quiz question, written by Claude from ONE course chunk."""
    question_type: Literal["mcq", "short", "viva"]       # only these 3 values are valid
    question: str                                        # the question text shown to the student
    options: list[str]                                   # the choices for mcq; an empty list for short and viva
    correct_answer: str                                  # mcq: the exact text of the right option; others: a model answer
    key_points: list[str]                                # 2-4 ideas a good answer must contain; evaluate_answer grades against these
    difficulty: Literal["easy", "medium", "hard"]        # must match the difficulty the student chose; checked in code
    source_chunk_id: str                                 # the chunk this question is based on, e.g. "s01-c010"; checked in code


class Quiz(BaseModel):
    """A whole quiz for one session: what generate_quiz asks Claude to return."""
    session: int                       # the session the quiz is about
    questions: list[QuizQuestion]      # one entry per question, in the order shown to the student


class QuizRequest(BaseModel):
    """The JSON body a client sends to POST /quiz (the API's INPUT).

    FastAPI validates it before our code runs: a bad request gets a 422
    and never costs a database query or a Claude call.
    """
    # Required (no default): a quiz is always about one session.
    # ge=1: sessions start at 1. No le=: a new session shouldn't need a code change (same as AskRequest).
    session: int = Field(ge=1)

    # ge=1, le=10: at least 1 question; at most 10 caps the cost and length of one Claude call.
    num_questions: int = Field(default=5, ge=1, le=10)

    # Literal: any other value (e.g. "essay", "mixed" for difficulty) gets a 422.
    # Same values and defaults as generate_quiz() in rag/quiz.py.
    question_type: Literal["mixed", "mcq", "short", "viva"] = "mixed"
    difficulty: Literal["easy", "medium", "hard"] = "medium"


class ChatRequest(BaseModel):
    """The JSON body a client sends to POST /chat (the API's INPUT).

    FastAPI validates it before the agent runs: a bad request gets a 422
    and never costs a search or a Claude call.
    """
    # Remove spaces at the start and end first, so "   " becomes "" and fails min_length below
    model_config = ConfigDict(str_strip_whitespace=True)

    # One conversation. The UI makes it (a new random id on "New chat") and sends it with every message,
    # so the agent remembers the earlier messages. ADK calls this the session_id.
    # max_length=100: an id is short, anything longer is junk.
    chat_id: str = Field(min_length=1, max_length=100)

    # What the student typed. min_length=1, not 3 like AskRequest: in a chat, "ok" or "why?" are real messages.
    # max_length=1000: caps the cost of one call (same as AskRequest).
    message: str = Field(min_length=1, max_length=1000)

    # The session scope: None (or not sent) = all sessions. ge=1: sessions start at 1.
    # Named course_session, not session: in ADK, "session" means a chat.
    course_session: int | None = Field(default=None, ge=1)
