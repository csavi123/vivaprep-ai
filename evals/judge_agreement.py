"""Compare my hand labels with the judge's verdicts (Phase 2, step 2d).

My labels:        evals/datasets/judge_labels_v1.csv   (human = yes / no, one row per key concept)
Judge's verdicts: the same RAG report the label sheet was built from
Both are joined on row_id ("s1-01#0" = question s1-01, first key concept).

No API calls. Run from the repo root:
    python -m evals.judge_agreement
"""

import csv
import json
import sys
from pathlib import Path

LABELS = Path(__file__).parent / "datasets" / "judge_labels_v1.csv"
REPORT = Path(__file__).parent / "reports" / "rag_session01_2026-11-21_191338.jsonl"


def safe_divide(top: int | float, bottom: int | float) -> float | None:
    """Return top / bottom, or None when bottom is 0 (e.g. no 'no' labels at all)."""
    if bottom == 0:
        return None
    return top / bottom


def agreement_metrics(pairs: list[tuple[bool, bool]]) -> dict:
    """pairs = [(human_says_covered, judge_says_covered), ...] -> counts and metrics.

    The human label is the reference ("the truth"); the judge is what we're checking.
    """
    both_yes = 0         # agree: covered
    both_no = 0          # agree: not covered
    judge_strict = 0     # human yes, judge no  (judge missed a covered concept)
    judge_lenient = 0    # human no,  judge yes (judge gave credit it shouldn't)

    for human, judge in pairs:
        if human and judge:
            both_yes = both_yes + 1
        elif not human and not judge:
            both_no = both_no + 1
        elif human and not judge:
            judge_strict = judge_strict + 1
        else:
            judge_lenient = judge_lenient + 1

    total = len(pairs)
    agreement = safe_divide(both_yes + both_no, total)

    # TPR: of the concepts I said were covered, how many did the judge also mark covered?
    tpr = safe_divide(both_yes, both_yes + judge_strict)
    # TNR: of the concepts I said were NOT covered, how many did the judge also mark not covered?
    tnr = safe_divide(both_no, both_no + judge_lenient)

    # Cohen's kappa: agreement after removing what two random markers would agree on by luck.
    # Luck = P(both say yes by chance) + P(both say no by chance)
    kappa = None
    if total > 0:
        human_yes_rate = (both_yes + judge_strict) / total
        judge_yes_rate = (both_yes + judge_lenient) / total
        chance = human_yes_rate * judge_yes_rate + (1 - human_yes_rate) * (1 - judge_yes_rate)
        kappa = safe_divide(agreement - chance, 1 - chance)

    return {
        "total": total,
        "both_yes": both_yes,
        "both_no": both_no,
        "judge_strict": judge_strict,
        "judge_lenient": judge_lenient,
        "agreement": agreement,
        "tpr": tpr,
        "tnr": tnr,
        "kappa": kappa,
    }


def show(value: float | None) -> str:
    """Format a metric for printing; None becomes 'n/a'."""
    if value is None:
        return "n/a"
    return f"{value:.2f}"


def load_human_labels(path: Path) -> dict:
    """My labels: row_id -> True (yes) / False (no)."""
    human_labels = {}
    with path.open(encoding="utf-8") as f:
        for row in csv.DictReader(f):
            label = row["human"].strip().lower()
            if label not in ("yes", "no"):
                raise SystemExit(f"{row['row_id']}: human label must be yes or no, got {label!r}")
            human_labels[row["row_id"]] = (label == "yes")
    return human_labels


def load_judge_verdicts(path: Path) -> dict:
    """The judge's verdicts from a report, keyed the same way as the label sheet."""
    judge_verdicts = {}     # row_id -> the verdict dict (covered + reason + concept)
    with path.open(encoding="utf-8") as f:
        for line in f:
            record = json.loads(line)
            for index, verdict in enumerate(record["verdicts"]):
                judge_verdicts[f"{record['id']}#{index}"] = verdict
    return judge_verdicts


def compare(human_labels: dict, judge_verdicts: dict) -> tuple[list, list]:
    """Join on row_id; every labelled row must have a judge verdict."""
    pairs = []
    disagreements = []
    for row_id, human in human_labels.items():
        if row_id not in judge_verdicts:
            raise SystemExit(f"{row_id} is in the label sheet but not in the report")
        verdict = judge_verdicts[row_id]
        judge = verdict["covered"]
        pairs.append((human, judge))
        if human != judge:
            disagreements.append((row_id, human, verdict))
    return pairs, disagreements


if __name__ == "__main__":
    # Reports to check: given on the command line, or the original RAG report by default
    #   python -m evals.judge_agreement                         -> full detail for the original report
    #   python -m evals.judge_agreement A.jsonl B.jsonl C.jsonl -> one summary line per report
    report_paths = []
    for arg in sys.argv[1:]:
        report_paths.append(Path(arg))
    if len(report_paths) == 0:
        report_paths.append(REPORT)

    human_labels = load_human_labels(LABELS)

    # Several reports: one line each, so runs can be compared at a glance
    if len(report_paths) > 1:
        print(f"{'report':<45} {'agree':>6} {'TPR':>5} {'TNR':>5} {'kappa':>6} {'strict':>7} {'lenient':>8}")
        for path in report_paths:
            pairs, _ = compare(human_labels, load_judge_verdicts(path))
            m = agreement_metrics(pairs)
            print(f"{path.name:<45} {show(m['agreement']):>6} {show(m['tpr']):>5} {show(m['tnr']):>5} "
                  f"{show(m['kappa']):>6} {m['judge_strict']:>7} {m['judge_lenient']:>8}")
        raise SystemExit(0)

    # One report: full detail
    pairs, disagreements = compare(human_labels, load_judge_verdicts(report_paths[0]))

    # 4. Metrics
    m = agreement_metrics(pairs)
    print(f"Rows compared: {m['total']}\n")
    print("                 judge: yes   judge: no")
    print(f"  me: yes        {m['both_yes']:>8}   {m['judge_strict']:>8}   <- judge too strict")
    print(f"  me: no         {m['judge_lenient']:>8}   {m['both_no']:>8}")
    print("                     ^ judge too lenient\n")
    print(f"Agreement:      {show(m['agreement'])}")
    print(f"TPR (my yes):   {show(m['tpr'])}   judge also said yes when I said yes")
    print(f"TNR (my no):    {show(m['tnr'])}   judge also said no when I said no")
    print(f"Cohen's kappa:  {show(m['kappa'])}")

    # 5. Every disagreement, so I can read why the judge decided differently
    print(f"\nDisagreements ({len(disagreements)}):")
    for row_id, human, verdict in disagreements:
        if human:
            kind = "TOO STRICT (me yes, judge no)"
        else:
            kind = "TOO LENIENT (me no, judge yes)"
        print(f"\n{row_id}  {kind}")
        print(f"   concept: {verdict['concept']}")
        print(f"   judge's reason: {verdict['reason']}")
