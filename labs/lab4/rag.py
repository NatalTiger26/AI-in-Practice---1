#!/usr/bin/env python3
"""Lab 4 — your RAG pipeline.

Write this yourself. `aip/rag.py` is the reference implementation; look at it
after Part A, not before. Labs 5-7 build on whichever of the two you prefer,
but you must be able to explain every line of the one you use.
"""
from __future__ import annotations

import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from aip.guards import UNTRUSTED_SYSTEM_CLAUSE, delimit_untrusted, enforce_citations  # noqa: E402
from aip.llm import chat  # noqa: E402
from aip.retrieval import Hit, Retriever, format_context  # noqa: E402

# The exact string the system must emit when it cannot answer. Exact, because
# downstream code detects refusal by matching it -- a paraphrase is a bug.
REFUSAL = "I don't have enough information in the provided sources to answer that."

# TODO A: write this before you read aip/rag.py::ANSWER_SYSTEM.
ANSWER_SYSTEM = f"""\
You answer Aurora Health policy questions using ONLY the numbered sources below.

Hard rules (follow in this order):
1. Use the sources only. Do not use general knowledge, training data, or guesses.
2. Cite every factual sentence with the source index that supports it, like [1]
   or [2][4]. Never invent a citation number that was not given to you.
3. If the sources do not contain enough information to answer, reply with EXACTLY
   this sentence and nothing else:
   {REFUSAL}
4. If the sources only support part of the question, answer the supported part
   with citations, and clearly say which part you cannot answer from the sources.
5. If two sources disagree, say that they disagree and cite both — do not pick
   one silently.
6. Keep answers short: usually two or three sentences unless the question needs more.

{UNTRUSTED_SYSTEM_CLAUSE}
"""


@dataclass
class Answer:
    question: str
    text: str
    hits: list[Hit] = field(default_factory=list)
    refused: bool = False
    citations_valid: bool = False
    invalid_citations: list[int] = field(default_factory=list)
    n_citations: int = 0
    truncated: bool = False


def validate_answer(text: str, n_sources: int, finish_reason: str | None = None) -> dict:
    """TODO B2. Return a dict with at least:

        {"valid": bool, "refused": bool, "invalid_citations": [ints],
         "n_citations": int, "truncated": bool, "reason": str}

    Checks:
      - every [n] is between 1 and n_sources
      - not truncated (finish_reason == "length" means the answer was cut off,
        and a cut-off prose answer LOOKS FINE -- this is T1 failure mode 4 and
        it is the dangerous one)
      - a non-refusal answer contains at least one citation
    """
    text = (text or "").strip()
    truncated = finish_reason == "length"
    refused = text.startswith(REFUSAL[:40]) or text == REFUSAL

    cited = sorted({int(m) for m in re.findall(r"\[(\d+)\]", text)})
    n_citations = len(cited)

    # enforce_citations returns (ok_and_has_cite, invalid_list)
    _ok_with_cite, invalid = enforce_citations(text, n_sources) if n_sources > 0 else (False, cited)
    # for refusals, missing citations are fine; still reject out-of-range cites
    out_of_range = [c for c in cited if c < 1 or c > n_sources]

    if truncated:
        return {
            "valid": False,
            "refused": refused,
            "invalid_citations": out_of_range,
            "n_citations": n_citations,
            "truncated": True,
            "reason": "truncated",
        }
    if not text:
        return {
            "valid": False,
            "refused": False,
            "invalid_citations": [],
            "n_citations": 0,
            "truncated": False,
            "reason": "empty",
        }
    if out_of_range:
        return {
            "valid": False,
            "refused": refused,
            "invalid_citations": out_of_range,
            "n_citations": n_citations,
            "truncated": False,
            "reason": "invalid_citation_index",
        }
    if not refused and n_citations == 0:
        return {
            "valid": False,
            "refused": False,
            "invalid_citations": [],
            "n_citations": 0,
            "truncated": False,
            "reason": "missing_citation",
        }
    return {
        "valid": True,
        "refused": refused,
        "invalid_citations": [],
        "n_citations": n_citations,
        "truncated": False,
        "reason": "ok",
    }


