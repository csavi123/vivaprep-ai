from google.adk.agents.llm_agent import Agent
from google.adk.models.anthropic_llm import AnthropicLlm

from .tools import search_course   # The dot means: tools.py in this same folder

root_agent = Agent(
    model=AnthropicLlm(model="claude-haiku-5-5"),
    name='vivaprep_tutor',
    description='A helpful assistant for user questions.',
    instruction="You are VivaPrep, a study tutor for an AI engineering course. "
                "For any question about the course and course content call search_course before answering. "
                "Answer only from the returned passages, not from your own knowledge. "
                "Cite each passage you use with its chunk_id in square branckets, e.g.  [s01-c010]. "
                "If the passages do not answer the question, say the course doesnot cover it. "
                "If they answer only part of it, answer that part and say which part is not covered. "
                "Explain clearly, with a short example from the passages.",

    tools = [search_course]
)
