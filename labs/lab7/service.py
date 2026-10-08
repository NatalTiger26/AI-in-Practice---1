#!/usr/bin/env python3
"""Lab 7 — the service.

    uvicorn labs.lab7.service:app --reload --port 8000
    curl -s localhost:8000/ask -H 'content-type: application/json' \
         -d '{"question":"How long do I have to file a claim?"}' | jq
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
import time
from pathlib import Path
from typing import Any, Iterator

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from aip import cache, tracing  # noqa: E402
from aip.cost import BudgetExceeded, global_budget  # noqa: E402
from aip.guards import ToolGuard, enforce_citations  # noqa: E402

app = FastAPI(title="Aurora Policy Assistant", version="1.0")

_PIPELINE = None
_STARTED = time.time()
_REQUEST_STATS: dict[str, Any] = {
    "n": 0,
    "errors": {},
    "latencies_ms": [],
    "cache_hits": 0,
    "tool_calls": 0,
}


def pipeline():
    """TODO A2: build your Labs 3-5 pipeline once, at startup, and cache it.

    Building it per-request re-embeds the corpus every time. Students do this
    and then report a 40-second p95.
    """
    global _PIPELINE
    if _PIPELINE is None:
        from aip.chunking import markdown_chunks
        from aip.retrieval import DenseRetriever
        from labs.lab3.search import load_corpus
        from labs.lab4.rag import REFUSAL, answer_question
        from labs.lab6.agent import REGISTRY, SCHEMAS, run_agent

        corpus = load_corpus()
        # Lab 3 winner: markdown-400 dense
        chunks = [
            c for doc_id, text in corpus.items()
            for c in markdown_chunks(text, doc_id, size=400)
        ]
        retriever = DenseRetriever(chunks, show_progress=False)

        def answer_rag(question: str, top_k: int = 5) -> dict:
            # Lab 5-style: fewer distractors (final_k=3) helped generation
            a = answer_question(question, retriever, k=12, final_k=min(top_k, 3))
            citations = []
            for i, h in enumerate(a.hits, start=1):
                excerpt = (h.text if hasattr(h, "text") else getattr(h.chunk, "text", ""))[:400]
                doc_id = h.doc_id if hasattr(h, "doc_id") else getattr(h.chunk, "doc_id", "?")
                citations.append({
                    "index": i,
                    "doc_id": doc_id,
                    "excerpt": excerpt,
                })
            return {
                "answer": a.text,
                "refused": a.refused,
                "citations": citations,
                "citations_valid": a.citations_valid,
            }

        def answer_tools(question: str) -> dict:
            # Lab 6 guards on the request path
            guard = ToolGuard(
                max_calls=6,
                allow={"search_policy", "get_policy_details", "compute_premium"},
                requires_confirmation={"issue_refund"},
                confirm_fn=lambda n, a: False,
            )
            r = run_agent(
                question,
                guard=guard,
                layers={1, 2, 4, 5},
                max_seconds=45.0,
                budget_usd=0.02,
            )
            return {
                "answer": r.get("answer") or "",
                "refused": (r.get("answer") or "").startswith("I don't have enough"),
                "citations": [],
                "tool_log": r.get("tool_log") or [],
                "stopped_because": r.get("stopped_because"),
            }

        _PIPELINE = {
            "retriever": retriever,
            "n_chunks": len(chunks),
            "answer_rag": answer_rag,
            "answer_tools": answer_tools,
            "refusal_prefix": REFUSAL[:40],
        }
    return _PIPELINE


class AskRequest(BaseModel):
    question: str = Field(min_length=3, max_length=1000)
    top_k: int = Field(default=5, ge=1, le=20)
    mode: str = Field(default="rag", pattern="^(rag|tools)$")


class Citation(BaseModel):
    index: int
    doc_id: str
    excerpt: str


class AskResponse(BaseModel):
    answer: str
    refused: bool
    citations: list[Citation]
    latency_ms: float
    cost_usd: float
    cached: bool
    trace_id: str


def _norm_question(q: str) -> str:
    return re.sub(r"\s+", " ", q.strip().lower())


def _response_cache_key(question: str, mode: str, top_k: int) -> str:
    payload = {"q": _norm_question(question), "mode": mode, "top_k": top_k}
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def _record_error(kind: str) -> None:
    _REQUEST_STATS["errors"][kind] = _REQUEST_STATS["errors"].get(kind, 0) + 1


def _is_provider_outage(exc: Exception) -> bool:
    msg = f"{type(exc).__name__} {exc}".lower()
    return any(
        s in msg
        for s in (
            "rate limit", "ratelimit", "timeout", "503", "502", "overloaded",
            "service unavailable", "connection", "api error", "resource_exhausted",
        )
    )


@app.post("/ask", response_model=AskResponse)
def ask(req: AskRequest) -> AskResponse:
    """TODO A1. Return cost and trace_id in the response -- they are how
    anyone debugs this later."""
    t0 = time.perf_counter()
    pipe = pipeline()
    b0 = global_budget().spent_usd
    key = _response_cache_key(req.question, req.mode, req.top_k)

    try:
        with tracing.trace("http.ask", question=req.question[:120], mode=req.mode) as span:
            # Exact response cache (Part B1)
            ck = cache.make_key("lab7.ask", {"key": key})
            try:
                cached_body = cache.get(ck)
            except Exception:
                cached_body = None
            if isinstance(cached_body, dict) and cached_body.get("answer") is not None:
                _REQUEST_STATS["n"] += 1
                _REQUEST_STATS["cache_hits"] += 1
                latency = (time.perf_counter() - t0) * 1000
                _REQUEST_STATS["latencies_ms"].append(latency)
                span["cached"] = True
                return AskResponse(
                    answer=cached_body["answer"],
                    refused=bool(cached_body.get("refused")),
                    citations=[Citation(**c) for c in cached_body.get("citations") or []],
                    latency_ms=round(latency, 1),
                    cost_usd=0.0,
                    cached=True,
                    trace_id=span.get("run_id") or span.get("span_id") or "",
                )

            if req.mode == "tools":
                with tracing.trace("agent.tools"):
                    out = pipe["answer_tools"](req.question)
                _REQUEST_STATS["tool_calls"] += len(out.get("tool_log") or [])
            else:
                with tracing.trace("rag.answer", top_k=req.top_k):
                    out = pipe["answer_rag"](req.question, top_k=req.top_k)

            # Citation validity is already enforced in Lab 4 path; re-check indices
            n_src = len(out.get("citations") or [])
            if out.get("answer") and n_src and not out.get("refused"):
                ok, invalid = enforce_citations(out["answer"], n_src)
                span["citations_ok"] = ok
                if not ok:
                    span["invalid_citations"] = invalid

            cost = max(0.0, global_budget().spent_usd - b0)
            latency = (time.perf_counter() - t0) * 1000
            span["latency_ms"] = latency
            span["cost_usd"] = cost

            body = {
                "answer": out.get("answer") or "",
                "refused": bool(out.get("refused")),
                "citations": out.get("citations") or [],
            }
            try:
                cache.put(ck, "lab7.ask", {"key": key}, body)
            except Exception:
                pass

            _REQUEST_STATS["n"] += 1
            _REQUEST_STATS["latencies_ms"].append(latency)

            return AskResponse(
                answer=body["answer"],
                refused=body["refused"],
                citations=[Citation(**c) for c in body["citations"]],
                latency_ms=round(latency, 1),
                cost_usd=round(cost, 6),
                cached=False,
                trace_id=span.get("run_id") or span.get("span_id") or "",
            )

    except BudgetExceeded as exc:
        _record_error("budget")
        raise HTTPException(status_code=429, detail=str(exc)) from exc
    except NotImplementedError:
        raise
    except Exception as exc:                                    # noqa: BLE001
        # TODO A3: distinguish a provider outage (503 + Retry-After) from a
        # genuine bug (500). Returning 500 for a rate limit makes every client
        # retry immediately, which is exactly wrong.
        if _is_provider_outage(exc):
            _record_error("provider")
            raise HTTPException(
                status_code=503,
                detail="upstream model unavailable",
                headers={"Retry-After": "30"},
            ) from exc
        _record_error("internal")
        raise HTTPException(status_code=500, detail="internal error") from exc


@app.get("/health")
def health() -> dict:
    """TODO C: index size, model profile, cache stats, uptime."""
    pipe = None
    try:
        pipe = pipeline()
    except Exception as exc:  # noqa: BLE001
        return {"status": "degraded", "error": str(exc)[:200],
                "uptime_s": round(time.time() - _STARTED, 1)}
    return {
        "status": "ok",
        "uptime_s": round(time.time() - _STARTED, 1),
        "index_chunks": pipe["n_chunks"],
        "retriever": "markdown-400 dense (Lab 3)",
        "modes": ["rag", "tools"],
        "guards": "Lab 6 layers 1,2,4,5 on tools mode",
        "cache": cache.stats(),
    }


@app.get("/metrics")
def metrics() -> dict:
    """TODO C2: cost today, cost/query, cache hit rate, p50/p95/p99, error rate."""
    b = global_budget()
    lats = sorted(_REQUEST_STATS["latencies_ms"])

    def pct(p: float) -> float:
        if not lats:
            return 0.0
        idx = min(len(lats) - 1, max(0, int(round((p / 100) * (len(lats) - 1)))))
        return round(lats[idx], 1)

    n = max(1, _REQUEST_STATS["n"])
    return {
        **b.as_dict(),
        "requests": _REQUEST_STATS["n"],
        "cache_hits": _REQUEST_STATS["cache_hits"],
        "cache_hit_rate": round(_REQUEST_STATS["cache_hits"] / n, 3),
        "cost_per_query_usd": round(b.spent_usd / n, 6) if _REQUEST_STATS["n"] else 0.0,
        "p50_latency_ms": pct(50),
        "p95_latency_ms": pct(95),
        "p99_latency_ms": pct(99),
        "error_rate_by_type": dict(_REQUEST_STATS["errors"]),
        "tool_call_counts": _REQUEST_STATS["tool_calls"],
    }


# TODO B2: POST /ask/stream with server-sent events.
#          Then solve B3: you cannot validate citations before you have sent
#          the answer. Pick one of the three strategies and defend it.
@app.post("/ask/stream")
async def ask_stream(req: AskRequest):
    """SSE stream. Strategy (B3): buffer full answer, validate, then stream
    tokens from the buffer + a final `validation` event. Loses true TTFT from
    the model but keeps citation guarantees — safer for insurance answers.
    """
    pipe = pipeline()

    def event_gen() -> Iterator[dict]:
        t0 = time.perf_counter()
        try:
            with tracing.trace("http.ask.stream", question=req.question[:120]):
                if req.mode == "tools":
                    out = pipe["answer_tools"](req.question)
                else:
                    out = pipe["answer_rag"](req.question, top_k=req.top_k)
                answer = out.get("answer") or ""
                cites = out.get("citations") or []
                n_src = len(cites)
                valid = True
                invalid: list[int] = []
                if answer and n_src and not out.get("refused"):
                    valid, invalid = enforce_citations(answer, n_src)

                # Stream in small chunks (simulated SSE from buffered answer)
                chunk_size = 40
                for i in range(0, len(answer), chunk_size):
                    yield {
                        "event": "token",
                        "data": json.dumps({"text": answer[i : i + chunk_size]}),
                    }
                yield {
                    "event": "validation",
                    "data": json.dumps({
                        "citations_valid": valid,
                        "invalid_citations": invalid,
                        "refused": bool(out.get("refused")),
                        "citations": cites,
                        "latency_ms": round((time.perf_counter() - t0) * 1000, 1),
                    }),
                }
                yield {"event": "done", "data": "{}"}
        except BudgetExceeded as exc:
            yield {"event": "error", "data": json.dumps({"status": 429, "detail": str(exc)})}
        except Exception as exc:  # noqa: BLE001
            status = 503 if _is_provider_outage(exc) else 500
            yield {"event": "error", "data": json.dumps({"status": status, "detail": str(exc)[:200]})}

    return EventSourceResponse(event_gen())
