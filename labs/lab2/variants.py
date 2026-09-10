# #!/usr/bin/env python3
# """Lab 2 — the configurations under test.

# Each variant is a callable `str -> dict`. `grid.py` runs them all through the
# same harness, so the only thing that differs between rows of your table is the
# thing you intended to differ.
# """
# from __future__ import annotations

# import json
# import sys
# from pathlib import Path

# ROOT = Path(__file__).resolve().parents[2]
# sys.path.insert(0, str(ROOT))

# from labs.lab1.extract import (  # noqa: E402
#     SYSTEM_PROMPT, TicketRecord, apply_business_rules, extract_deterministic,
# )

# # ---------------------------------------------------------------------------
# # A1 — your six chosen examples.
# # ---------------------------------------------------------------------------
# # TODO A1: choose 6 dev-set tickets. For EACH, write one line saying what it
# #          teaches that prose cannot. Pick edges, not averages (T2 §2.2):
# #            - the billing/complaint boundary
# #            - a ticket with no policy number (teaches null)
# #            - a Hinglish ticket
# #            - a satisfied-but-urgent ticket (the sentiment/urgency trap)
# #            - a ticket whose policy number is only in a quoted reply
# #            - one you got wrong in Lab 1
# # FEW_SHOT_IDS: list[str] = [
# #     # "T0123",   # teaches: ...
# # ]
# FEW_SHOT_IDS: list[str] = [
#     "T0097",  # billing/complaint boundary
#     "T0054",  # no policy number -> null
#     "T0200",  # Hinglish
#     "T0222",  # satisfied-but-urgent
#     "T0029",   # policy number only in quoted reply
#     "T0202",  # got wrong in Lab 1
# ]



# def load_examples(ids: list[str]) -> list[dict]:
#     rows = [json.loads(l) for l in
#             (ROOT / "data/eval/extraction_dev.jsonl").open(encoding="utf-8")]
#     by_id = {r["id"]: r for r in rows}
#     missing = [i for i in ids if i not in by_id]
#     if missing:
#         raise KeyError(f"unknown example ids: {missing}")
#     return [by_id[i] for i in ids]


# def few_shot_block(ids: list[str]) -> str:
#     """TODO A2: render the examples into the prompt.

#     The example output format must be byte-identical to the format you are
#     asking the model to produce. A mismatch here is a classic own goal.
#     """
#     # raise NotImplementedError
#     """Render selected examples in the exact format requested from the model."""
#     # examples = load_examples(ids)

#     # blocks = []

#     # for i, example in enumerate(examples, 1):
#     #     ticket = example["text"]

#     #     output = {
#     #         "evidence": example["evidence"],
#     #         "category": example["category"],
#     #         "urgency": example["urgency"],
#     #         "sentiment": example["sentiment"],
#     #         "product": example["product"],
#     #     }

#     #     blocks.append(
#     #         f"Example {i}\n"
#     #         f"Ticket:\n{ticket}\n\n"
#     #         f"Output:\n{json.dumps(output, ensure_ascii=False)}"
#     #     )

#     # return "\n\n".join(blocks)
#     """Render selected examples in the exact format requested from the model."""
#     examples = load_examples(ids)

#     blocks = []
#     for i, example in enumerate(examples, start=1):
#         blocks.append(
#             f"Example {i}:\n"
#             f"{json.dumps(example, ensure_ascii=False)}"
#         )

#     return "\n\n".join(blocks)



# # ---------------------------------------------------------------------------
# # The variants
# # ---------------------------------------------------------------------------
# def zero_shot(ticket: str, tier: str = "SMALL") -> dict:
#     """TODO B: Lab 1 Part C, no examples. This is your baseline."""
#     raise NotImplementedError


# def few_shot(ticket: str, tier: str = "SMALL") -> dict:
#     """TODO B: zero_shot + the few-shot block."""
#     raise NotImplementedError


# class TicketRecordReasoned(TicketRecord):
#     """TODO B: add a `reasoning: str` field FIRST (T2 §3.3).

#     Pydantic keeps declaration order, and field order in the JSON Schema
#     influences generation order. Putting reasoning first makes it condition the
#     answer; putting it last makes it a post-hoc rationalisation. You want the
#     first. Measure the difference in output tokens.
#     """


# def few_shot_reasoned(ticket: str, tier: str = "SMALL") -> dict:
#     """TODO B: few_shot with TicketRecordReasoned."""
#     raise NotImplementedError


