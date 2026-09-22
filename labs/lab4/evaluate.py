#!/usr/bin/env python3
"""Lab 4 evaluation. Scaffolding provided; the judges are yours.

    python labs/lab4/evaluate.py --full --save reports/lab4.json
    python labs/lab4/evaluate.py --gold-context
    python labs/lab4/evaluate.py --calibrate      # writes the hand-label sheet
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from aip.chunking import markdown_chunks  # noqa: E402
from aip.cost import Budget  # noqa: E402
from aip.evals import (  # noqa: E402
    JUDGE_RUBRIC_CORRECTNESS,
    JUDGE_RUBRIC_FAITHFULNESS,
    judge_agreement,
    llm_judge,
)
from aip.retrieval import DenseRetriever, format_context  # noqa: E402
from labs.lab3.search import load_corpus, load_questions  # noqa: E402
from labs.lab4.rag import REFUSAL, answer_question, answer_with_gold_context  # noqa: E402

GOLDEN = ROOT / "data/eval/rag_golden.jsonl"
LABEL_SHEET = ROOT / "labs/lab4/calibration_labels.jsonl"


def build_retriever():
    """TODO: use YOUR Lab 3 winning configuration, not this placeholder.

    Lab 3 result: markdown-aware chunking, size=400, dense retrieval, keep
    heading prefix (default markdown_chunks behaviour).
    """
    corpus = load_corpus()
    chunks = [c for doc_id, text in corpus.items()
              for c in markdown_chunks(text, doc_id, size=400)]
    return DenseRetriever(chunks)


# Improved rubrics (D1) — still single-criterion, but explicit on partial
# refusal, paraphrase-strengthening, and refusal-vs-reference.
FAITHFULNESS_RUBRIC = """\
You grade whether an ANSWER is fully supported by the provided CONTEXT only.

Rules:
- Judge support only. Do NOT judge helpfulness, style, or real-world truth.
- Score 1 only if every factual claim is supported by the context.
- Score 0 if any claim is missing from the context, even if true in the world.
- Paraphrase is fine; strengthening a claim beyond the context is not.
- A full refusal when the context is insufficient is SUPPORTED (score 1).
- A partial answer (answers what is supported, refuses the rest) is SUPPORTED
  if the answered part is in the context and the refusal is honest.

CONTEXT:
{context}

ANSWER:
{answer}

Reply as JSON: {{"score": 0 or 1, "unsupported_claims": ["..."], "reason": "one sentence"}}
"""

CORRECTNESS_RUBRIC = """\
Compare a CANDIDATE answer to a REFERENCE answer for the same question.

Score 2 = same substantive content as the reference (wording may differ),
          OR both correctly refuse when the reference is a refusal / "not in sources".
Score 1 = partially correct: some correct content, but omits something important
          the reference states, or only answers part of a multi-part question.
Score 0 = wrong content, invents facts, OR answers confidently when the reference
          refuses, OR refuses when the reference gives a clear answer.

QUESTION: {question}
REFERENCE: {reference}
CANDIDATE: {candidate}

