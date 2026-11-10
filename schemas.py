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
