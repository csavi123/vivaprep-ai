import time
import anthropic
import dotenv
from schemas import LLMResult

dotenv.load_dotenv()
client=anthropic.Anthropic()

HAIKU_INPUT_PRICE_PER_MTOK = 0.10
HAIKU_OUTPUT_PRICE_PER_MTOK = 0.50

def ask(prompt: str, model: str="claude-haiku-5-5", max_tokens: int=1024)->LLMResult:
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