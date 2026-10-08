# Lab 5 Report — Diagnose, Fix, Prove

**Starting point:** Lab 4 system, `reports/lab4.json`  
**Failures to explain:** 16 out of 45 questions (correctness score below 2)

Commands used:

```bash
python labs/lab5/diagnose.py --input reports/lab4.json --pareto
python labs/lab5/fix_pipeline.py --before-after --save reports/lab5_before_after.json
```

---

## 1. What went wrong? (Part A — classify)

Lab 5 says: every wrong answer fails at **exactly one stage**. Classify first; do not guess a fix.

### Better “is the answer in the corpus?” check

The starter `answer_in_corpus` only counted long words. That can miss answers that use different wording but the same numbers.

**What I changed:** also check that numbers in the gold answer appear in the relevant docs, and allow a short character n-gram match. So we do not wrongly call something “missing from the corpus” when the facts are actually there.

### Failure tally

| Failure mode | Meaning (short) | Count | Share |
|---|---|---|---|
| **6 — generation** | Right docs were retrieved, but the written answer is still wrong/incomplete | **15** | **94%** |
| 2 — chunk boundary | Answer may be split across chunks (needs a human look) | **1** | 6% |
| 1 missing content | Fact not in corpus at all | 0 | 0% |
| 3 embedding mismatch | Query and chunk don’t match in vector space | 0 | 0% |
| 4 ranking | Gold found early, then lost in top-k | 0 | 0% |
| 5 reranker | Reranker dropped a good hit | 0 | 0% |
| 7 presentation | Answer right, citations broken | 0 | 0% |

Pareto chart (from the script):

```
failure mode          n    share   cumulative
generation            15   93.8%   93.8%  ████████████████████████████
chunk_boundary         1    6.2%  100.0%  ██
```

**Almost all failures are generation.** That is not a bug in the classifier — it matches Lab 4: when we gave the model the gold documents, correctness jumped to 0.929. The model can write good answers; on these 16 it often had the right docs and still wrote a weak answer.

### How I knew it was generation (not retrieval)

For 15 of the 16 failures, the **correct document id was already in the retrieved list**.  
So the model saw the right source and still scored 0 or 1.

Important rule from the handout (easy to get backwards):

- If **gold context fixes** the answer → the problem was **retrieval**  
- If gold was **already in context** and the answer is still bad → the problem is **generation**

Here: gold was already in context → mode 6.

### The one case that needed a human check

| Question | Auto label | What I think |
|---|---|---|
| Q37 | chunk_boundary / needs_human_check | Singapore cover / limit — corpus does not fully support the limit (Lab 4). Closer to “cannot fully answer” than a pure chunk-split bug. |

---

## 2. What should we fix first? (Part B — rank)

| Cluster | Size | Possible fix | Expected recoveries | Extra cost? | Effort |
|---|---|---|---|---|---|
| **Generation** | 15 | Use fewer context chunks + clearer “answer every part” instruction | **4–6** | No extra API calls | Low |
| Chunk boundary | 1 | Bigger chunks / more overlap | 0–1 | No | Medium |

**Choice: fix generation.**

One sentence why: it is almost the whole backlog (15/16), the fix is cheap (no HyDE, no second model call), and the diagnosis says retrieval is not the main problem for these failures.

### Prediction (written *before* coding the fix)

I expect this change to:

1. Fully fix **about 4 to 6** of the 15 generation failures (score moves to 2).  
2. Keep cost about the **same** as Lab 4 generate (≤ 2× allowed; I expect ~1×).  
3. **Not** break questions that already worked (check a small pass sample).

I will compare this prediction to the measured numbers in section 4.

---

## 3. What I changed (Part C — one fix only)

File: `labs/lab5/fix_pipeline.py` (v2 pipeline).

**Only two generation-side changes:**

1. **Fewer distractors:** keep **3** chunks for the model instead of 5 (`final_k=3`).  
2. **Multi-part instruction:** if the question has several parts, answer every part the sources support; only refuse the part that is missing.

**What I did not change:** chunking, embeddings, hybrid search, reranker.  
Those would be right for retrieval modes. Our tally said generation.

---

## 4. Did it work? (Part D — measure)

Measured on **16 old failures + 8 old passes** (24 questions), saved in `reports/lab5_before_after.json`.

### Before vs after

| Metric | Before (v1) | After (v2) | Change |
|---|---|---|---|
| Correctness on the 16 failures (0–1 scale) | 0.375 | **0.562** | **+0.187** |
| Faithfulness on those failures | 0.94 | **1.00** | +0.06 |
| Failures fully fixed (score → 2) | — | **4 out of 16** | |
| Old passes that broke | — | **0** | |
| Citations still valid | — | **1.00** on this set | |
| Cost for this run | — | $0.24 for 24 questions, p95 ~4.8 s | no extra calls per question |

**Which failures got fixed:** Q10, Q22, Q29, Q41  

**Still wrong (12):** Q04, Q05, Q11, Q19, Q20, Q21, Q23, Q26, Q32, Q35, Q37, Q44  
Most of these are multi-hop or need several facts in one answer — still a generation gap.

### Prediction vs reality

| | Predicted | Measured |
|---|---|---|
| Recoveries | 4–6 | **4** |
| Regressions | minimal | **0** |
| Cost | ~1× | no extra model calls |

The prediction was **right at the low end**. Not a huge win, but real and matched what we said before implementing.

### Regression check (did anything get worse?)

- 8 questions that already scored 2: still score 2.  
- No new citation failures on this set.  
- Did not add HyDE/multi-query, so cost did not double.

### After the fix, what does the backlog look like?

Still mostly **generation** (hard multi-hop / incomplete answers). We did not uncover a hidden ranking problem — we only made some generation failures easier.

### What I would try next

For remaining **multi_hop** questions only: split the question into sub-questions, retrieve and answer each, then merge. That will cost more on those queries; measure only on the multi_hop subset.

---

## 5. Honest notes

1. **First diagnose run** (before the tree was finished) said 100% chunk_boundary. That was incomplete code, not the real story. After finishing the branches, the real story was **94% generation**.  
2. **4 recoveries out of 16** is progress, not a solved system.  
3. Jumping to hybrid search or HyDE would have ignored the diagnosis (gold docs were already retrieved).

---

## 6. Files to submit

| File | What it is |
|---|---|
| `labs/lab5/diagnose.py` | Classifier (better corpus check + full mode tree) |
| `labs/lab5/fix_pipeline.py` | The one generation fix + before/after runner |
| `labs/lab5/report.md` | This report |
| `reports/lab5_diagnosis.json` | Per-failure mode labels |
| `reports/lab5_before_after.json` | Measured v1 vs v2 scores |

---

## Bottom line

1. **Diagnose:** 15/16 failures = generation (right docs, weak answer).  
2. **Predict:** recover 4–6 with fewer chunks + multi-part prompt.  
3. **Fix:** only that generation change.  
4. **Measure:** recovered **4**, **0** regressions, prediction held.