Reply as JSON: {{"score": 0|1|2, "reason": "one sentence"}}
"""


# ---------------------------------------------------------------------------
# judges (yours)
# ---------------------------------------------------------------------------
def judge_faithfulness(answer_text: str, context: str) -> int | None:
    """TODO D1: improve JUDGE_RUBRIC_FAITHFULNESS and return 0 or 1.

    Things the shipped rubric does not yet handle well:
      - a partial refusal (answers part, refuses part)
      - an answer that cites correctly but paraphrases into a stronger claim
      - an answer that is right about the world and wrong about the context

    Parse failures are missing data — return None, do not score as 0.
    """
    verdict = llm_judge(
        FAITHFULNESS_RUBRIC.format(context=context[:8000], answer=answer_text),
        tier="LARGE",
        max_tokens=2048,
    )
    if not isinstance(verdict, dict) or verdict.get("parse_error"):
        return None
    if "score" not in verdict:
        return None
    return int(verdict["score"])


def judge_correctness(question: str, candidate: str, reference: str) -> int | None:
    """TODO D1: returns 0, 1 or 2. Handle refusal cases explicitly --
    a correct refusal on an unanswerable question must score 2, and the
    shipped rubric does not say so.

    Parse failures are missing data — return None, do not score as 0.
    """
    # Fast path: both look like our exact refusal string
    ref_refuses = REFUSAL[:40] in (reference or "") or (reference or "").strip().startswith("I don't have enough")
    cand_refuses = (candidate or "").strip().startswith(REFUSAL[:40])
    if ref_refuses and cand_refuses:
        return 2
    if ref_refuses and not cand_refuses:
        # candidate answered when gold says refuse
        return 0

    verdict = llm_judge(
        CORRECTNESS_RUBRIC.format(
            question=question, reference=reference, candidate=candidate
        ),
        tier="LARGE",
        max_tokens=2048,
    )
    if not isinstance(verdict, dict) or verdict.get("parse_error"):
        return None
    if "score" not in verdict:
        return None
    return int(verdict["score"])


# ---------------------------------------------------------------------------
def run_full(save: str = "") -> None:
    questions = load_questions(include_unanswerable=True)
    retriever = build_retriever()
    rows = []

    with Budget(limit_usd=1.00, label="lab4-full") as b:
        for q in questions:
            a = answer_question(q["question"], retriever)
            ctx = format_context(a.hits)
            unanswerable = not q["relevant_docs"] or q["kind"] == "unanswerable"
            rows.append({
                "id": q["id"], "kind": q["kind"], "unanswerable": unanswerable,
                "answer": a.text, "refused": a.refused,
                "citations_valid": a.citations_valid,
                "invalid_citations": a.invalid_citations,
                "faithfulness": judge_faithfulness(a.text, ctx),
                "correctness": judge_correctness(q["question"], a.text, q["gold_answer"]),
                "retrieved": [h.doc_id for h in a.hits],
                "relevant": q["relevant_docs"],
            })

    ans = [r for r in rows if not r["unanswerable"]]
    una = [r for r in rows if r["unanswerable"]]
    refusals = [r for r in rows if r["refused"]]

    def _mean(vals):
        vals = [v for v in vals if v is not None]
        return statistics.fmean(vals) if vals else float("nan")

    print(f"\nn = {len(rows)}  ({len(ans)} answerable, {len(una)} unanswerable)")
    print(f"citation validity   {_mean(r['citations_valid'] for r in rows):.3f}"
          "   (target 1.000)")
    faith_vals = [r["faithfulness"] for r in rows]
    print(f"faithfulness        {_mean(faith_vals):.3f}"
          f"   (excluded {sum(1 for v in faith_vals if v is None)} parse_errors)")
    corr_vals = [r["correctness"] for r in ans]
    print(f"correctness (0-2)   {_mean(corr_vals):.3f}"
          f"  normalised {_mean(corr_vals) / 2:.3f}"
          f"   (excluded {sum(1 for v in corr_vals if v is None)} parse_errors)")
    rec = (sum(1 for r in una if r["refused"]) / len(una)) if una else 0.0
    prec = (sum(1 for r in refusals if r["unanswerable"]) / len(refusals)) if refusals else 1.0
    print(f"refusal recall      {rec:.3f}   ({sum(1 for r in una if r['refused'])}/{len(una)})")
    print(f"refusal precision   {prec:.3f}   ({len(refusals)} refusals total)")
    print("\n" + b.report())

    print("\nby question kind (mean correctness / 2):")
    kinds = sorted({r["kind"] for r in ans})
    for kind in kinds:
        sub = [r for r in ans if r["kind"] == kind]
        print(f"  {kind:<16} {_mean(r['correctness'] for r in sub)/2:.3f}"
              f"  n={len(sub)}")

    if save:
        p = ROOT / save
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(rows, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"\nsaved -> {p}   (Lab 5 reads this file)")


def run_gold_context() -> None:
    """E2: the decomposition. This is the highest-value 10 minutes in the lab."""
    questions = [q for q in load_questions() if q["relevant_docs"]]
    retriever = build_retriever()
    corpus = load_corpus()

    retrieved_scores, gold_scores = [], []
    with Budget(limit_usd=1.00, label="lab4-decomposition"):
        for q in questions:
            a = answer_question(q["question"], retriever)
            s_r = judge_correctness(q["question"], a.text, q["gold_answer"])
            if s_r is not None:
                retrieved_scores.append(s_r / 2)
            g = answer_with_gold_context(
                q["question"], [corpus[d] for d in q["relevant_docs"] if d in corpus])
            s_g = judge_correctness(q["question"], g.text, q["gold_answer"])
            if s_g is not None:
                gold_scores.append(s_g / 2)

    A = statistics.fmean(gold_scores) if gold_scores else float("nan")
    B = statistics.fmean(retrieved_scores) if retrieved_scores else float("nan")
    print(f"\ncorrectness with GOLD context       A = {A:.3f}   <- generation ceiling")
    print(f"correctness with RETRIEVED context  B = {B:.3f}   <- your system")
    print(f"retrieval-attributable loss   A - B = {A - B:.3f}")
    print(f"generation-attributable loss  1 - A = {1 - A:.3f}")
    print("\nWhichever is larger is where Lab 5 goes.")


def make_calibration_sheet() -> None:
    """D2: writes 20 answers for you to hand-label BEFORE seeing the judge."""
    rows = json.loads((ROOT / "reports/lab4.json").read_text(encoding="utf-8"))
    sample = rows[:20]
    LABEL_SHEET.write_text("\n".join(json.dumps({
        "id": r["id"], "answer": r["answer"],
        "human_faithfulness": None, "human_correctness": None,
    }, ensure_ascii=False) for r in sample) + "\n", encoding="utf-8")
    print(f"wrote {LABEL_SHEET}")
    print("Fill in human_faithfulness (0/1) and human_correctness (0/1/2), then:")
    print("  python labs/lab4/evaluate.py --kappa")


def report_kappa() -> None:
    human = [json.loads(l) for l in LABEL_SHEET.open(encoding="utf-8")]
    machine = {r["id"]: r for r in
               json.loads((ROOT / "reports/lab4.json").read_text(encoding="utf-8"))}
    for field in ("faithfulness", "correctness"):
        h = [r[f"human_{field}"] for r in human if r[f"human_{field}"] is not None]
        m = [machine[r["id"]][field] for r in human if r[f"human_{field}"] is not None]
        if not h:
            print(f"{field}: no human labels yet")
            continue
        print(f"{field}: {judge_agreement(m, h)}")
    print("\nkappa < 0.4 -> fix the rubric, not the model. Read your disagreements.")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--full", action="store_true")
    ap.add_argument("--gold-context", action="store_true")
    ap.add_argument("--calibrate", action="store_true")
    ap.add_argument("--kappa", action="store_true")
    ap.add_argument("--save", default="")
    a = ap.parse_args()
    if a.full:
        run_full(a.save)
    if a.gold_context:
        run_gold_context()
    if a.calibrate:
        make_calibration_sheet()
    if a.kappa:
        report_kappa()
    if not any([a.full, a.gold_context, a.calibrate, a.kappa]):
        ap.print_help()
