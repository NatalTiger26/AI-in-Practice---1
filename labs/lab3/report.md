# Lab 3 Report — Semantic Search That Actually Works

**n = 42** (dropped Q36 / Q38 / Q39 — empty `relevant_docs`, so recall/nDCG undefined).  
Stated dataset size is 45; unexplained n=42 would look like a bug, so this is called out on purpose.

---

## Baseline (sliding-800 dense)

| hit@1 | hit@5 | recall@5 | MRR | nDCG@10 | p95 ms |
|---|---|---|---|---|---|
| 0.786 | 0.929 | 0.845 | 0.845 | 0.805 | ~2 (cached) |

---

## Part A — Chunking

### A1 · four strategies @ 800 (dense)

| strategy | chunks | hit@1 | recall@5 | MRR | nDCG@10 |
|---|---|---|---|---|---|
| fixed | 83 | 0.738 | 0.837 | 0.839 | 0.795 |
| sliding | 91 | 0.786 | 0.845 | 0.845 | 0.805 |
| recursive | 98 | 0.786 | 0.839 | 0.855 | 0.813 |
| **markdown** | **164** | 0.762 | **0.899** | **0.872** | **0.846** |

**Winner: markdown.** Biggest lift is recall / MRR / nDCG, not hit@1 alone.  
Chunk count 164 vs ~90 means the strategy actually ran (if all four had been within ~1 point with similar counts, that would be a stale-index bug).

### A2 · size sweep on markdown

| size | chunks | hit@1 | recall@5 | MRR | nDCG@10 |
|---|---|---|---|---|---|
| **400** | 235 | **0.786** | **0.903** | **0.880** | **0.853** |
| 800 | 164 | 0.762 | 0.899 | 0.872 | 0.846 |
| 1600 | 150 | 0.714 | 0.875 | 0.826 | 0.808 |

**Shape:** best at 400, soft drop at 1600 — **not monotonic**.  
**Dilution (T4 §2.2):** a larger window packs more unrelated sentences into one embedding; the vector is an average, so a narrow question matches less cleanly. 400 keeps sections tighter; 1600 mixes topics.

### A3 · heading path prefix

| | hit@1 | hit@5 | recall@5 | MRR | nDCG@10 |
|---|---|---|---|---|---|
| **with** `[heading > path]` | **0.786** | 0.976 | 0.903 | **0.880** | **0.853** |
| without | 0.690 | **1.000** | 0.911 | 0.813 | 0.820 |

Prefix **raises ranking metrics** (hit@1, MRR, nDCG) while hit@5 can look flat or even higher without it.  
So: better top rank ≠ more docs somewhere in top-5. Ranking and recall are different jobs; the path is free structure signal.

### A4 · chunking failure mode

Markdown wins when the answer sits under a clear heading and fixed/sliding cut the section mid-thought or bury it in a mixed window. Classic T4 §5 mode 2: right document family, wrong cut.

---

## Part B — Dense vs BM25 vs hybrid  
*(markdown-400)*

### B1 · overall

| retriever | hit@1 | recall@5 | MRR | nDCG@10 |
|---|---|---|---|---|
| **dense** | **0.786** | **0.903** | **0.880** | **0.853** |
| bm25 | 0.476 | 0.796 | 0.670 | 0.698 |
| hybrid RRF | 0.667 | 0.863 | 0.798 | 0.795 |

**Dense wins.** Hybrid is worse than dense alone on nDCG@10 (0.795 vs 0.853).

### B2 · by kind (MRR — not hit@5)

hit@5 is saturated (~0.93–0.98); MRR shows the real split:

| kind | dense MRR | bm25 MRR | hybrid MRR | n |
|---|---|---|---|---|
| aggregation | 0.875 | 0.375 | 0.583 | 4 |
| multi_hop | 1.000 | 0.650 | 0.817 | 10 |
| paraphrase | 0.800 | 0.487 | 0.650 | 5 |
| single_hop | 0.907 | 0.852 | 0.944 | 18 |
| trap_archived | 0.833 | 0.511 | 0.667 | 3 |
| unanswerable | 0.312 | 0.417 | 0.375 | 2 |

**Q44** (exact id `AUR-HI-SIL-2026`): dense **0.50** / BM25 **1.00** / hybrid **1.00**  
→ BM25 matches the rare token; dense only half-ranks it.

**Q41** (paraphrase of grace period, no lexical overlap): dense **1.00** / BM25 **0.00** / hybrid **0.25**  
→ embedding links meaning; bag-of-words finds nothing; fusion **hurts** a question dense already had perfect.

### B3 · RRF k

| k | nDCG@10 | MRR |
|---|---|---|
| 10 | 0.816 | 0.812 |
| 30 | 0.795 | 0.798 |
| 60 | 0.795 | 0.798 |
| 100 | 0.790 | 0.798 |

