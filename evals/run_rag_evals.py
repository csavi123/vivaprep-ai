"""Score the RAG tutor (rag/answer.py) on session01.jsonl with the SAME judge as run_evals.py (M5 Step 5).

run_evals.py     = closed-book: Haiku answers with no course content (ask_tutor)
run_rag_evals.py = open-book:   Haiku answers from the retrieved course chunks (answer)
Same 25 questions, same judge, so the difference in score comes from the answers.

Besides the judge's coverage score, every answer gets 4 free checks (no LLM call):
  A. quote found:      is each citation's quote really in the chunk it points to? (grounding)
  B. right session:    is each cited chunk from the question's session?           (citation accuracy)
  C. retrieval hit:    was the question's session in the retrieved chunks at all?
  D. uncited answer:   in_course=True but no citations = an answer with no evidence

Run from the repo root:
    python -m evals.run_rag_evals
"""

import json
from datetime import datetime
from pathlib import Path

from evals.run_evals import load_cases, judge   # one judge for both runs: a fair comparison
from rag.answer import answer
from rag.embeddings import load_model

DATASET = Path(__file__).parent / "datasets" / "session01.jsonl"
DATASET_SESSION = 1     # every question in session01.jsonl is about session 1
REPORTS_DIR = Path(__file__).parent / "reports"
LIMIT = None    # None = all 25; set to a number (e.g. 5) for a quick check

MARKDOWN_SYMBOLS = ["*", "_", "`", "#"]


def normalize(text: str) -> str:
    """Make chunk text and quotes comparable: lowercase, no markdown symbols, single spaces.

    Chunks are markdown ("a **token** is"), Haiku quotes plain text ("a token is").
    This is NOT fuzzy matching: after cleanup the quote must still match exactly.
    """
    text = text.lower()
    for symbol in MARKDOWN_SYMBOLS:
        text = text.replace(symbol, "")
    words = text.split()            # split() with no argument splits on any whitespace, incl. \n
    return " ".join(words)


def expected_session(case: dict) -> int:
    """The session a question belongs to.

    retrieval_v1.jsonl has "session": 1 on every line.
    session01.jsonl has no session field: every question is from session 1.
    (Its "section": "S1".."S5" is a section INSIDE session 1, not a session number.)
    """
    if "session" in case:
        return int(case["session"])
    return DATASET_SESSION


def check_citations(citations: list, chunks: list[dict], session: int) -> dict:
    """Checks A and B for every citation. Citations must already be range-checked (answer() does that)."""
    quotes_found = 0
    right_session = 0
    details = []

    for citation in citations:
        chunk = chunks[citation.block - 1]      # block numbers start at 1, list indexes at 0

        # A. Is the quote really in that chunk?
        found = normalize(citation.quote) in normalize(chunk["text"])
        if found:
            quotes_found = quotes_found + 1

        # B. Is the chunk from the question's session?
        same_session = chunk["session"] == session
        if same_session:
            right_session = right_session + 1

        details.append({
            "block": citation.block,
            "session": chunk["session"],
            "quote": citation.quote,
            "quote_found": found,
            "right_session": same_session,
        })

    return {
        "citations": len(citations),
        "quotes_found": quotes_found,
        "right_session": right_session,
        "details": details,
    }


