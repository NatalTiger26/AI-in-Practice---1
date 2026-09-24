#!/usr/bin/env python3
"""Lab 5 — the failure classifier.

    python labs/lab5/diagnose.py --input reports/lab4.json
    python labs/lab5/diagnose.py --input reports/lab4.json --pareto

Implements the T4 §5 diagnostic tree. Everything that can be decided by code
is decided by code; mode 2 needs your eyes and the script says so.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from labs.lab3.search import load_corpus, load_questions  # noqa: E402

MODES = {
    1: "missing_content",
    2: "chunk_boundary",
    3: "embedding_mismatch",
    4: "ranking",
    5: "reranker",
    6: "generation",
    7: "presentation",
}


def answer_in_corpus(gold_answer: str, corpus: dict[str, str],
                     relevant_docs: list[str]) -> bool:
    """Mode 1 test. Crude keyword overlap, deliberately.

    TODO: this is a weak test -- it will pass on a paraphrase and fail on a
    numeric answer expressed differently. Improve it, and say in your report
    how you know your improvement is better.
    """
    # Improved: (1) original token overlap, (2) key numbers present,
    # (3) substantial character n-grams — reduces false "missing content".
    text = " ".join(corpus.get(d, "") for d in relevant_docs).lower()
    if not text:
        return False
    gold = (gold_answer or "").lower()
    if not gold.strip():
        return True

    tokens = [t.strip(".,;():%") for t in gold.split() if len(t.strip(".,;():%")) > 4]
    token_hit = (
        sum(1 for t in tokens if t in text) / len(tokens) > 0.4
        if tokens else True
    )

    numbers = re.findall(r"\d+(?:\.\d+)?", gold)
    number_hit = all(n in text for n in numbers) if numbers else True

    # light n-gram: any 12-char window of gold (letters/digits only) in text
    compact = re.sub(r"[^a-z0-9]+", "", gold)
    text_c = re.sub(r"[^a-z0-9]+", "", text)
    ngram_hit = False
    if len(compact) >= 12:
        for i in range(0, len(compact) - 11, 4):
            if compact[i : i + 12] in text_c:
                ngram_hit = True
                break
    else:
        ngram_hit = compact in text_c if compact else True

    # content is "in corpus" if numbers match when present, and either tokens or ngram hit
    if numbers and not number_hit:
        return False
    return token_hit or ngram_hit


def classify(row: dict, q: dict, corpus: dict[str, str], *,
             gold_context_fixes_it: bool | None = None,
             in_top_30: bool | None = None,
             dropped_by_reranker: bool | None = None) -> tuple[int, str]:
    """Walk the T4 §5 diagnostic tree. Returns (mode, evidence).

    TODO: complete the branches marked TODO. Follow the tree in the handout;
    do not invent your own ordering, because the ordering is what makes the
    modes mutually exclusive.
    """
    # Mode 7 first: right answer, wrong citation. Check this before anything
    # else, because a mode-7 failure is not a retrieval failure at all.
    if row.get("correctness", 0) >= 2 and not row.get("citations_valid", True):
        return 7, f"correct answer, invalid citations {row.get('invalid_citations')}"

    # Mode 1: is the answer even in the corpus?
    if not answer_in_corpus(q["gold_answer"], corpus, q["relevant_docs"]):
        return 1, "gold answer content not found in the relevant documents"

    relevant = list(q.get("relevant_docs") or [])
    retrieved = list(row.get("retrieved") or [])
    # Lab 4 stores final ranked doc ids (post final_k), not a separate top-30 list.
    overlap = [d for d in retrieved if d in relevant]
    any_relevant_retrieved = bool(overlap)

    # Mode 6: does gold context fix it?
    # TODO: if gold_context_fixes_it is False, this is a generation failure.
    #       Note the direction -- gold context FIXING the answer means
    #       RETRIEVAL was at fault, not generation. People get this backwards.
    #
    # When the flag is not supplied: if the gold doc *was* in the final context
    # and the answer is still wrong, treat as generation (mode 6). If gold was
    # not in context, generation was starved → not mode 6.
    if gold_context_fixes_it is False:
        return 6, "gold context does not fix answer → generation failure"
    if gold_context_fixes_it is None and any_relevant_retrieved:
        # gold doc was available to the generator; still failed → generation
        return 6, (
            f"relevant doc(s) {overlap} were in final context but correctness="
            f"{row.get('correctness')}; generator failed with gold present"
        )

    # TODO Mode 4/5: gold doc in top 30 but not in the final k
    #       -> 5 if the reranker dropped it, else 4
    if in_top_30 is True and not any_relevant_retrieved:
        if dropped_by_reranker:
            return 5, "gold was in top-30 retrieval but dropped by reranker"
        return 4, "gold was in top-30 but not in final_k (ranking)"

    # Without an explicit top-30 probe: if we have no overlap, ranking/embedding
    # failed to surface gold in the final window.
    if not any_relevant_retrieved:
        # TODO Mode 3: gold doc not even in the top 30. Confirm by searching for
        #       the gold chunk's own text -- if THAT retrieves it, the query is the
        #       problem (mode 3). If it does not, the chunk itself is unfindable
        #       (mode 2, needs your eyes).
        #
        # Heuristic confirmation without a live retriever: if gold text lives in
        # relevant docs (mode 1 passed) but never appeared in retrieved ranks,
        # prefer embedding/query mismatch (3). Mode 2 still needs human eyes for
        # true boundary splits — mark those when the gold span is likely split.
        gold = q.get("gold_answer") or ""
        rel_text = " ".join(corpus.get(d, "") for d in relevant)
        # if a long contiguous gold span is missing from a single doc region,
        # boundary is plausible
        span = re.sub(r"\s+", " ", gold.strip())
        if len(span) > 40 and span[:40] not in re.sub(r"\s+", " ", rel_text):
            return 2, "needs_human_check: open the chunks around the gold answer"
        return 3, (
            f"relevant docs {relevant} never appeared in retrieved {retrieved[:8]} "
            f"→ embedding/query mismatch (or ranking beyond final_k)"
        )

    # Gold was in final context path already handled as mode 6 above.
    # Fallback: still wrong with ambiguous signals → human check for boundaries.
    return 2, "needs_human_check: open the chunks around the gold answer"


def pareto(tally: Counter) -> str:
    total = sum(tally.values()) or 1
    lines, cum = ["failure mode          n    share   cumulative"], 0
    for mode, n in tally.most_common():
        cum += n
        bar = "█" * round(30 * n / total)
        lines.append(f"{MODES[mode]:<20} {n:>3}   {n/total:>5.1%}   "
                     f"{cum/total:>5.1%}  {bar}")
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", default="reports/lab4.json")
    ap.add_argument("--pareto", action="store_true")
    ap.add_argument("--save", default="reports/lab5_diagnosis.json")
    args = ap.parse_args()

    rows = json.loads((ROOT / args.input).read_text(encoding="utf-8"))
    questions = {q["id"]: q for q in load_questions(include_unanswerable=True)}
    corpus = load_corpus()

    failures = [r for r in rows
                if r.get("correctness", 2) < 2 or not r.get("citations_valid", True)]
    print(f"{len(failures)} failures out of {len(rows)}\n")

    out, tally = [], Counter()
    for r in failures:
        q = questions[r["id"]]
        mode, evidence = classify(r, q, corpus)
        tally[mode] += 1
        out.append({"id": r["id"], "kind": q["kind"], "mode": mode,
                    "mode_name": MODES[mode], "evidence": evidence,
                    "question": q["question"], "answer": r["answer"][:300]})
        print(f"  {r['id']:<5} {MODES[mode]:<20} {evidence}")

    print("\n" + pareto(tally))
    print("\nCases marked needs_human_check are Part A2. Open them.")

    p = ROOT / args.save
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nsaved -> {p}")


if __name__ == "__main__":
    main()
