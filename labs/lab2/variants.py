#!/usr/bin/env python3
"""Lab 2 — the configurations under test.

Each variant is a callable `str -> dict`. `grid.py` runs them all through the
same harness, so the only thing that differs between rows of your table is the
thing you intended to differ.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from aip.llm import StructuredOutputError, structured  # noqa: E402

from labs.lab1.extract import (  # noqa: E402
    SYSTEM_PROMPT,
    TicketRecordC,
    apply_business_rules,
    extract_deterministic,
)

# ---------------------------------------------------------------------------
# A1 — your six chosen examples.
# ---------------------------------------------------------------------------
# TODO A1: choose 6 dev-set tickets. For EACH, write one line saying what it
#          teaches that prose cannot. Pick edges, not averages (T2 §2.2):
#            - the billing/complaint boundary
#            - a ticket with no policy number (teaches null)
#            - a Hinglish ticket
#            - a satisfied-but-urgent ticket (the sentiment/urgency trap)
#            - a ticket whose policy number is only in a quoted reply
#            - one you got wrong in Lab 1
FEW_SHOT_IDS: list[str] = [
    "T0054",  # teaches: billing/complaint boundary — pure complaint, angry, no policy
    "T0097",  # teaches: angry billing is still billing, not complaint
    "T0200",  # teaches: Hinglish → language=hi-en
    "T0187",  # teaches: pure information, urgency=1 (no record lookup)
    "T0029",  # teaches: null policy_number when absent from live message
    "T0021",  # teaches: Hinglish + high urgency technical (edge from Lab 1 errors)
]


def load_examples(ids: list[str]) -> list[dict]:
    rows = [json.loads(l) for l in
            (ROOT / "data/eval/extraction_dev.jsonl").open(encoding="utf-8")]
    by_id = {r["id"]: r for r in rows}
    missing = [i for i in ids if i not in by_id]
    if missing:
        raise KeyError(f"unknown example ids: {missing}")
    return [by_id[i] for i in ids]


def few_shot_block(ids: list[str]) -> str:
    """TODO A2: render the examples into the prompt.

    The example output format must be byte-identical to the format you are
    asking the model to produce. A mismatch here is a classic own goal.
    """
    examples = load_examples(ids)
    blocks = []
    for i, example in enumerate(examples, start=1):
        expected = example["expected"]
        # Match TicketRecordC fields only — deterministic fields are not asked of the model.
        output = {
            "evidence": example["input"][:120].replace("\n", " ").strip(),
            "category": expected["category"],
            "urgency": expected["urgency"],
            "sentiment": expected["sentiment"],
            "product": expected["product"],
            "language": expected["language"],
        }
        blocks.append(
            f"Example {i}\n"
            f"Ticket:\n{example['input']}\n\n"
            f"Output:\n{json.dumps(output, ensure_ascii=False)}"
        )
    return "\n\n".join(blocks)


# ---------------------------------------------------------------------------
# Shared path: Lab 1 Part C (model for judgement fields, code for the rest)
# ---------------------------------------------------------------------------
def _run(ticket: str, *, schema, system: str, tier: str = "SMALL") -> dict:
    try:
        rec = structured(
            prompt_or_messages=ticket,
            system=system,
            schema=schema,
            tier=tier,
        )
        model_fields = rec.model_dump() if hasattr(rec, "model_dump") else dict(rec)
    except StructuredOutputError as exc:
        model_fields = {
            "evidence": "",
            "category": "information",
            "urgency": 1,
            "sentiment": "neutral",
            "product": "unknown",
            "language": "en",
            "needs_human_review": True,
            "review_reason": f"StructuredOutputError: {exc}",
        }
    model_fields.pop("reasoning", None)
    det = extract_deterministic(ticket)
    return apply_business_rules({**model_fields, **det}, ticket)


# ---------------------------------------------------------------------------
# The variants
# ---------------------------------------------------------------------------
def zero_shot(ticket: str, tier: str = "SMALL") -> dict:
    """TODO B: Lab 1 Part C, no examples. This is your baseline."""
    return _run(ticket, schema=TicketRecordC, system=SYSTEM_PROMPT, tier=tier)


def few_shot(ticket: str, tier: str = "SMALL") -> dict:
    """TODO B: zero_shot + the few-shot block."""
    system = (
        SYSTEM_PROMPT
        + "\n\nHere are examples showing exactly how tickets should be classified. "
        "Match the same output structure and decision rules.\n\n"
        + few_shot_block(FEW_SHOT_IDS)
    )
    return _run(ticket, schema=TicketRecordC, system=system, tier=tier)


class TicketRecordReasoned(BaseModel):
    """TODO B: add a `reasoning: str` field FIRST (T2 §3.3).

    Pydantic keeps declaration order, and field order in the JSON Schema
    influences generation order. Putting reasoning first makes it condition the
    answer; putting it last makes it a post-hoc rationalisation. You want the
    first. Measure the difference in output tokens.
    """

    reasoning: str = Field(
        default="",
        description=(
            "One or two sentences explaining the evidence used for category and "
            "urgency. Quote or closely paraphrase the decisive span. Write this "
            "field first, then the other fields."
        ),
    )
    evidence: str = Field(
        max_length=200,
        description=(
            "Quote verbatim the shortest span of the ticket that provides the "
            "clearest evidence for the chosen category. Maximum 200 characters."
        ),
    )
    category: Literal[
        "billing", "claims", "policy_change", "technical", "complaint", "information"
    ] = Field(
        description=(
            "Choose exactly one category based on primary intent. Prefer a "
            "concrete category over complaint when the customer still wants a "
            "billing, claims, policy, or technical issue resolved."
        ),
    )
    urgency: int = Field(
        ge=1,
        le=5,
        description=(
            "1–5 scale from the annotation guide. 1 = answerable without opening "
            "the customer record; 2 = needs lookup/action/defect fix; 3 = already "
            "stuck; 4 = money/access at risk now or escalation threat; 5 = "
            "emergency or customer states they are filing with the Ombudsman."
        ),
    )
    sentiment: Literal["angry", "frustrated", "neutral", "satisfied"] = Field(
        description="Tone only. frustrated requires reference to a prior failure.",
    )
    product: Literal["bronze", "silver", "gold", "platinum", "unknown"] = Field(
        description="Plan tier only when named; otherwise unknown.",
    )
    language: Literal["en", "hi-en"] = Field(
        description="hi-en if Hindi words mix into English; else en.",
    )


def few_shot_reasoned(ticket: str, tier: str = "SMALL") -> dict:
    """TODO B: few_shot with TicketRecordReasoned."""
    system = (
        SYSTEM_PROMPT
        + "\n\nHere are examples showing exactly how tickets should be classified. "
        "Also produce a brief reasoning field before the other fields.\n\n"
        + few_shot_block(FEW_SHOT_IDS)
    )
    return _run(ticket, schema=TicketRecordReasoned, system=system, tier=tier)


def cascade(ticket: str) -> dict:
    """TODO C: SMALL first; escalate to MAIN on a trigger you choose.

    Triggers, roughly in ascending order of how well they work:
      - validation failed                      (free, weak: misses confident errors)
      - evidence field empty or very short     (free, surprisingly decent)
      - urgency >= 4                           (free, but it is not a confidence signal)
      - two SMALL samples at T=0.7 disagree    (2x small cost, much the best)

    Record which path each ticket took -- set rec['_path'] = 'small' | 'large'
    so grid.py can report the escalation rate.
    """
    # Trigger: validation failure, or evidence empty / very short (free signals).
    # Avoids the T=0 double-sample cache bug (identical cache hit → never escalates).
    small = zero_shot(ticket, tier="SMALL")

    if small.get("needs_human_review"):
        large = zero_shot(ticket, tier="MAIN")
        large["_path"] = "large"
        return large

    evidence = str(small.get("evidence") or "").strip()
    if len(evidence) < 12:
        large = zero_shot(ticket, tier="MAIN")
        large["_path"] = "large"
        return large

    small["_path"] = "small"
    return small


VARIANTS = {
    "zero_shot": lambda t: zero_shot(t, "SMALL"),
    "zero_shot_main": lambda t: zero_shot(t, "MAIN"),
    "few_shot": lambda t: few_shot(t, "SMALL"),
    "few_shot_main": lambda t: few_shot(t, "MAIN"),
    "few_shot_reasoned": lambda t: few_shot_reasoned(t, "SMALL"),
    "few_shot_reasoned_main": lambda t: few_shot_reasoned(t, "MAIN"),
    "cascade": cascade,
}
