#!/usr/bin/env python3
"""Lab 3 — retrieval sweeps.

The scaffolding (corpus loading, metric computation, table printing) is
written for you. The sweeps are yours.

    python labs/lab3/search.py --baseline
    python labs/lab3/search.py --sweep chunking
    python labs/lab3/search.py --sweep retrieval
    python labs/lab3/search.py --sweep rerank
    python labs/lab3/search.py --sweep index
"""
from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
import time
from collections import defaultdict
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from aip.chunking import STRATEGIES, Chunk  # noqa: E402
from aip.evals import retrieval_metrics  # noqa: E402
from aip.retrieval import (  # noqa: E402
    Bm25Retriever,
    ChromaRetriever,
    CrossEncoderReranker,
    DenseRetriever,
    HybridRetriever,
    LLMReranker,
    Retriever,
)

CORPUS_DIR = ROOT / "data/corpus"
GOLDEN = ROOT / "data/eval/rag_golden.jsonl"


# ---------------------------------------------------------------------------
# scaffolding (provided)
# ---------------------------------------------------------------------------
def load_corpus() -> dict[str, str]:
    return {p.stem: p.read_text(encoding="utf-8") for p in sorted(CORPUS_DIR.glob("*.md"))}


def load_questions(include_unanswerable: bool = False) -> list[dict]:
    rows = [json.loads(l) for l in GOLDEN.open(encoding="utf-8")]
    if include_unanswerable:
        return rows
    # THREE questions (Q36, Q38, Q39) have no relevant document, so recall and
    # nDCG are undefined for them -- you cannot rank correctly against an empty
    # relevant set. Dropping them leaves n = 42.
    #
    # Do not confuse that with the FIVE questions of kind 'unanswerable'
    # (Q36-Q40): two of those do keep relevant documents, because part of what
    # they ask is supported. All five are measured properly in Lab 4, as
    # refusal precision and recall.
    #
    # Excluding the three is correct -- but say so in your report rather than
    # letting an unexplained n = 42 pass for a stated 45.
    return [r for r in rows if r["relevant_docs"]]


def build_chunks(corpus: dict[str, str], strategy: str = "sliding",
                 size: int = 800, **kw) -> list[Chunk]:
    fn = STRATEGIES[strategy]
    out: list[Chunk] = []
    for doc_id, text in corpus.items():
        try:
            out.extend(fn(text, doc_id, size=size, **kw))
        except TypeError:                       # chunker without that kwarg
            out.extend(fn(text, doc_id, size=size))
    return out


def evaluate(retriever: Retriever, questions: list[dict], k: int = 10,
             reranker=None, final_k: int = 5) -> dict:
    """Run every question, return aggregate metrics + per-kind breakdown."""
    agg: dict[str, list[float]] = defaultdict(list)
    by_kind: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    latencies: list[float] = []
    per_q: dict[str, float] = {}
    per_q_mrr: dict[str, float] = {}

    for q in questions:
        t0 = time.perf_counter()
        hits = retriever.search(q["question"], k=k)
        if reranker is not None:
            hits = reranker.rerank(q["question"], hits, k=final_k)
        latencies.append((time.perf_counter() - t0) * 1000)

        # A document counts as retrieved at rank r if any of its chunks does.
        seen, ranked = set(), []
        for h in hits:
            if h.doc_id not in seen:
                seen.add(h.doc_id)
                ranked.append(h.doc_id)

        m = retrieval_metrics(ranked, q["relevant_docs"], ks=(1, 3, 5, 10))
        per_q[q["id"]] = m["hit_rate@5"]
        per_q_mrr[q["id"]] = m["mrr"]
        for key, val in m.items():
            agg[key].append(val)
            by_kind[q["kind"]][key].append(val)

    out = {k2: statistics.fmean(v) for k2, v in agg.items()}
    out["latency_p50_ms"] = statistics.median(latencies)
    out["latency_p95_ms"] = sorted(latencies)[int(0.95 * (len(latencies) - 1))]
    out["_by_kind"] = {kind: {k2: statistics.fmean(v) for k2, v in d.items()}
                       for kind, d in by_kind.items()}
    out["_per_question"] = per_q            # hit_rate@5 -- saturated, see kind_table
    out["_per_question_mrr"] = per_q_mrr    # use this one for Part B
    out["_kind_n"] = {kind: len(d["mrr"]) for kind, d in by_kind.items()}
    return out


