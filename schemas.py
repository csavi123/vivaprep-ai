from pydantic import BaseModel


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