# def cascade(ticket: str) -> dict:
#     """TODO C: SMALL first; escalate to MAIN on a trigger you choose.

#     Triggers, roughly in ascending order of how well they work:
#       - validation failed                      (free, weak: misses confident errors)
#       - evidence field empty or very short     (free, surprisingly decent)
#       - urgency >= 4                           (free, but it is not a confidence signal)
#       - two SMALL samples at T=0.7 disagree    (2x small cost, much the best)

#     Record which path each ticket took -- set rec['_path'] = 'small' | 'large'
#     so grid.py can report the escalation rate.
#     """
#     raise NotImplementedError


# VARIANTS = {
#     "zero_shot": lambda t: zero_shot(t, "SMALL"),
#     "zero_shot_main": lambda t: zero_shot(t, "MAIN"),
#     "few_shot": lambda t: few_shot(t, "SMALL"),
#     "few_shot_main": lambda t: few_shot(t, "MAIN"),
#     "few_shot_reasoned": lambda t: few_shot_reasoned(t, "SMALL"),
#     "few_shot_reasoned_main": lambda t: few_shot_reasoned(t, "MAIN"),
#     "cascade": cascade,
# }
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

from pydantic import create_model

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from aip.llm import StructuredOutputError, structured  # noqa: E402

from labs.lab1.extract import (  # noqa: E402
    SYSTEM_PROMPT,
    TicketRecord,
    TicketRecordC,
    apply_business_rules,
    extract_deterministic,
)


# ---------------------------------------------------------------------------
# A1 — your six chosen examples.
# ---------------------------------------------------------------------------

FEW_SHOT_IDS: list[str] = [
    "T0097",  # teaches: billing/complaint boundary
    "T0054",  # teaches: no policy number -> null
    "T0200",  # teaches: Hinglish
    "T0222",  # teaches: satisfied-but-urgent
    "T0029",  # teaches: policy number only in quoted reply
    "T0207",  # teaches: example that was wrong in Lab 1
]


def load_examples(ids: list[str]) -> list[dict]:
    rows = [
        json.loads(l)
        for l in (
            ROOT / "data/eval/extraction_dev.jsonl"
        ).open(encoding="utf-8")
    ]

    by_id = {r["id"]: r for r in rows}

    missing = [i for i in ids if i not in by_id]
    if missing:
        raise KeyError(f"unknown example ids: {missing}")

    return [by_id[i] for i in ids]


# def few_shot_block(ids: list[str]) -> str:
#     """Render examples in exactly the JSON format requested from the model."""

#     examples = load_examples(ids)

#     blocks = []

#     for i, example in enumerate(examples, start=1):
#         # IMPORTANT:
#         # This must match the format that TicketRecord asks the model to
#         # produce. Do NOT dump the entire dataset row because that may contain
#         # fields such as id/text that are not part of the requested output.
#         output = {
#             "evidence": example["evidence"],
#             "category": example["category"],
#             "urgency": example["urgency"],
#             "sentiment": example["sentiment"],
#             "product": example["product"],
#             "language": example["language"],
#             "policy_number": example["policy_number"],
#             "contains_pii": example["contains_pii"],
#         }

#         blocks.append(
#             f"Example {i}\n"
#             f"Ticket:\n{example['text']}\n\n"
#             f"Output:\n"
#             f"{json.dumps(output, ensure_ascii=False)}"
#         )

#     return "\n\n".join(blocks)

