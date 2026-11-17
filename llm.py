import json
from datetime import datetime,timezone
from pathlib import Path
import random
import time
import anthropic
import dotenv
from schemas import LLMResult, TutorAnswer
from pydantic import BaseModel
dotenv.load_dotenv()
client=anthropic.Anthropic(max_retries=0)
LOG_FILE= Path("logs/llm_calls.jsonl")

HAIKU_INPUT_PRICE_PER_MTOK = 0.10
HAIKU_OUTPUT_PRICE_PER_MTOK = 0.50
MAX_ATTEMPTS = 3
BASE_DELAY_S = 1.0
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504, 529}

# Haiku 5.5 thinks before answering by default (hidden, but billed as output tokens),
# and thinking + answer share max_tokens. 1024 cut off long answers mid-JSON (s3-03, 2026-11-16).
# max_tokens is a ceiling, not a cost: you pay only for the tokens actually used.
# ~16000 is the docs' suggested default for non-streaming calls (higher risks HTTP timeouts).
DEFAULT_MAX_TOKENS = 16000

def log_call(model: str, result: LLMResult) -> None:
    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "model": model,
        "input_tokens": result.input_tokens,
        "output_tokens" : result.output_tokens,
        "cost_usd" : result.cost_usd,
        "latency_s" : result.latency_s,
        "stop_reason" : result.stop_reason
    }

    LOG_FILE.parent.mkdir(exist_ok=True)
    with open(LOG_FILE, "a") as f:             # "a" = add to the end of the file
        f.write(json.dumps(record) + "\n")



def ask(prompt: str, model: str="claude-haiku-5-5", max_tokens: int=DEFAULT_MAX_TOKENS,output_format: type[BaseModel] | None = None)->LLMResult:
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            start_time=time.perf_counter()
            message=  client.messages.parse(
                model=model,
                max_tokens=max_tokens,
                messages=[
                    {
                        "role":"user",
                        "content":prompt,
                    }
                ],
                output_format=output_format
            )
            stop_time=time.perf_counter()
            
            latency= stop_time-start_time
            cost= message.usage.input_tokens/1000000 * HAIKU_INPUT_PRICE_PER_MTOK + message.usage.output_tokens/1000000 * HAIKU_OUTPUT_PRICE_PER_MTOK
            result= LLMResult(text=message.content[-1].text,input_tokens=message.usage.input_tokens,output_tokens=message.usage.output_tokens,cost_usd=cost,latency_s=latency,stop_reason=message.stop_reason, parsed=message.parsed_output)
            log_call(model, result)        # write the receipt
            return result
        except anthropic.APIStatusError as e:
            if e.status_code not in RETRYABLE_STATUS_CODES:
                raise
            if attempt == MAX_ATTEMPTS:
                raise
            delay= BASE_DELAY_S * 2 ** (attempt -1 ) +random.uniform(0,1)
            print(f"Attempt {attempt} failed ({e.status_code}), retrying in {delay:.1f}s")
            time.sleep(delay)

        except anthropic.APIConnectionError:
            if attempt == MAX_ATTEMPTS:
                raise
            delay = BASE_DELAY_S * 2 ** (attempt - 1) + random.uniform(0, 1)
            print(f"Attempt {attempt} failed (connection error), retrying in {delay:.1f}s")
            time.sleep(delay)


def ask_tutor(question: str) -> TutorAnswer:
    result = ask(question, output_format=TutorAnswer)
    return result.parsed