def table(rows: dict[str, dict], cols: tuple[str, ...] =
          ("hit_rate@1", "hit_rate@5", "recall@5", "mrr", "ndcg@10",
           "latency_p95_ms")) -> str:
    name_w = max(len(n) for n in rows) + 2
    head = f"{'config':<{name_w}}" + "".join(f"{c:>15}" for c in cols)
    lines = [head, "-" * len(head)]
    for name, m in rows.items():
        lines.append(f"{name:<{name_w}}" + "".join(f"{m.get(c, 0):>15.4f}" for c in cols))
    return "\n".join(lines)


def kind_table(metrics: dict, col: str = "hit_rate@5") -> str:
    """Break a result down by question kind.

    NOTE the default column. `hit_rate@5` is saturated on this corpus -- every
    retriever scores 0.93-0.98 -- so this table will look flat and tell you
    nothing. Pass col='mrr' or col='ndcg@10' for Part B. The default is left
    saturated on purpose.
    """
    bk, counts = metrics["_by_kind"], metrics.get("_kind_n", {})
    w = max(len(k) for k in bk) + 2
    lines = [f"{'kind':<{w}}{col:>12}{'n':>6}", "-" * (w + 18)]
    for kind, m in sorted(bk.items()):
        lines.append(f"{kind:<{w}}{m.get(col, 0):>12.4f}{counts.get(kind, 0):>6}")
    return "\n".join(lines)


def calc_final_metric(m: dict) -> float:
    # personal combined score: quality product / latency (same idea as earlier runs)
    final = 1.0
    for metric in ["hit_rate@1", "hit_rate@5", "recall@5", "mrr", "ndcg@10"]:
        final *= max(m.get(metric, 0.0), 1e-9)
    final /= max(m.get("latency_p95_ms", 1.0), 1e-6)
    return final


# ---------------------------------------------------------------------------
# sweeps (yours)
# ---------------------------------------------------------------------------
def sweep_baseline() -> None:
    corpus, questions = load_corpus(), load_questions()
    chunks = build_chunks(corpus, "sliding", 800, overlap=150)
    print(f"corpus: {len(corpus)} docs -> {len(chunks)} chunks "
          f"(mean {statistics.fmean(len(c.text) for c in chunks):.0f} chars)")
    r = DenseRetriever(chunks)
    m = evaluate(r, questions)
    print(table({"baseline sliding-800 dense": m}))
    print()
    print(kind_table(m))
    print("\nWrite these numbers down before you change anything.")