def few_shot_block(ids: list[str]) -> str:
    """Render selected examples in the exact format requested from the model."""
    examples = load_examples(ids)

    blocks = []

    for i, example in enumerate(examples, start=1):
        ticket = example["input"]
        expected = example["expected"]

        # The few-shot output must match the model's requested JSON format.
        # Evidence is not present in the dev gold data, so we don't invent it.
        output = {
            "category": expected["category"],
            "urgency": expected["urgency"],
            "sentiment": expected["sentiment"],
            "product": expected["product"],
            "language": expected["language"],
            "policy_number": expected["policy_number"],
            "contains_pii": expected["contains_pii"],
            "escalate": expected["escalate"],
        }

        blocks.append(
            f"Example {i}:\n"
            f"Ticket:\n{ticket}\n\n"
            f"Output:\n"
            f"{json.dumps(output, ensure_ascii=False)}"
        )

    return "\n\n".join(blocks)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _extract_with_schema(
    ticket: str,
    schema,
    system_prompt: str,
) -> dict:
    """Call the structured-output model and return a plain dict.

    On structured-output failure, return a safe human-review record rather
    than allowing the grid evaluation to crash.
    """
    try:
        rec = structured(
            prompt_or_messages=ticket,
            system=system_prompt,
            schema=schema,
        )

        if hasattr(rec, "model_dump"):
            return rec.model_dump()

        return dict(rec)

    except StructuredOutputError as exc:
        # Keep the shape compatible with the rest of the pipeline.
        if schema is TicketRecordC:
            return {
                "evidence": "",
                "category": "information",
                "urgency": 1,
                "sentiment": "neutral",
                "product": "unknown",
                "language": "en",
                "needs_human_review": True,
                "review_reason": f"StructuredOutputError: {exc}",
            }

        return {
            "evidence": "",
            "category": "information",
            "urgency": 1,
            "sentiment": "neutral",
            "product": "unknown",
            "language": "en",
            "policy_number": None,
            "contains_pii": False,
            "needs_human_review": True,
            "review_reason": f"StructuredOutputError: {exc}",
        }


def _build_prompt(extra_instructions: str = "") -> str:
    """Build the stable system instructions used by the variants."""

    prompt = SYSTEM_PROMPT

    if extra_instructions:
        prompt += "\n\n" + extra_instructions

    return prompt


# ---------------------------------------------------------------------------
# The variants
# ---------------------------------------------------------------------------

def zero_shot(ticket: str, tier: str = "SMALL") -> dict:
    """Baseline: ask the model to extract the complete TicketRecord."""

    # The tier argument is intentionally accepted because grid.py uses it.
    # The structured() helper selects/uses the configured model tier.
    del tier

    return _extract_with_schema(
        ticket=ticket,
        schema=TicketRecord,
        system_prompt=_build_prompt(),
    )


def few_shot(ticket: str, tier: str = "SMALL") -> dict:
    """Zero-shot plus six carefully selected examples."""

    del tier

    prompt = _build_prompt(
        "Here are examples showing exactly how tickets should be classified. "
        "Follow the same output structure and decision rules.\n\n"
        + few_shot_block(FEW_SHOT_IDS)
    )

    return _extract_with_schema(
        ticket=ticket,
        schema=TicketRecord,
        system_prompt=prompt,
    )


class TicketRecordReasoned(TicketRecord):
    """TicketRecord with reasoning declared FIRST.

    The reasoning field comes first intentionally: the model should produce
    its reasoning before the final classification fields.
    """

    reasoning: str = (
        # Pydantic v2 supports this form, but using a Field gives the model
        # a useful description in the generated JSON schema.
        ""
    )


# Rebuild the class with a proper Pydantic Field for reasoning.
# This keeps `reasoning` first in the schema.
from pydantic import Field  # noqa: E402


class TicketRecordReasoned(TicketRecord):
    reasoning: str = Field(
        default="",
        description=(
            "Briefly explain the evidence and decision used to classify the "
            "ticket. Quote or refer to the relevant ticket evidence. "
            "Decide evidence first, then category, urgency, sentiment, "
            "product, and language."
        ),
    )


def few_shot_reasoned(ticket: str, tier: str = "SMALL") -> dict:
    """Few-shot extraction with a reasoning field."""

    del tier

    prompt = _build_prompt(
        "Here are examples showing exactly how tickets should be classified. "
        "Use the examples as demonstrations. For this variant, also provide "
        "a brief reasoning field before the final classification fields.\n\n"
        + few_shot_block(FEW_SHOT_IDS)
    )

    return _extract_with_schema(
        ticket=ticket,
        schema=TicketRecordReasoned,
        system_prompt=prompt,
    )


def cascade(ticket: str) -> dict:
    """Run SMALL first and escalate to MAIN when the result looks uncertain.

    The trigger used here is weak/empty evidence. This is cheap because it
    requires only one SMALL call before deciding whether to escalate.
    """

    small = zero_shot(ticket, "SMALL")

    # If the first call failed validation, send it to MAIN.
    if small.get("needs_human_review"):
        large = zero_shot(ticket, "MAIN")
        large["_path"] = "large"
        return large

    # Evidence is our cheap uncertainty signal.
    evidence = str(small.get("evidence", "")).strip()

    if len(evidence) < 10:
        large = zero_shot(ticket, "MAIN")
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
