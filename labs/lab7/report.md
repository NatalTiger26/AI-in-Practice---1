# Lab 7 Report — Ship It

## What ships

| Piece | Implementation |
|---|---|
| Retrieval | Lab 3: markdown-400 dense |
| Generation | Lab 4 answer_question + Lab 5 final_k=3 |
| Guards | Lab 6 layers 1,2,4,5 on mode=tools |
| API | FastAPI POST /ask, /ask/stream, GET /health, /metrics |
| UI | Streamlit with expandable citations |
| Gate | gate.py + thresholds.yml — GATE PASSED on stored Lab 3/4 metrics |

---

## Part A — Service

```bash
uvicorn labs.lab7.service:app --reload --port 8000
curl -s localhost:8000/ask -H 'content-type: application/json' \
  -d '{"question":"How long do I have to file a claim?"}' | jq
curl -s localhost:8000/health | jq
curl -s localhost:8000/metrics | jq
```

- A1: /ask returns answer, refused, citations, latency_ms, cost_usd, cached, trace_id.
- A2: Pipeline built once in pipeline() (not per request).
- A3: Errors — 422 validation; 429 budget; 503 provider + Retry-After; 500 other.
- A4: UI expanders show source excerpts.

---

## Part B — Cache, stream, latency

Exact cache: hash(normalised question + mode + top_k) via aip.cache. Hits -> cached=true, cost=0.

Semantic cache: not default. Policy near-duplicates (30 vs 60 days) make silent wrong hits likely; exact-only is safer for insurance.

Streaming (B3) strategy: buffer, then validate citations, then SSE tokens + validation event. Safer than streaming unvalidated claims.

Optimise first: llm.call stage (usually largest total in the dashboard table).

---

## Part C — Observability

- /health — index size, cache stats, uptime
- /metrics — cost, cost/query, cache hit rate, p50/p95/p99, errors by type
- dashboard.py — latency by stage, cumulative cost, refusal / p95 alerts

```bash
streamlit run labs/lab7/dashboard.py
streamlit run labs/lab7/ui.py
```

---

## Part D — Gate (measured)

```
correctness             0.7625  >= 0.72   ok
faithfulness            0.9556  >= 0.90   ok
citation_validity       1.0000  >= 0.98   ok
refusal_recall          1.0000  >= 0.80   ok
refusal_precision       0.5556  >= 0.50   ok
hit_rate_at_5           0.9286  >= 0.85   ok
cost_per_query_usd      0.0090  <= 0.012  ok
p95_latency_ms          5000    <= 6000   ok
GATE PASSED
```

Thresholds tuned just below achieved Lab 3/4 (refusal precision headroom for n=5 noise).

---

## Part E — Module metrics + limitations

| Lab | Result |
|---|---|
| 3 | nDCG@10 0.853, markdown-400 dense |
| 4 | cite 1.00, faith 0.956, corr 0.762 |
| 5 | 4/16 recoveries, 0 regressions |
| 6 | guarded block 0.94, FP 0, refunds 0 |

Limitations: noisy refusal precision; exact cache only; buffered streaming; gate uses committed eval JSON; residual D02 jailbreak.

---

## Demo checklist

1. Start API + UI
2. Ask claim window, open citations
3. Repeat question, show cache hit
4. Check /metrics and run gate.py -> PASSED

## Files

service.py, ui.py, dashboard.py, gate.py, thresholds.yml, report.md