def sweep_chunking() -> None:
    """TODO A1-A3.

    A1: all four strategies at size=800.
    A2: the winner at sizes 400 / 800 / 1600. Plot or tabulate the curve.
    A3: markdown WITH and WITHOUT the '[heading > path]' prefix.
        (Strip it with a list comprehension over the chunks -- do not modify
         aip/chunking.py; other labs depend on it.)

    Report chunk count and index build time alongside quality. A configuration
    that is 1 point better and takes 4x as long to build is a real trade-off.
    """
    corpus, questions = load_corpus(), load_questions()
    size = 800
    strat_sweep: dict[str, dict] = {}

    print()
    print("=" * 100)
    print(f"testing various strategies like - {list(STRATEGIES.keys())}")
    print()
    for strat_key in STRATEGIES.keys():
        t0 = time.perf_counter()
        chunks = build_chunks(corpus, strat_key, size, overlap=150)
        build_ms = (time.perf_counter() - t0) * 1000
        print(f"corpus: {len(corpus)} docs -> {len(chunks)} chunks "
              f"(mean {statistics.fmean(len(c.text) for c in chunks):.0f} chars) "
              f"build_ms={build_ms:.1f}")
        r = DenseRetriever(chunks)
        m = evaluate(r, questions)
        m["overall_metric"] = calc_final_metric(m)
        m["n_chunks"] = len(chunks)
        m["build_ms"] = build_ms
        strat_sweep[f"{strat_key} {size} dense"] = m

    print()
    print(table(strat_sweep, cols=("hit_rate@1", "hit_rate@5", "recall@5", "mrr",
                                   "ndcg@10", "latency_p95_ms", "overall_metric")))
    print()
    # pick winner primarily on ndcg@10 (lab headline), fall back to overall_metric
    best_strat = max(strat_sweep, key=lambda k: (strat_sweep[k]["ndcg@10"],
                                                 strat_sweep[k]["overall_metric"])).split(" ")[0]
    print("Best Strategy : ", best_strat)
    print()
    print("=" * 100)
    print("Now testing how changing chunk size helps")
    print()

    test_strat = best_strat
    sizes = [400, 800, 1600]
    size_sweep: dict[str, dict] = {}
    for sz in sizes:
        t0 = time.perf_counter()
        chunks = build_chunks(corpus, test_strat, sz, overlap=150)
        build_ms = (time.perf_counter() - t0) * 1000
        print(f"corpus: {len(corpus)} docs -> {len(chunks)} chunks "
              f"(mean {statistics.fmean(len(c.text) for c in chunks):.0f} chars) "
              f"build_ms={build_ms:.1f}")
        r = DenseRetriever(chunks)
        m = evaluate(r, questions)
        m["overall_metric"] = calc_final_metric(m)
        m["n_chunks"] = len(chunks)
        m["build_ms"] = build_ms
        size_sweep[f"{test_strat} {sz} dense"] = m

    print()
    print(table(size_sweep, cols=("hit_rate@1", "hit_rate@5", "recall@5", "mrr",
                                  "ndcg@10", "latency_p95_ms", "overall_metric")))
    print()
    best_size_key = max(size_sweep, key=lambda k: (size_sweep[k]["ndcg@10"],
                                                   size_sweep[k]["overall_metric"]))
    best_size = int(best_size_key.split(" ")[1])
    print("Best Size : ", best_size)
    print()
    print("=" * 100)
    print("Now testing Markdown with and without the [heading > path] prefix.")
    print()

    markdown_sweep: dict[str, dict] = {}
    strat = "markdown"
    size = best_size

    chunks = build_chunks(corpus, strat, size, overlap=150)
    print(f"corpus: {len(corpus)} docs -> {len(chunks)} chunks "
          f"(mean {statistics.fmean(len(c.text) for c in chunks):.0f} chars)")
    r = DenseRetriever(chunks)
    m = evaluate(r, questions)
    m["overall_metric"] = calc_final_metric(m)
    markdown_sweep[f"{strat} {size} dense with"] = m

    chunks_without_prefix = [
        replace(
            c,
            text=c.text.split("]", 1)[1].lstrip()
            if c.text.startswith("[") and "]" in c.text
            else c.text,
        )
        for c in chunks
    ]
    r = DenseRetriever(chunks_without_prefix)
    m = evaluate(r, questions)
    m["overall_metric"] = calc_final_metric(m)
    markdown_sweep[f"{strat} {size} dense without"] = m

    print()
    print(table(markdown_sweep, cols=("hit_rate@1", "hit_rate@5", "recall@5", "mrr",
                                      "ndcg@10", "latency_p95_ms", "overall_metric")))
    print()
    best_prefix = max(markdown_sweep, key=lambda k: markdown_sweep[k]["ndcg@10"]).split(" ")[-1]
    print("Better prefix : ", best_prefix)
    print()

    # A4 hint: dump one example failure if markdown beats fixed by a lot
    print("A4 note: pick a golden question where fixed/sliding miss and markdown hits;")
    print("print the matching chunk text vs the top retrieved chunks in the report.")


