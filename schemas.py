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