def _generate(question: str, hits: list[Hit], *, tier: str, system: str = ANSWER_SYSTEM) -> tuple[str, str | None]:
    context = delimit_untrusted(format_context(hits, max_chars=8000))
    prompt = f"{context}\n\nQuestion: {question}\n\nAnswer with citations:"
    result = chat(
        prompt,
        system=system,
        tier=tier,
        temperature=0.0,
        max_tokens=600,
        return_full=True,
    )
    if isinstance(result, dict):
        return (result.get("text") or "").strip(), result.get("finish_reason")
    return str(result).strip(), None


def answer_question(question: str, retriever: Retriever, *, k: int = 12,
                    final_k: int = 5, reranker=None, tier: str = "MAIN") -> Answer:
    """TODO: retrieve -> (rerank) -> generate -> validate -> maybe repair.

    B3: decide what happens when validation fails. Whatever you decide, the
    function must never return an Answer with citations_valid=False and
    refused=False. That combination is the thing you are being paid to prevent.
    """
    hits = retriever.search(question, k=k)
    if reranker is not None:
        hits = reranker.rerank(question, hits, k=final_k)
    else:
        hits = list(hits)[:final_k]

    text, finish_reason = _generate(question, hits, tier=tier)
    v = validate_answer(text, len(hits), finish_reason)

    # B3 policy: on invalid citations / missing cites / truncation, ONE corrective
    # retry. If still bad, fall back to exact refusal. Never return a confident
    # answer with citations_valid=False — that is worse than refusing.
    if not v["valid"] and not v["refused"]:
        repair_note = (
            f"Your previous answer failed validation ({v['reason']}). "
            f"Invalid citation indices: {v['invalid_citations']}. "
            f"Reply again using only sources [1]..[{len(hits)}], with citations, "
            f"or reply with the exact refusal sentence if you cannot answer."
        )
        context = delimit_untrusted(format_context(hits, max_chars=8000))
        prompt = (
            f"{context}\n\nQuestion: {question}\n\n"
            f"{repair_note}\n\nAnswer with citations:"
        )
        result = chat(
            prompt, system=ANSWER_SYSTEM, tier=tier,
            temperature=0.0, max_tokens=600, return_full=True,
        )
        if isinstance(result, dict):
            text = (result.get("text") or "").strip()
            finish_reason = result.get("finish_reason")
        else:
            text = str(result).strip()
            finish_reason = None
        v = validate_answer(text, len(hits), finish_reason)

        if not v["valid"] and not v["refused"]:
            text = REFUSAL
            v = validate_answer(text, len(hits), None)

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


def answer_with_gold_context(question: str, gold_docs: list[str], *,
                             tier: str = "MAIN") -> Answer:
    """TODO E2: same generator, but the context is the gold documents.

    No retrieval at all -- read data/corpus/<doc_id>.md for each gold doc,
    chunk it or pass it whole, and generate. The difference between this and
    answer_question() is the damage your retriever is doing.
    """
    # Build synthetic hits so format_context / citations still work (same generator path).
    from aip.chunking import Chunk
    from aip.retrieval import Hit as HitCls

    hits = []
    for i, doc in enumerate(gold_docs):
        text = doc if isinstance(doc, str) else str(doc)
        snippet = text[:3500]
        ch = Chunk(text=snippet, doc_id=f"gold_{i+1}", chunk_id=f"gold_{i+1}_0", meta={})
        hits.append(HitCls(chunk=ch, score=1.0, source="gold", rank=i))

    text, finish_reason = _generate(question, hits, tier=tier)
    v = validate_answer(text, len(hits), finish_reason)

    if not v["valid"] and not v["refused"]:
        text = REFUSAL
        v = validate_answer(text, len(hits), None)

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