if __name__ == "__main__":
    cases = load_cases(DATASET)
    print(f"loaded {len(cases)} cases")

    model = load_model()        # BGE-M3 is slow to load: load once, reuse for every question

    scores = []
    abstained = 0               # questions where the tutor said "not in the course"
    skipped = 0                 # questions where the judge returned nothing usable
    total_cost = 0.0            # cost of the RAG answers only (judge() doesn't return its cost)
    total_latency = 0.0
    records = []                # one dict per question, written to JSONL at the end

    # Totals for the citation and grounding checks
    all_citations = 0                   # every valid citation, over all questions
    all_quotes_found = 0                # A, summed
    all_right_session = 0               # B, summed
    questions_with_right_citation = 0   # questions with at least one citation to the right session
    retrieval_hits = 0                  # C
    uncited_answers = 0                 # D

    for case in cases[:LIMIT]:
        # 1. Answer with RAG: search -> prompt with the chunks -> GroundedAnswer
        rag_result = answer(case["question"], model=model)
        grounded = rag_result.answer            # the GroundedAnswer
        answer_text = grounded.answer           # the answer string inside it

        total_cost = total_cost + rag_result.cost_usd
        total_latency = total_latency + rag_result.latency_s

        # 2. Count abstentions separately: all concepts will be ❌, but that's a different failure
        if not grounded.in_course:
            abstained = abstained + 1

        # 3. Citation and grounding checks (before the judge, so they count even if the judge fails)
        session = expected_session(case)
        check = check_citations(grounded.citations, rag_result.chunks, session)

        all_citations = all_citations + check["citations"]
        all_quotes_found = all_quotes_found + check["quotes_found"]
        all_right_session = all_right_session + check["right_session"]
        if check["right_session"] > 0:
            questions_with_right_citation = questions_with_right_citation + 1

        # The session of each retrieved chunk, in rank order, e.g. [1, 5, 1, 4, 1]
        retrieved_sessions = []
        for chunk in rag_result.chunks:
            retrieved_sessions.append(chunk["session"])

        # C. Did search give the model the right lesson at all?
        retrieval_hit = session in retrieved_sessions
        if retrieval_hit:
            retrieval_hits = retrieval_hits + 1

        # D. Answered as in-course, but with no evidence
        uncited = grounded.in_course and check["citations"] == 0
        if uncited:
            uncited_answers = uncited_answers + 1

        # 4. Grade it with the same judge as the closed-book run
        verdict = judge(case, answer_text)

        # Guard: judge() returns None if the structured output failed; an empty list would divide by 0
        if verdict is None or len(verdict.verdicts) == 0:
            print(f"{case['id']}: SKIPPED (judge returned no verdicts)")
            skipped = skipped + 1
            continue

        # Warn if the judge didn't return one verdict per key concept
        if len(verdict.verdicts) != len(case["key_concepts"]):
            print(f"{case['id']}: WARNING judge returned {len(verdict.verdicts)} verdicts "
                  f"for {len(case['key_concepts'])} concepts")

        covered = 0
        for v in verdict.verdicts:
            if v.covered:
                covered = covered + 1
        total = len(verdict.verdicts)
        score = covered / total
        scores.append(score)

        # 5. Print it so you can read it now
        flag = "" if grounded.in_course else "  (ABSTAINED)"
        print(f"\n{case['id']}: {covered}/{total}{flag}")
        print(f"   Answer: {answer_text}")
        print(f"   Retrieved sessions: {retrieved_sessions} | retrieval hit: {'✅' if retrieval_hit else '❌'} "
              f"| invalid citations: {len(rag_result.invalid_citations)}")
        print(f"   Citations: {check['citations']} | quotes found: {check['quotes_found']}/{check['citations']} "
              f"| right session: {check['right_session']}/{check['citations']}"
              f"{'  (UNCITED ANSWER)' if uncited else ''}")
        for d in check["details"]:
            quote_mark = "✅" if d["quote_found"] else "❌ NOT FOUND"
            print(f"     [{d['block']}] s{d['session']:02d} {quote_mark}: \"{d['quote']}\"")
        for v in verdict.verdicts:
            mark = "✅" if v.covered else "❌"
            print(f"   {mark} {v.concept}: {v.reason}")

        # 6. Save everything about this question, for error analysis later
        verdict_list = []
        for v in verdict.verdicts:
            verdict_list.append({"concept": v.concept, "covered": v.covered, "reason": v.reason})

        records.append({
            "id": case["id"],
            "question": case["question"],
            "expected_session": session,
            "answer": answer_text,
            "in_course": grounded.in_course,
            "citations": check["citations"],
            "quotes_found": check["quotes_found"],
            "right_session": check["right_session"],
            "citation_details": check["details"],
            "invalid_citations": len(rag_result.invalid_citations),
            "retrieved_sessions": retrieved_sessions,
            "retrieval_hit": retrieval_hit,
            "uncited": uncited,
            "covered": covered,
            "total": total,
            "score": score,
            "verdicts": verdict_list,
            "cost_usd": rag_result.cost_usd,
            "latency_s": rag_result.latency_s,
        })

    # 7. Summary
    answered = len(cases[:LIMIT])
    print("\n--- Summary (RAG, open-book) ---")
    if len(scores) > 0:
        average = sum(scores) / len(scores)
        print(f"Coverage (judge):        {average:.2f} over {len(scores)} cases")
    print(f"Abstained:               {abstained}/{answered}")
    print(f"Skipped (no judge):      {skipped}")

    print("\nCitations and grounding (no LLM):")
    if all_citations > 0:
        print(f"A. Quote accuracy:       {all_quotes_found}/{all_citations} = {all_quotes_found / all_citations:.0%} of citations")
        print(f"B. Citation accuracy:    {all_right_session}/{all_citations} = {all_right_session / all_citations:.0%} of citations (strict: one session)")
    else:
        print("A/B. No citations at all")
    print(f"B. Questions with >=1 right citation: {questions_with_right_citation}/{answered}")
    print(f"C. Retrieval hit:        {retrieval_hits}/{answered}")
    print(f"D. Uncited answers:      {uncited_answers}/{answered}")

    print(f"\nRAG answer cost: ${total_cost:.4f} total | avg latency: {total_latency / answered:.1f}s")

    # 8. Save to a file (evals/reports/ is git-ignored: it contains course text)
    REPORTS_DIR.mkdir(exist_ok=True)
    report_file = REPORTS_DIR / f"rag_session01_{datetime.now().strftime('%Y-%m-%d_%H%M%S')}.jsonl"
    with report_file.open("w", encoding="utf-8") as f:
        for record in records:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    print(f"Saved {len(records)} results -> {report_file}")