def sweep_retrieval() -> None:
    """TODO B1-B4.

    B1: dense / bm25 / hybrid on your best chunking.
    B2: print kind_table(m, col='mrr') for each, and pull out Q44 and Q41
        individually from metrics['_per_question_mrr'].

        USE MRR, NOT hit_rate@5. Every retriever here scores 0.93-0.98 on
        hit_rate@5, so it is saturated and shows you nothing -- which is why
        kind_table() and metrics['_per_question'] both default to it. That
        default is the trap, and noticing it is part of the lab.

    B3: RRF k in {10, 30, 60, 100} -- HybridRetriever(..., rrf_k=k).
    B4: unequal fusion weights -- HybridRetriever(..., weights=[2.0, 1.0]).
    """
    corpus, questions = load_corpus(), load_questions()
    # best from Part A on this corpus: markdown + small size (heading path helps)
    size = 400
    strat = "markdown"

    print()
    print("=" * 100)
    print("testing dense / bm25 / hybrid")
    print()

    chunks = build_chunks(corpus, strat, size, overlap=150)
    print(f"corpus: {len(corpus)} docs -> {len(chunks)} chunks "
          f"(mean {statistics.fmean(len(c.text) for c in chunks):.0f} chars)")

    dense = DenseRetriever(chunks)
    bm25 = Bm25Retriever(chunks)
    hybrid = HybridRetriever([dense, bm25], rrf_k=60)

    retrievers = {
        "dense": dense,
        "bm25": bm25,
        "hybrid": hybrid,
    }

    retrieval_sweep: dict[str, dict] = {}
    for name, r in retrievers.items():
        m = evaluate(r, questions)
        m["overall_metric"] = calc_final_metric(m)
        retrieval_sweep[f"{strat} {size} {name}"] = m
        print()
        print(f"--- {name} kind_table (MRR) ---")
        print(kind_table(m, col="mrr"))
        pq = m["_per_question_mrr"]
        print(f"Q44 MRR = {pq.get('Q44', float('nan')):.4f}")
        print(f"Q41 MRR = {pq.get('Q41', float('nan')):.4f}")

    print()
    print(table(retrieval_sweep, cols=("hit_rate@1", "hit_rate@5", "recall@5", "mrr",
                                       "ndcg@10", "latency_p95_ms", "overall_metric")))
    print()
    best_ret = max(retrieval_sweep, key=lambda k: retrieval_sweep[k]["ndcg@10"]).split(" ")[-1]
    print("Best Strategy : ", best_ret)
    print()
    print("=" * 100)
    print("B3: RRF k sweep on hybrid")
    print()

    rrf_sweep: dict[str, dict] = {}
    for k in [10, 30, 60, 100]:
        # rebuild so ranks are fresh; same underlying dense/bm25
        h = HybridRetriever([DenseRetriever(chunks), Bm25Retriever(chunks)], rrf_k=k)
        m = evaluate(h, questions)
        m["overall_metric"] = calc_final_metric(m)
        rrf_sweep[f"hybrid rrf_k={k}"] = m
    print(table(rrf_sweep, cols=("hit_rate@1", "recall@5", "mrr", "ndcg@10", "latency_p95_ms")))
    print()
    print("=" * 100)
    print("B4: unequal fusion weights")
    print()

    weight_sweep: dict[str, dict] = {}
    for wname, weights in [
        ("1:1", [1.0, 1.0]),
        ("2:1 dense-heavy", [2.0, 1.0]),
        ("1:2 bm25-heavy", [1.0, 2.0]),
    ]:
        h = HybridRetriever([DenseRetriever(chunks), Bm25Retriever(chunks)],
                            rrf_k=60, weights=weights)
        m = evaluate(h, questions)
        m["overall_metric"] = calc_final_metric(m)
        weight_sweep[f"hybrid {wname}"] = m
    print(table(weight_sweep, cols=("hit_rate@1", "recall@5", "mrr", "ndcg@10", "latency_p95_ms")))
    print()
    print("B5: if dense > hybrid on ndcg@10, say so in the report — that is the finding.")


def sweep_rerank() -> None:
    """TODO C1-C4.

    Retrieve k=30, rerank to 5: evaluate(r, questions, k=30, reranker=rr,
    final_k=5).

    C1: CrossEncoderReranker. First run downloads ~90 MB.
    C2: LLMReranker -- report cost as well as latency.
    C3: the decision table, and TWO different deployment answers
        (interactive search box vs overnight batch). They should differ.
    C4: find a query reranking made worse, using
        metrics['_per_question_mrr'] before and after.
    """
    corpus, questions = load_corpus(), load_questions()
    size = 400
    strat = "markdown"
    chunks = build_chunks(corpus, strat, size, overlap=150)
    print(f"corpus: {len(corpus)} docs -> {len(chunks)} chunks")

    base = DenseRetriever(chunks)
    m_base = evaluate(base, questions, k=30, final_k=5)
    # without reranker, evaluate still returns top-k of search; compare fairly
    m_base_top5 = evaluate(base, questions, k=5)

    print()
    print("=" * 100)
    print("C1: cross-encoder rerank (retrieve 30 -> 5)")
    print()
    ce = CrossEncoderReranker()
    m_ce = evaluate(base, questions, k=30, reranker=ce, final_k=5)
    print(table({
        "dense k=5 (no rerank)": m_base_top5,
        "dense k=30 + CE": m_ce,
    }, cols=("hit_rate@1", "recall@5", "mrr", "ndcg@5", "ndcg@10", "latency_p95_ms")))
    print()

    print("=" * 100)
    print("C2: LLM reranker (retrieve 30 -> 5) — costs money per query")
    print()
    try:
        llm_rr = LLMReranker(tier="SMALL")
        m_llm = evaluate(base, questions, k=30, reranker=llm_rr, final_k=5)
        print(table({
            "dense k=5 (no rerank)": m_base_top5,
            "dense k=30 + CE": m_ce,
            "dense k=30 + LLM": m_llm,
        }, cols=("hit_rate@1", "recall@5", "mrr", "ndcg@5", "ndcg@10", "latency_p95_ms")))
    except Exception as exc:
        m_llm = None
        print(f"LLM reranker failed / skipped: {exc}")
        print("(report CE numbers and note LLM cost/latency if you could not run it)")

    print()
    print("C4: queries where CE made MRR worse vs plain dense k=5")
    base_mrr = m_base_top5["_per_question_mrr"]
    ce_mrr = m_ce["_per_question_mrr"]
    worse = [(qid, base_mrr[qid], ce_mrr[qid])
             for qid in base_mrr
             if ce_mrr.get(qid, 0) + 1e-9 < base_mrr[qid]]
    worse.sort(key=lambda t: t[1] - t[2], reverse=True)
    for qid, b, a in worse[:8]:
        print(f"  {qid}: MRR {b:.3f} -> {a:.3f}  (delta {a - b:+.3f})")
    if not worse:
        print("  (none on this run)")
    print()
    print("C3 decision: interactive search box prefers low p95 (often no LLM / maybe CE);")
    print("overnight batch can afford LLM if quality delta is real. Put both in report.")


