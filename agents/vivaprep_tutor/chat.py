"""Run the VivaPrep tutor agent for one chat message (used by POST /chat in api/main.py)

The API stays thin: it calls run_chat() and returns the result.
The ADK details (Runner, chat history, events) live here, next to the agent.

Two words that are easy to mix up:
    - chat_id:  one conversation. ADK calls it a "session" (session_id)
    - course_session: the course session(1-17) the student picked, or None for all sessions.
"""


from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

from langfuse import observe

from llm import HAIKU_INPUT_PRICE_PER_MTOK, HAIKU_OUTPUT_PRICE_PER_MTOK, langfuse

from .agent import root_agent   # the dot: agent.py in this same folder

# ADK files every chat under (app name, user id, chat id)
APP_NAME = "vivaprep"
USER_ID = "student"             # one fixed user for now; real per-student users come with M10 (memory)

# Stores each chat's message history and its state (where course_session goes).
# In memory only: every chat is lost when the server restarts. Fine for v1; a database-backed service later.
session_service = InMemorySessionService()

# The Runner is ADK's agent loop: send the chat to Claude, run the tools Claude asks for,
# send the results back, and repeat until Claude gives a final answer.
# Created ONCE here, not inside run_chat(): a new Runner per message would mean a new, empty
# session_service, and the tutor would forget everything said before.
runner = Runner(
    agent=root_agent,
    app_name=APP_NAME,
    session_service=session_service,
    # A message with an unknown chat_id creates that chat, so "New chat" in the UI
    # only needs a new id, not an extra "create chat" API call
    auto_create_session=True,
)


# Langfuse: one trace per tutor message. Claude calls and searches made inside it should nest under it
# (to be checked: runner.run() works on a background thread, which can split them into separate traces)
@observe(as_type="agent", name="tutor", capture_input=False, capture_output=False)
def run_chat(chat_id: str, message: str, course_session: int | None) -> dict:
    """Send one student message to the tutor agent and collect what happened.

    Returns a dict: answer, trace (the tool calls), model_calls,
    input_tokens, output_tokens, cost_usd.
    """

    # 1. Wrap the student's text the way ADK expects a message
    new_message = types.Content(role="user", parts=[types.Part(text=message)])

    # 2. Empty boxes, filled while we read the events
    answer = ""                     # the final answer text
    trace = []                      # every tool call, in order (for "How I got this answer")
    trace_by_call_id = {}           # find a tool call by its id, to attach its result later
    model_calls = 0                 # how many times Claude was called
    input_tokens = 0                # tokens Claude read, over all calls
    output_tokens = 0               # tokens Claude wrote, over all calls

    # 3. Run the agent. state_delta writes the scope BEFORE the agent starts,
    #    so search_course can read it with tool_context.state.get("course_session").
    events = runner.run(
        user_id=USER_ID,
        session_id=chat_id,             # ADK's "session" = this chat, NOT the course session
        new_message=new_message,
        state_delta={"course_session": course_session},
    )

    # The events arrive one by one, in order: Claude's tool call, the tool's result, ..., the final answer
    for event in events:
        # 3a. Claude's replies carry a token-usage tag (tool results don't)
        if event.usage_metadata is not None:
            model_calls += 1
            # "or 0": a count can be None, and None can't be added to a number
            input_tokens += event.usage_metadata.prompt_token_count or 0
            output_tokens += event.usage_metadata.candidates_token_count or 0

        # 3b. Claude asked to use a tool, e.g. search_course(query="context window")
        for call in event.get_function_calls():
            # The result isn't known yet, so status and passages start empty (filled in 3c)
            entry = {"tool": call.name, "args": dict(call.args or {}), "status": None, "passages": []}
            trace.append(entry)
            # File the same card under its id: two search_course calls have the same name, but different ids
            trace_by_call_id[call.id] = entry

        # 3c. A tool finished: attach its result to the call card with the same id
        for response in event.get_function_responses():
            entry = trace_by_call_id.get(response.id)
            if entry is None:
                continue                # a result with no call we saw: shouldn't happen, so skip it
            result = response.response or {}      # the dict search_course returned
            entry["status"] = result.get("status")
            entry["passages"] = result.get("passages", [])
            # entry is the same object that's in trace, so trace is updated too

        # 3d. The final answer: text, with no more tool calls after it.
        #     The `and` checks stop a crash if the event has no content.
        if event.is_final_response() and event.content and event.content.parts:
            texts = []
            for part in event.content.parts:
                if part.text:
                    texts.append(part.text)
            # Glue every text part together: taking only parts[0] could cut the answer short
            answer = "".join(texts)

    # 4. Back outside the loop. Same prices as llm.py, so Ask, Quiz and Tutor costs can be compared.
    #    Prices are per million tokens (MTOK), so divide by 1_000_000 (underscores just make it readable).
    cost_usd = (
        input_tokens / 1_000_000 * HAIKU_INPUT_PRICE_PER_MTOK
        + output_tokens / 1_000_000 * HAIKU_OUTPUT_PRICE_PER_MTOK
    )

    # Langfuse: the student's message in, the answer out, and the agent's own counts
    searches = 0
    for entry in trace:
        if entry["tool"] == "search_course":
            searches += 1
    langfuse.update_current_span(
        input={"message": message, "chat_id": chat_id, "course_session": course_session},
        output=answer,
        metadata={
            "model_calls": model_calls,
            "searches": searches,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cost_usd": cost_usd,
        },
    )

    # 5. Everything POST /chat sends back to the UI
    return {
        "answer": answer,
        "trace": trace,
        "model_calls": model_calls,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cost_usd": cost_usd,
    }

