import random
import time
import anthropic
import dotenv
from schemas import LLMResult

dotenv.load_dotenv()
client=anthropic.Anthropic(max_retries=0)

HAIKU_INPUT_PRICE_PER_MTOK = 0.10
HAIKU_OUTPUT_PRICE_PER_MTOK = 0.50
MAX_ATTEMPTS = 3
BASE_DELAY_S = 1.0
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504, 529}

def ask(prompt: str, model: str="claude-haiku-5-5", max_tokens: int=1024)->LLMResult:
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            start_time=time.perf_counter()
            message=  client.messages.create(
                model=model,
                max_tokens=max_tokens,
                messages=[
                    {
                        "role":"user",
                        "content":prompt,
                    }
                ]
            )
            stop_time=time.perf_counter()
            
            latency= stop_time-start_time
            cost= message.usage.input_tokens/1000000 * HAIKU_INPUT_PRICE_PER_MTOK + message.usage.output_tokens/1000000 * HAIKU_OUTPUT_PRICE_PER_MTOK
            return LLMResult(text=message.content[-1].text,input_tokens=message.usage.input_tokens,output_tokens=message.usage.output_tokens,cost_usd=cost,latency_s=latency,stop_reason=message.stop_reason)
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