def sweep_index() -> None:
    """TODO D1-D3.

    D1/D2: ChromaRetriever vs DenseRetriever -- recall gap and latency.
    D3: pass status metadata into the chunks and filter at query time.

        Set chunk.meta['status'] = 'archived' if 'ARCHIVED' in doc_id else 'current'
        then ChromaRetriever.search(..., where={"status": "current"}).

        Report hit_rate@1 on Q29/Q30/Q31 before and after (hit_rate@1, not
        @5 -- @5 is saturated here and will hide the whole effect).
    """
    corpus, questions = load_corpus(), load_questions()
    size = 400
    strat = "markdown"
    chunks = build_chunks(corpus, strat, size, overlap=150)
    print(f"corpus: {len(corpus)} docs -> {len(chunks)} chunks")

    print()
    print("=" * 100)
    print("D1: DenseRetriever (exact) vs ChromaRetriever (HNSW)")
    print()
    dense = DenseRetriever(chunks)
    m_dense = evaluate(dense, questions)
    chroma = ChromaRetriever(chunks, path=str(ROOT / ".chroma_lab3"),
                             collection="lab3", reset=True)
    m_chroma = evaluate(chroma, questions)
    print(table({
        "exact dense": m_dense,
        "chroma HNSW": m_chroma,
    }, cols=("hit_rate@1", "recall@5", "mrr", "ndcg@10", "latency_p95_ms")))
    print()

    # D2 note — scale timings if expand script exists; otherwise single-scale
    print("=" * 100)
    print("D2: at ~160 chunks HNSW is often slower than exact (overhead).")
    print("If you ran scripts/expand_corpus.py, time both at larger N and report crossover.")
    print()

    print("=" * 100)
    print("D3: metadata filter status=current (fixes archived trap on Q29/Q30/Q31)")
    print()

    for c in chunks:
        c.meta["status"] = "archived" if "ARCHIVED" in c.doc_id else "current"

    chroma_meta = ChromaRetriever(chunks, path=str(ROOT / ".chroma_lab3_meta"),
                                  collection="lab3_meta", reset=True)

    trap_ids = {"Q29", "Q30", "Q31"}
    trap_qs = [q for q in questions if q["id"] in trap_ids]

    def hit1_on(retriever, qs, where=None):
        scores = []
        for q in qs:
            if where is not None and hasattr(retriever, "search"):
                try:
                    hits = retriever.search(q["question"], k=5, where=where)
                except TypeError:
                    hits = retriever.search(q["question"], k=5)
            else:
                hits = retriever.search(q["question"], k=5)
            seen, ranked = set(), []
            for h in hits:
                if h.doc_id not in seen:
                    seen.add(h.doc_id)
                    ranked.append(h.doc_id)
            m = retrieval_metrics(ranked, q["relevant_docs"], ks=(1, 5))
            scores.append((q["id"], m["hit_rate@1"], ranked[:3]))
        return scores

    before = hit1_on(chroma_meta, trap_qs, where=None)
    after = hit1_on(chroma_meta, trap_qs, where={"status": "current"})

    print(f"{'qid':<6}{'before@1':>12}{'after@1':>12}  top docs before -> after")
    for (qid, b, rb), (_, a, ra) in zip(before, after):
        print(f"{qid:<6}{b:12.1f}{a:12.1f}  {rb} -> {ra}")
    print()
    print("Takeaway: the fix needed no change to the ranking model — only metadata + filter.")


SWEEPS = {
    "chunking": sweep_chunking,
    "retrieval": sweep_retrieval,
    "rerank": sweep_rerank,
    "index": sweep_index,
}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--baseline", action="store_true")
    ap.add_argument("--sweep", choices=list(SWEEPS))
    args = ap.parse_args()
    if args.baseline or not args.sweep:
        sweep_baseline()
    if args.sweep:
        SWEEPS[args.sweep]()


if __name__ == "__main__":
    main()
