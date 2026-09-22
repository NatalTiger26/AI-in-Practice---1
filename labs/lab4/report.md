# Lab 4 Report — RAG v1: Grounded Answers with Citations

Retriever from Lab 3: **markdown-400 dense** (heading prefix kept), `k=12`, `final_k=5`, no reranker.

**n = 45** (40 answerable, 5 unanswerable). Metrics below from:

```bash
python labs/lab4/evaluate.py --full --save reports/lab4.json
python labs/lab4/evaluate.py --gold-context
```

---

## Headline results

| Metric | Target | Measured | Pass? |
|---|---|---|---|
| Citation validity | **1.00** | **1.000** | yes |
| Faithfulness | ≥ 0.90 | **0.956** | yes |
| Answer correctness (norm) | ≥ 0.75 | **0.762** | yes |
| Refusal recall | ≥ 4/5 | **5/5 (1.00)** | yes |
| Refusal precision | ≥ 0.70 | **0.556 (5/9)** | **no** |
| Cost / query | ≤ $0.01 | ~$0.011 ($0.512 / 45) | slightly over |
| p95 e2e | ≤ 6,000 ms | 6,259 ms | slightly over |

Correctness raw mean on answerable: **1.525 / 2**.  
Parse errors excluded: **0**.

### By kind (correctness / 2)

| kind | score | n |
|---|---|---|
| single_hop | 0.889 | 18 |
| trap_archived | 0.833 | 3 |
| aggregation | 0.750 | 4 |
| multi_hop | 0.600 | 10 |
| paraphrase | 0.600 | 5 |

Weakest: multi-hop and paraphrase — matches Lab 3, where those kinds were also harder for ranking.

---

## Part A — Prompt

`ANSWER_SYSTEM` enforces: sources only, `[n]` cites, no invented indices, exact `REFUSAL` string, partial answers when only part is supported, surface disagreements, short answers, plus `UNTRUSTED_SYSTEM_CLAUSE`.

---

## Part B — Citations

`validate_answer` rejects out-of-range `[n]`, truncation (`finish_reason=length`), empty text, and non-refusal answers with zero cites.

**B3 policy:** one corrective retry → if still invalid, exact refusal.  
Never returns `citations_valid=False` with `refused=False`.

**Result:** citation validity **1.000** — code guarantee held.

---

## Part C — Refusal

### Counts (required; n=5 is noisy)

| | count |
|---|---|
| Should refuse (unanswerable) | 5 |
| Refused ∩ should | **5** |
| Total refused | **9** |
| False refusals (answerable) | **4** |

```
recall    = 5/5 = 1.00
precision = 5/9 = 0.556
```

One extra case moves precision by ~0.11 and recall by 0.20 — treat these as a **direction**, not a precise measurement (T3 §2.1).

### C2 · Q37

Prompt allows partial answers (supported part + refuse unsupported limit). Full run still shows over-refusal on some answerable items; product dial below addresses that.

### C4 · product decision (insurance helpdesk)

Current dial is **recall-heavy** (never miss a true unanswerable, but refuse 4 answerable).  

For a claims/policy helpdesk I would **tighten precision** slightly: false answers on deadlines/limits are more expensive than an occasional “I don’t have enough information…”, but **four** false refusals on answerable questions will annoy agents. Next step: soften the refusal rule one notch (e.g. only refuse when *no* cited support exists for the main ask) and re-measure both ratios. Do not chase 1.00 recall at the cost of precision without a cost argument.

---

## Part D — Judges

Rubrics improved for partial refusal and “refuse when reference refuses → score 2”.  
`parse_error` → `None` (not 0). This run: **0 parse errors**.

### Calibration (D2)

```bash
python labs/lab4/evaluate.py --calibrate
# fill human_faithfulness (0/1) and human_correctness (0/1/2)
# in labs/lab4/calibration_labels.jsonl  for 20 rows
python labs/lab4/evaluate.py --kappa
```

κ not yet computed (labels empty). Required before treating judge scores as final; if κ < 0.4, fix the rubric text, not the model.

---

## Part E — Gold-context decomposition

| | value |
|---|---|
| **A** correctness @ gold context | **0.929** (generation ceiling) |
| **B** correctness @ retrieved context | **0.762** (full system) |
| Retrieval-attributable loss **A − B** | **0.167** |
| Generation-attributable loss **1 − A** | **0.071** |

**Retrieval loss > generation loss** → Lab 5 should prioritise retrieval / context assembly more than prompt-only tweaks. Generation is already strong when given the right docs (0.929).

---

## Cost & latency

| | |
|---|---|
| Full run | 142 calls, $0.512, p50 2.9 s, p95 **6.3 s** |
| Drivers | generate + 2× LARGE judge per question |

Slightly over the $0.01/query and 6 s p95 targets because judges dominate. Production path (no faithfulness/correctness judges online) would be generate-only and much cheaper/faster; the eval harness is intentionally expensive.

---

## Recommended config (carry to Lab 5)

| piece | choice |
|---|---|
| Chunk / retrieve | markdown-400 dense, k=12 → final_k=5 |
| Rerank | none |
| Generate | MAIN, temp 0, max_tokens 600, ANSWER_SYSTEM as written |
| Validate | enforce cites + truncation; 1 repair then REFUSAL |
| Online judges | off (eval only) |

---

## Surprises

1. Citation validity hit 1.0 cleanly — validator on the return path works.  
2. Faithfulness high (0.956) while multi-hop/paraphrase correctness lag — grounding ok, content coverage weaker.  
3. Refusal recall perfect, precision soft — system is cautious.  
4. **Most of the correctness gap is retrieval (0.167), not generation (0.071).**

---

## Files

- `labs/lab4/rag.py`  
- `labs/lab4/evaluate.py`  
- `labs/lab4/report.md`  
- `reports/lab4.json`  
- `labs/lab4/calibration_labels.jsonl` (hand-label for κ)  
