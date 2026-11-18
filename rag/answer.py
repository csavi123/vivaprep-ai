"""Answer a question from the course chunks, with citations (M5: the "G" in RAG).

Run from the repo root:
    python -m rag.answer "What is a token?"
"""

import sys

from llm import ask
from rag.search import search
from schemas import GroundedAnswer, RagResult

# The rules come first, then the context, then the question.
# The Anthropic docs recommend long documents before the question.
# (llm.ask() has no system= parameter yet, see docs/LIMITS.md, so the rules go in the prompt.)
PROMPT_TEMPLATE = """You are a tutor for an AI engineering course. Answer the student's question using ONLY the numbered context blocks below.

Rules:
1. Use only information from the context blocks. Do not add facts from your own knowledge.
2. For every block you used, add a citation with its block number and a short quote copied exactly from that block.
3. If the context blocks do not contain the answer, set in_course to false, say briefly that the course material does not cover it, and leave citations empty.

<context>
{context}
</context>

<question>
{question}
</question>"""


def format_context(chunks: list[dict]) -> str:
    """Turn search results into numbered blocks that Claude can cite.

    Block [1] is chunks[0], block [2] is chunks[1], and so on.
    Later, a citation with block=2 is mapped back to chunks[1].
    """
    blocks = []
    for number, chunk in enumerate(chunks, start=1):     # start=1: blocks are numbered 1 to k, not 0 to k-1
        # The heading path is already the first line of chunk["text"] (the chunker adds it), so don't repeat it here
        label = f"[{number}] Session {chunk['session']}"
        block = label + "\n" + chunk["text"]
        blocks.append(block)

    # A blank line between blocks, so Claude can see where one ends and the next starts
    return "\n\n".join(blocks)


def answer(question: str, k: int = 5, model=None, session: int | None = None) -> RagResult:
    """Retrieve k chunks, ask Claude to answer from them, and check the citations."""
    # 1. Retrieve: the k chunks closest in meaning to the question
    #    (model= is the BGE-M3 embedding model; pass it in when answering many questions, it's slow to load)
    chunks = search(question, k=k, model=model, session=session)

    # 2. Format the chunks as numbered blocks
    context = format_context(chunks)

    # 3. Fill the template: rules + context + question
    prompt = PROMPT_TEMPLATE.format(context=context, question=question)

    # 4. Ask Claude for a GroundedAnswer
    result = ask(prompt, output_format=GroundedAnswer)
    if result.parsed is None:
        # Happens if Claude hits max_tokens mid-JSON (docs/LIMITS.md); fail loudly here, not later
        raise ValueError(f"No structured answer (stop_reason={result.stop_reason}) for: {question}")
    grounded = result.parsed

    # 5. Validate the citations: a block number must point at one of the chunks we sent.
    #    Invalid ones are moved out (not just deleted) so the eval can count them.
    valid_citations = []
    invalid_citations = []
    for citation in grounded.citations:
        if 1 <= citation.block <= len(chunks):
            valid_citations.append(citation)
        else:
            invalid_citations.append(citation)
    grounded.citations = valid_citations

    # 6. Return everything the eval needs
    return RagResult(
        question=question,
        answer=grounded,
        chunks=chunks,
        invalid_citations=invalid_citations,
        cost_usd=result.cost_usd,
        latency_s=result.latency_s,
    )


def main() -> None:
    # sys.argv = ['rag/answer.py', 'your question']: [0] is the script, [1] is the question
    if len(sys.argv) < 2:
        raise SystemExit('Usage: python -m rag.answer "your question"')
    question = sys.argv[1]

    rag = answer(question)

    print("ANSWER:")
    print(rag.answer.answer)
    print()
    print(f"in_course: {rag.answer.in_course}")
    print()
    print("CITATIONS:")
    for citation in rag.answer.citations:
        chunk = rag.chunks[citation.block - 1]        # block numbers start at 1, list indexes start at 0
        print(f"  [{citation.block}] Session {chunk['session']} ({chunk['chunk_id']}): \"{citation.quote}\"")
    if rag.invalid_citations:
        print(f"INVALID citations (block not in context): {rag.invalid_citations}")
    print()
    print(f"cost: ${rag.cost_usd:.5f}   latency: {rag.latency_s:.1f}s")


if __name__ == "__main__":
    main()