**Mostly flat.** Small moves at n=42 are noise. Insensitivity is why RRF is a decent default — not because one k is special.

### B4 · weights

| weights | nDCG@10 | hit@1 |
|---|---|---|
| 1:1 | 0.795 | 0.667 |
| 2:1 dense-heavy | 0.807 | 0.690 |
| 1:2 bm25-heavy | 0.793 | 0.714 |

Dense-heavy helps a bit but **still below pure dense (0.853)**. Nothing here beats shipping dense alone.

### B5 · finding

**Hybrid loses on this corpus.** Dense already beats BM25 on most disagreeing questions; fusing a weaker list drags good ranks down more than it saves identifier queries. "Hybrid is the strongest default" is a prior from other corpora — measured false here.

---

## Part C — Reranking (retrieve 30 → 5)

| config | hit@1 | recall@5 | MRR | nDCG@5 | p95 ms |
|---|---|---|---|---|---|
| dense k=5 (no rerank) | 0.786 | 0.891 | 0.877 | 0.831 | **0.3** |
| dense k=30 + **CE** | 0.762 | 0.889 | 0.862 | 0.817 | **148** |
| dense k=30 + **LLM** | **0.857** | 0.881 | **0.905** | **0.851** | **~37000** |

**Cross-encoder:** quality **down** vs plain dense, latency up ~500×.  
**LLM:** quality **up** (hit@1 0.79 → 0.86, MRR 0.88 → 0.90), but ~37 s p95 — sequential calls per candidate.

### C4 · CE made these worse (MRR)

| qid | before | after | Δ |
|---|---|---|---|
| Q32 | 1.00 | 0.20 | −0.80 |
| Q26 | 1.00 | 0.33 | −0.67 |
| Q41 | 1.00 | 0.33 | −0.67 |
| Q01 / Q20 / Q45 | 1.00 | 0.50 | −0.50 |

CE is trained on web search; policy chunks that "look wrong" for that distribution get demoted even when dense had them rank-1 (T4 §5 mode 5).

### C3 · two deployment answers

| setting | ship | why |
|---|---|---|
| **Interactive agent search box** | **dense only (no rerank)** | p95 must stay sub-second; CE hurts quality *and* latency; LLM is unusable live |
| **Overnight batch / offline QA** | **dense + LLM rerank** (if budget allows) | hit@1/MRR gain is real; multi-second / multi-call cost is acceptable offline |

Same metrics, different latency and cost constraints → different choice.

---

## Part D — Index + metadata

### D1 · exact vs Chroma HNSW (markdown-400)

| | hit@1 | recall@5 | MRR | nDCG@10 | p95 ms |
|---|---|---|---|---|---|
| exact dense | 0.786 | 0.903 | 0.880 | 0.853 | **0.27** |
| chroma HNSW | 0.786 | 0.903 | 0.880 | 0.853 | **1.42** |

**Zero quality gap** at this scale; HNSW is **slower** (~5×) because graph overhead > one small matmul.

### D2 · scale note

Crossover only shows up at much larger N (thousands of chunks). Lab corpus (~235 chunks) is not the regime where ANN pays off.

### D3 · archived trap (Q29 / Q30 / Q31)

| qid | hit@1 before | hit@1 after `status=current` | what changed |
|---|---|---|---|
| Q29 | 1.0 | 1.0 | already current |
| **Q30** | **0.0** | **1.0** | was ranking `*-ARCHIVED` first |
| Q31 | 1.0 | 1.0 | archived still in list before filter |

**Q30 is the smoking gun:** filter alone fixed hit@1 with **no retriever change**.  
Lesson: bad retrieval is often **corpus / metadata / filter**, not the model.

---

## Final recommended config

| axis | choice |
|---|---|
| Chunking | **markdown**, size **400**, **keep heading prefix** |
| Retriever | **dense only** (not hybrid) |
| Rerank | **none** interactive; optional **LLM** for batch |
| Index | **exact dense** at this N; Chroma when scale demands |
| Metadata | always filter `status=current` |

**Measured quality (dev, n=42):**  
nDCG@10 **0.853** · recall@5 **0.903** · hit@1 **0.786** · MRR **0.880**  
All above lab targets (0.80 / 0.85 / 0.65).

---

## Surprises

1. Hybrid **lost** to dense — theory average ≠ this corpus.  
2. Cross-encoder **hurt** ranking and added ~148 ms.  
3. HNSW **slower** than exact at ~235 chunks.  
4. One metadata flag fixed Q30 completely.

---

## Greedy sweep limit

Axes swept one at a time (chunk → size → retriever → rerank → index). That can miss interactions (e.g. BM25 + different size, CE only on multi-hop). Full grid is too large for the session; limitation acknowledged.

---

## Files

- `labs/lab3/search.py` — completed sweeps  
- `labs/lab3/report.md` — this file  
- `reports/lab3_sweeps.json` — numeric dump of this run  
