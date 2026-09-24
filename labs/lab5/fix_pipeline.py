#!/usr/bin/env python3
"""Lab 5 — one fix at a time (mode 6: generation).

Dominant failure mode after diagnosis: generation (gold doc in context,
answer still incomplete/wrong). Fix under test:

  * Reduce distractors: final_k 5 → 3 (less middle-context noise)
  * Put highest-score hit first (already true for dense; keep explicit)
  * Stronger instruction to cover every part of multi-part questions

    python labs/lab5/fix_pipeline.py --before-after --save reports/lab5_before_after.json

Prediction (stated before measuring): recover ~4–6 of 15 generation failures
on multi_hop / paraphrase / partial single_hop; expect little change on
refusal; cost should stay ≤ 2× Lab 4 generate path (no extra model calls).
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from aip.cost import Budget  # noqa: E402
from aip.retrieval import format_context  # noqa: E402
from labs.lab3.search import load_questions  # noqa: E402
from labs.lab4.evaluate import (  # noqa: E402
    build_retriever,
    judge_correctness,
    judge_faithfulness,
)
from labs.lab4.rag import REFUSAL, answer_question  # noqa: E402

# Mode-6 prompt addendum — one variable: answer-all-parts discipline
MULTI_PART_SYSTEM_EXTRA = """
When the question has multiple parts or asks for a comparison, answer every
part that the sources support. Do not stop after the first clause. If a part
is unsupported, say so and refuse only that part.
""".strip()


def answer_v2(question: str, retriever, *, tier: str = "MAIN"):
    """v2 generate path: fewer context chunks + multi-part instruction.

    Implemented by calling the same Lab 4 pipeline with final_k=3 and a
    one-shot system prefix via monkeypatch-free wrapper: we retrieve here,
    then reuse Lab 4 validate/repair by temporarily narrowing hits.
    """
    from labs.lab4 import rag as rag_mod

    # retrieve wider, keep only top 3 for generation (fewer distractors)
    hits = retriever.search(question, k=12)
    hits = list(hits)[:3]

    original = rag_mod.ANSWER_SYSTEM
    rag_mod.ANSWER_SYSTEM = original + "\n\n" + MULTI_PART_SYSTEM_EXTRA
    try:
        # bypass outer retrieve by using gold-style path pieces
        text, finish = rag_mod._generate(question, hits, tier=tier)
        v = rag_mod.validate_answer(text, len(hits), finish)
        if not v["valid"] and not v["refused"]:
            # same B3 policy as Lab 4
            from aip.guards import delimit_untrusted
            from aip.llm import chat

            repair = (
                f"Previous answer failed validation ({v['reason']}). "
                f"Use only sources [1]..[{len(hits)}] with citations, "
                f"or the exact refusal sentence."
            )
            ctx = delimit_untrusted(format_context(hits, max_chars=8000))
            prompt = f"{ctx}\n\nQuestion: {question}\n\n{repair}\n\nAnswer with citations:"
            result = chat(
                prompt, system=rag_mod.ANSWER_SYSTEM, tier=tier,
                temperature=0.0, max_tokens=600, return_full=True,
            )
            if isinstance(result, dict):
                text = (result.get("text") or "").strip()
                finish = result.get("finish_reason")
            else:
                text = str(result).strip()
                finish = None
            v = rag_mod.validate_answer(text, len(hits), finish)
            if not v["valid"] and not v["refused"]:
                text = REFUSAL
                v = rag_mod.validate_answer(text, len(hits), None)
        from labs.lab4.rag import Answer
        return Answer(
            question=question,
            text=text,
            hits=list(hits),
            refused=v["refused"],
            citations_valid=v["valid"] or v["refused"],
            invalid_citations=v["invalid_citations"],
            n_citations=v["n_citations"],
            truncated=v["truncated"],
        )
    finally:
        rag_mod.ANSWER_SYSTEM = original


def run_before_after(save: str = "") -> None:
    """Re-score Lab 4 failures + a small pass sample with v2; compare to lab4.json."""
    lab4_path = ROOT / "reports/lab4.json"
    if not lab4_path.exists():
        print("Need reports/lab4.json")
        return

    lab4 = json.loads(lab4_path.read_text(encoding="utf-8"))
    by_id = {r["id"]: r for r in lab4}
    questions = {q["id"]: q for q in load_questions(include_unanswerable=True)}
    retriever = build_retriever()

    # focus: all failures + a few previous passes for regression
    fail_ids = [r["id"] for r in lab4
                if r.get("correctness", 2) < 2 or not r.get("citations_valid", True)]
    pass_ids = [r["id"] for r in lab4
                if r.get("correctness", 2) >= 2 and r.get("citations_valid", True)][:8]
    target_ids = fail_ids + pass_ids

    rows = []
    with Budget(limit_usd=1.50, label="lab5-v2") as b:
        for qid in target_ids:
            q = questions[qid]
            a = answer_v2(q["question"], retriever)
            ctx = format_context(a.hits)
            unanswerable = not q["relevant_docs"] or q["kind"] == "unanswerable"
            faith = judge_faithfulness(a.text, ctx)
            corr = judge_correctness(q["question"], a.text, q["gold_answer"])
            prev = by_id[qid]
            rows.append({
                "id": qid,
                "kind": q["kind"],
                "unanswerable": unanswerable,
                "answer": a.text,
                "refused": a.refused,
                "citations_valid": a.citations_valid,
                "faithfulness": faith,
                "correctness": corr,
                "v1_correctness": prev.get("correctness"),
                "v1_faithfulness": prev.get("faithfulness"),
                "v1_refused": prev.get("refused"),
                "was_failure": qid in fail_ids,
            })

    def mean_corr(subset):
        vals = [r["correctness"] for r in subset if r["correctness"] is not None]
        return statistics.fmean(vals) / 2 if vals else float("nan")

    def mean_corr_v1(subset):
        vals = [r["v1_correctness"] for r in subset if r["v1_correctness"] is not None]
        return statistics.fmean(vals) / 2 if vals else float("nan")

    fails = [r for r in rows if r["was_failure"]]
    recovered = sum(
        1 for r in fails
        if (r["correctness"] or 0) >= 2 and (r["v1_correctness"] or 0) < 2
    )
    regressed = sum(
        1 for r in rows
        if not r["was_failure"]
        and (r["correctness"] is not None and r["correctness"] < 2)
        and (r["v1_correctness"] or 0) >= 2
    )

    print(f"scored {len(rows)} questions ({len(fails)} former failures)")
    print(f"v1 correctness (failures only)  {mean_corr_v1(fails):.3f}")
    print(f"v2 correctness (failures only)  {mean_corr(fails):.3f}")
    print(f"recovered failures (corr 0/1 → 2): {recovered} / {len(fails)}")
    print(f"regressions on former passes:     {regressed}")
    print(b.report())

    if save:
        p = ROOT / save
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({
            "prediction": "recover 4-6 of 15 generation failures; cost ≤ 2x",
            "fix": "final_k=3 + multi-part instruction (mode 6)",
            "recovered": recovered,
            "n_failures_tested": len(fails),
            "regressions": regressed,
            "rows": rows,
        }, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"saved -> {p}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--before-after", action="store_true")
    ap.add_argument("--save", default="reports/lab5_before_after.json")
    a = ap.parse_args()
    if a.before_after:
        run_before_after(a.save)
    else:
        ap.print_help()
