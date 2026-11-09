import anthropic
import dotenv

dotenv.load_dotenv()
client=anthropic.Anthropic()
message= client.messages.create(
    model="claude-haiku-5-5",
    max_tokens=1024,
    messages=[
        {
            "role":"user",
            "content":"Hello Claude",
        }
    ]
    )
print(message.content[-1].text)
print(message.usage.input_tokens)
print(message.usage.output_tokens)
cost= message.usage.input_tokens/1000000 * 0.10 + message.usage.output_tokens/1000000 * 0.50
print(f"Cost: ${cost:.6f}")