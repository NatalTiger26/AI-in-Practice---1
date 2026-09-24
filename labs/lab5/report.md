# Lab 5 Report — Diagnose, Fix, Prove

Input: `reports/lab4.json` (45 questions, **16 failures** with correctness < 2).

```bash
python labs/lab5/diagnose.py --input reports/lab4.json --pareto
python labs/lab5/fix_pipeline.py --before-after --save reports/lab5_before_after.json
```

---

## Part A — Failure classification

### Improved `answer_in_corpus`

Shipped test was token-overlap only (false “missing content” on reworded numbers).  
**Change:** also require key **numbers** from gold in relevant docs, plus a light alphanumeric n-gram match. Present if numbers match (when any) and (token OR n-gram) hits.

### Tally (completed diagnostic tree)

| Mode | Name | n | share |
|---|---|---|---|
| **6** | **generation** | **15** | **93.8%** |
| 2 | chunk_boundary | 1 | 6.2% |
| 1, 3, 4, 5, 7 | — | 0 | 0% |

```
failure mode          n    share   cumulative
generation            15   93.8%   93.8%  ████████████████████████████
chunk_boundary         1    6.2%  100.0%  ██
```

### Why mode 6 (not inverted)

For 15/16 failures, a **relevant doc id appears in `retrieved`**. Gold was available to the generator; the answer was still incomplete/wrong → **generation**.

> Gold context *fixing* the answer ⇒ retrieval fault. Gold already in context and still wrong ⇒ generation.

### A2 · human check

| id | note |
|---|---|
| Q37 | needs_human_check — unanswerable/partial (Singapore limit). Missing numeric addendum (Lab 4 C2); more refusal/generation edge than a pure boundary split. |

### A3

Dominant cluster = **generation (15)**. Secondary = chunk_boundary (1).

---

## Part B — Rank by expected value

| Cluster | n | Fix | Est. recovery | Cost Δ | Effort |
|---|---|---|---|---|---|
| **6 generation** | 15 | `final_k=3` + multi-part instruction | 4–6 | ~0 | low |
| 2 boundary | 1 | larger chunks / overlap | 0–1 | 0 | medium |

**Pick: mode 6** — largest cluster; no extra model calls; matches the tally.

### Prediction (before implementing)

> Recover **4–6 of 15** generation failures; cost ≤ 2× (expect ≈1×); minimal regression on former passes.

---

## Part C — Fix (one variable)

**v2** in `labs/lab5/fix_pipeline.py`:

1. `final_k` 5 → **3** (fewer distractors)  
2. Multi-part instruction: answer every supported part; refuse only the unsupported part  

No change to chunking, embeddings, hybrid, or reranker.

---

## Part D — Prove it (from `reports/lab5_before_after.json`)

Scored **24** questions: **16** former failures + **8** former passes.

### D1 · before / after

| Metric | v1 | v2 | Δ |
|---|---|---|---|
| Correctness on failures (norm, /2) | **0.375** | **0.562** | **+0.187** |
| Correctness on failures (raw 0–2 mean) | 0.75 | 1.125 | +0.375 |
| Faithfulness on failures | 0.938 | **1.000** | +0.062 |
| Recovered (corr &lt; 2 → 2) | — | **4 / 16** | |
| Regressions on former passes | — | **0** | |
| Citation validity (v2 subset) | — | **1.000** | |
| Cost (24 Q run) | — | $0.237 · p95 4.8 s | no extra calls/query |

**Recovered IDs:** Q10, Q22, Q29, Q41  

**Still failing (12):** Q04, Q05, Q11, Q19, Q20, Q21, Q23, Q26, Q32, Q35, Q37, Q44  
(mostly multi_hop / aggregation / paraphrase still partial)

**Prediction vs actual:** predicted 4–6 recoveries → measured **4**. Met at the low end.

### D2 · regression check

| Check | Result |
|---|---|
| Former passes (n=8) mean correctness | v1 = 2.0, v2 = 2.0 — **no drop** |
| Regressions | **0** |
| Extra retrieval/LLM calls | **none** (same generate path, smaller context) |
| Refusal on failure subset | 3 refused under v2 (includes hard/unanswerable edges) |

Nothing on the pass sample got worse.

### D3 · after fix

4 failures moved to full correctness. Remaining 12 still pattern as **generation** (incomplete multi-hop / missing clause), not a shift into ranking/embedding modes. Retrieval was not the lever for this cluster.

### D4 · next fix

**Multi-hop decomposition** on `kind==multi_hop` only (separate retrieve+generate per sub-question, merge). Measure on that subset; expect higher cost on those queries only.

---

## Honesty

1. Incomplete classifier first labelled 100% `chunk_boundary` — unfinished tree, not the true backlog.  
2. Recovery **4/16** is real but modest; no claim of a large full-set jump.  
3. Retrieval-first fixes (hybrid/HyDE) would have targeted the wrong stage given gold-in-context.

---

## Files

| file | role |
|---|---|
| `labs/lab5/diagnose.py` | mode-1 improvement + classify tree |
| `labs/lab5/fix_pipeline.py` | mode-6 fix + before/after harness |
| `labs/lab5/report.md` | this file |
| `reports/lab5_diagnosis.json` | mode tally |
| `reports/lab5_before_after.json` | measured recoveries (Q10, Q22, Q29, Q41) |
