# Lab 4 Report — RAG v1: Grounded Answers with Citations

Retriever from Lab 3: **markdown-400 dense** (heading prefix kept), `k=12`, `final_k=5`, no reranker.

**n = 45** (40 answerable, 5 unanswerable).

```bash
python labs/lab4/evaluate.py --full --save reports/lab4.json
python labs/lab4/evaluate.py --gold-context
python labs/lab4/calibrate_interactive.py
python labs/lab4/evaluate.py --kappa
```

---

## Headline results

| Metric | Target | Measured | Pass? |
|---|---|---|---|
| Citation validity | **1.00** | **1.000** | yes |
| Faithfulness | ≥ 0.90 | **0.956** | yes |
| Answer correctness (norm) | ≥ 0.75 | **0.762** | yes |
| Refusal recall | ≥ 4/5 | **5/5 (1.00)** | yes |
| Refusal precision | ≥ 0.70 | **0.556 (5/9)** | no |
| Cost / query | ≤ $0.01 | ~$0.011 ($0.512 / 45) | slightly over |
| p95 e2e | ≤ 6,000 ms | 6,259 ms | slightly over |

Correctness raw mean on answerable: **1.525 / 2**.  
Judge parse errors excluded: **0**.

### By kind (correctness / 2)

| kind | score | n |
|---|---|---|
| single_hop | 0.889 | 18 |
| trap_archived | 0.833 | 3 |
| aggregation | 0.750 | 4 |
| multi_hop | 0.600 | 10 |
| paraphrase | 0.600 | 5 |

Weakest: multi-hop and paraphrase (same kinds that were hard in Lab 3 retrieval).

---

## Part A — Generation prompt

`ANSWER_SYSTEM` requires:

1. Answer only from numbered sources (no general knowledge)
2. Cite factual sentences as `[n]` / `[n][m]`
3. Never invent a citation index
4. Exact `REFUSAL` string when sources are insufficient
5. Partial answers when only part of the question is supported
6. Surface source disagreements; do not pick silently
7. Short answers (about 2–3 sentences)
8. `UNTRUSTED_SYSTEM_CLAUSE` (for Lab 6)

---

## Part B — Citation enforcement

`validate_answer` checks:

- every `[n]` in `1..n_sources`
- not truncated (`finish_reason == "length"`)
- non-empty
- at least one citation unless the answer is a refusal

**B3 policy:** one corrective retry with the failure reason; if still invalid → exact `REFUSAL`.  
Never return `citations_valid=False` and `refused=False` together.

**Measured citation validity: 1.000** (code path held on all 45).

---

## Part C — Refusal

### Raw counts (n_unanswerable = 5 — noisy)

| | count |
|---|---|
| Should refuse | 5 |
| Refused and should | **5** |
| Total refused | **9** |
| False refusals (answerable) | **4** |

```
refusal recall    = 5/5 = 1.00
refusal precision = 5/9 = 0.556
```

One case moves recall by 0.20 and precision by ~0.11. These ratios are a **direction**, not a precise measurement.

### C2 · Q37 (partial support)

Prompt rule allows: answer the supported part with citations; refuse the unsupported limit. Over-refusal on some *answerable* items still shows up in the precision count.

### C4 · product dial (insurance helpdesk)

Current dial is **recall-heavy** (caught all 5 unanswerable; also refused 4 answerable).

For a claims/policy desk I would **nudge toward precision**: inventing a deadline is worse than refusing, but four false refusals train agents to ignore the tool. Soften slightly (refuse only when the main ask has no cited support) and re-measure both ratios. Do not optimise recall alone.

---

## Part D — Judges and calibration

### Rubrics

- **Faithfulness:** support from context only; partial/honest refusal counts as supported; world-true but context-false → 0.
- **Correctness:** 0/1/2; correct refusal when gold refuses → **2**; answering when gold refuses → **0**.
- Parse failures → `None` (missing data), not 0.

### D2 · hand labels + κ (n = 20)

| Metric | Raw agreement | Cohen’s κ |
|---|---|---|
| Faithfulness | **0.95** | **0.00** |
| Correctness | **0.95** | **0.875** |

**Correctness κ = 0.875** — well above 0.4; judge is usable for that axis.

**Faithfulness κ = 0.00** with **95% raw agreement** is the class-imbalance / ceiling effect: almost all items are label **1** for both human and judge, so chance agreement is also ~0.95 and κ collapses. That does **not** mean the rubric failed. For faithfulness, **raw agreement is the meaningful figure** on this set.

Judge headline scores (faithfulness 0.956, correctness 0.762) are reported under this calibration.

---

## Part E — Gold-context decomposition

| | value |
|---|---|
| **A** correctness @ gold context | **0.929** (generation ceiling) |
| **B** correctness @ retrieved context | **0.762** (full system) |
| Retrieval-attributable loss **A − B** | **0.167** |
| Generation-attributable loss **1 − A** | **0.071** |

**Retrieval loss > generation loss** → Lab 5 should prioritise retrieval / context assembly over further prompt-only tweaks. With the right documents, generation already scores 0.929.

---

## Cost and latency

| | |
|---|---|
| Full eval run | 142 calls · **$0.512** · p50 2.9 s · p95 **6.3 s** |
| Drivers | generate + 2× LARGE judge per question |

Slightly over $0.01/query and 6 s p95 **because the eval harness runs judges**. Production path (generate + citation check only) is cheaper and faster; online faithfulness/correctness judges stay off.

---

## Recommended config (into Lab 5)

| piece | choice |
|---|---|
| Chunk / retrieve | markdown-400 dense · k=12 → final_k=5 |
| Rerank | none |
| Generate | MAIN · temp 0 · max_tokens 600 · ANSWER_SYSTEM as in `rag.py` |
| Validate | enforce citations + truncation · 1 repair · then REFUSAL |
| Online judges | off (eval only) |

---

## Surprises

1. Citation validity 1.0 with a simple validator on the return path.  
2. Faithfulness high while multi-hop/paraphrase correctness lag — grounded but incomplete.  
3. Refusal recall perfect, precision soft — system is cautious.  
4. Most of the correctness gap is **retrieval (0.167)**, not generation (0.071).  
5. Faithfulness κ ≈ 0 despite 95% agreement — label imbalance, not a broken rubric.

---

## Files submitted

- `labs/lab4/rag.py`
- `labs/lab4/evaluate.py`
- `labs/lab4/report.md`
- `labs/lab4/calibration_labels.jsonl`
- `labs/lab4/calibrate_interactive.py`
- `reports/lab4.json`
