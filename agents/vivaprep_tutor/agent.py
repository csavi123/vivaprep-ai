from google.adk.agents.llm_agent import Agent
from google.adk.agents.readonly_context import ReadonlyContext
from google.adk.models.anthropic_llm import AnthropicLlm

from .tools import search_course   # The dot means: tools.py in this same folder

# The rules that never change. build_instruction() adds the session scope below them.
BASE_INSTRUCTION = (
    "You are VivaPrep, a study tutor for an AI engineering course. "
    "For any question about the course and course content call search_course before answering. "
    "Answer only from the returned passages, not from your own knowledge. "
    "Cite each passage you use with its chunk_id in square brackets, e.g. [s01-c010]. "
    "If the passages do not answer the question, say the course does not cover it. "
    "If they answer only part of it, answer that part and say which part is not covered. "
    "Explain clearly, with a short example from the passages."
)


def build_instruction(context: ReadonlyContext) -> str:
    """Build the instruction before EVERY Claude call, so Claude knows the session the student picked.

    The scope lives in the chat's state (POST /chat writes it; search_course enforces it in code).
    Here Claude only gets to READ it, so it understands "this session". It still can't change
    the scope: search_course reads it from the state, not from Claude.
    """
    # None when no session was picked (All sessions), or in `adk run`, where nobody sets it
    course_session = context.state.get("course_session")

    if course_session is None:
        scope = (
            "The student has not picked a session: search_course searches all 17 sessions. "
            "If they say 'this session', ask which session they mean."
        )
    else:
        scope = (
            f"The student has selected session {course_session}. "
            f"When they say 'this session', they mean session {course_session}. "
            f"search_course only searches session {course_session}. If the passages don't answer the question, "
            f"say that session {course_session} doesn't cover it, and that it may be in another session "
            "(they can switch the Session scope to All sessions). "
            "If they ask for a summary of the whole session, search for its main topics (a few searches), "
            "summarise what you found, and say the summary is based on the passages found, not the full session."
        )

    return BASE_INSTRUCTION + "\n\n" + scope


root_agent = Agent(
    model=AnthropicLlm(model="claude-haiku-5-5"),
    name="vivaprep_tutor",
    description="A study tutor that answers questions about the AI engineering course, with citations.",
    # A function, not a string: ADK calls it with the chat's context before each Claude call
    instruction=build_instruction,
    tools=[search_course],
)
