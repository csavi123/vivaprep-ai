import json
from pathlib import Path
from llm import ask,ask_tutor
from schemas import JudgeVerdict

DATASET= Path("evals/datasets/session01.jsonl")
LIMIT = None
JUDGE_PROMPT = """You are grading a student's answer against a list of key concepts.

Question:
{question}

Student's answer:
{answer}

Key concepts:
{concepts}

For EACH key concept, decide whether the student's answer covers it.
- Judge the meaning, not the exact wording. Different words that say the same thing count as covered.
- Only use what is written in the student's answer. Do not give credit for things the answer does not say.
- If the answer says something that contradicts the concept, it is not covered.
Return one verdict per key concept, in the same order, with a one-sentence reason."""

# Judge prompts by name, for evals/rejudge.py. A rubric-based v2 was tried and dropped (D024):
# no better than v1 on 73 hand labels (kappa 0.74 vs 0.79). Its rules are in evals/judge_rubric.md.
JUDGE_PROMPTS = {"v1": JUDGE_PROMPT}


def load_cases(path: Path) -> list[dict]:
    cases= []
    with open(path) as f:
        for line in f:
            data_dict= json.loads(line.strip())
          #  print (data_dict)
            cases.append(data_dict)
    return cases



def judge(case: dict, answer_text: str, prompt_template: str = JUDGE_PROMPT) -> JudgeVerdict:
    # prompt_template defaults to v1, so run_evals.py and run_rag_evals.py don't change until I decide
    concepts = "\n".join(f"- {c}" for c in case["key_concepts"])
    prompt = prompt_template.format(
        question=case["question"],
        answer=answer_text,
        concepts=concepts,
    )
    result=ask(prompt,output_format=JudgeVerdict)
    return result.parsed


if __name__ == "__main__":
   
    cases= load_cases(DATASET)

    print(f"loaded {len(cases)} cases")
    scores = []
    for case in cases[:LIMIT]:
        tutor_answer= ask_tutor(case["question"])
        verdict = judge(case, tutor_answer.answer)

        covered= sum(1 for v in verdict.verdicts if v.covered)
        total= len(verdict.verdicts)
        score = covered / total
        scores.append(score)
        print(f"{case['id']}: {covered}/{total}")
        print(f"   Answer: {tutor_answer.answer}")
        for v in verdict.verdicts:
            mark = "✅"  if v.covered else  "❌"
            print(f" {mark} {v.concept}: {v.reason}")
    average= sum(scores)/ len(scores)
    print(f"\nAverage score: {average:.2f} over {len(scores)} cases")
