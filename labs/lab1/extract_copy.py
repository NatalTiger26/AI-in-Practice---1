#!/usr/bin/env python3
"""Lab 1, Parts B and C — the extractor you actually ship.

Complete the TODOs. `run_eval.py` imports `extract_b` and `extract_c` from
here, so keep those two function names.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from aip.llm import StructuredOutputError, structured

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


CATEGORIES = Literal["billing", "claims", "policy_change",
                     "technical", "complaint", "information"]


# ===========================================================================
# PART B — the schema
# ===========================================================================
class TicketRecord(BaseModel):
    """The contract. Everything the model is allowed to say, and nothing else.

    Remember from T2 §3.2: field `description`s are shipped to the model as
    part of the JSON Schema. They are the highest-leverage place to put an
    instruction, because they sit next to the thing they govern. Write them as
    instructions to the model, not as documentation for a human.
    """

    # B1a: evidence is declared BEFORE category (and the other judgement fields).
    # Reason (T2 §3.3): the model is autoregressive; emitting the evidence span
    # first forces it to locate the justifying text before it commits to a label,
    # rather than rationalising a label it has already chosen.
    evidence: str = Field(
        max_length=200,
        description=(
            "Quote verbatim the shortest span of the ticket that provides the "
            "clearest evidence for the chosen category. The text must come "
            "directly from the ticket; never paraphrase, summarize, or invent "
            "evidence. Maximum 200 characters."
        ),
    )

    category: CATEGORIES = Field(
        description=(
            "Choose exactly one category based on the customer's primary intent. "
            "billing = charges, payments, invoices, refunds, or fees; "
            "claims = filing, checking, or resolving an insurance claim; "
            "policy_change = changing or updating an insurance policy (members, "
            "cover, contact details, portability); "
            "technical = problems with a website, app, system, login, or other "
            "technical functionality; "
            "complaint = the primary purpose is expressing dissatisfaction with "
            "Aurora's conduct (mis-selling, ignored grievance, long hold times) "
            "rather than resolving a billing, claims, policy, or technical issue; "
            "information = a request for information that does not fit the other "
            "categories. If dissatisfaction accompanies a specific billing, "
            "claims, policy-change, or technical request, choose that specific "
            "category rather than complaint."
        ),
    )

    urgency: int = Field(
        ge=1, le=5,
        description=(
            "Assign exactly one urgency score from 1 to 5. Judge the situation, "
            "not the volume or emotional tone. "
            "Decision question for 1 vs 2: can this be answered without opening "
            "the customer's record? If yes → 1; if Aurora must look something up, "
            "act, or fix a defect → at least 2. "
            "1 = answerable from general product knowledge or self-service how-to "
            "(e.g. waiting period, where to download e-card). "
            "2 = requires lookup of this customer's account, an action, a defect "
            "fix, or a transaction in flight (e.g. wellness points, add newborn, "
            "app crashes on upload). "
            "3 = something has already gone wrong or is stuck and the customer is "
            "waiting (e.g. debited twice, portability request with no reply). "
            "4 = repeated failure to resolve, money or access at risk now, or an "
            "explicit escalation threat (e.g. standing at hospital desk, portal down). "
            "5 = emergency in progress, formal denial demanding immediate reversal, "
            "or the customer states they ARE escalating to the Ombudsman "
            "(threatening to escalate is 4; stating they are filing is 5). "
            "Modifier: +1 (capped at 5) if the message states a same-day or "
            "next-morning deadline. Do not raise urgency for shouting or anger alone."
        ),
    )

    # TODO B1d: sentiment  -> Literal["angry","frustrated","neutral","satisfied"]

    sentiment: Literal["angry","frustrated","neutral","satisfied"] = Field(
        # description="Sentiment has 4 values. With each one described as: "
        #             "angry: the customer is angry and upset, "
        #             "frustrated: the customer is frustrated and annoyed, "
        #             "neutral: the customer is neither happy nor upset, "
        #             "satisfied: the customer is happy and content."
    description=( "Classify the customer's expressed emotional attitude toward the " 
                 "situation. " 
                 "angry = clearly expresses anger, hostility, outrage, or strong " 
                 "resentment; " 
                 "frustrated = expresses annoyance, disappointment, difficulty, or " 
                 "exasperation without clear strong anger or hostility; " 
                 "neutral = factual, informational, or emotionally neutral language " 
                 "with no clear positive or negative emotional attitude; " 
                 "satisfied = expresses happiness, gratitude, approval, relief, or " 
                 "positive satisfaction. " 
                 "Do not classify a ticket as angry or frustrated merely because it " 
                 "describes a problem; use the customer's actual emotional language." ),
    )

    # TODO B1e: product    -> Literal["bronze","silver","gold","platinum","unknown"]
    #           Note "unknown" is a legal value. Say explicitly when to use it.
    product: Literal["bronze","silver","gold","platinum","unknown"] = Field(
        description="Product has 5 values. With each one described as: "
                    "bronze: the customer has a bronze level product, "
                    "silver: the customer has a silver level product, "
                    "gold: the customer has a gold level product, " 
                    "platinum: the customer has a platinum level product, "
                    "unknown: the product level is not mentioned in the ticket."
    )
    # TODO B1f: language   -> Literal["en","hi-en"]
    language: Literal["en","hi-en"] = Field(
            description="Language can take 2 values. With each one described as: "
                        "en: the ticket is written in English, "
                        "hi-en: the ticket is written in Hinglish (a mix of Hindi and English)."
        )   

    # TODO B1g: evidence   -> str, max_length=200, "the span of the ticket that
    #           determined the category, quoted verbatim"

    # Part B only: the model decides these. In Part C you will delete them
    # from this schema and compute them in code instead.
    policy_number: str | None = Field(
        default=None,
        description=(
            "Exact policy number in the form AUR- followed by exactly seven digits "
            "(e.g. AUR-1234567), copied verbatim from the ticket. Return null when "
            "no such string appears in the live message. Never invent, guess, or "
            "reformat a policy number."
        ),
    )
    contains_pii: bool = Field(
        default=False,
        # description="TODO B1i"
        description=( "Return true if the ticket contains a phone number or an email " 
                     "address. Return false when neither is present. A person's name " 
                     "alone does not count as PII for this dataset. Do not infer PII " 
                     "from information that is not explicitly present in the ticket." ),
    )

    # Set by our code, never by the model.
    needs_human_review: bool = False
    review_reason: str = ""

    @field_validator("policy_number")
    @classmethod
    def _policy_format(cls, v: str | None) -> str | None:
        # TODO B1j: reject anything that is not exactly AUR-<7 digits>.
        #           Return None rather than raising if the model returned an
        #           empty string or the literal "null" -- decide which of those
        #           two behaviours you want and defend it in your report.
        if v is None:
            return None
        v = v.strip()
        if v == "" or v.lower() == "null":
            return None
        if not re.fullmatch(r"AUR-\d{7}", v):
            return None          # or raise ValueError if you prefer strictness
        return v


# SYSTEM_PROMPT = """\
# TODO B2: write this using the seven-component structure from T2 §2.

# Order it for attention AND for prompt caching: stable instructions first,
# volatile data last. The ticket text is injected by the caller, after this.

# It should be shorter than your first instinct. Most of what you want to say
# belongs in the field descriptions above.
# """

# SYSTEM_PROMPT = """\
# You are an expert insurance-ticket classifier.

# 1. Role: Extract structured fields from a single customer support ticket.
# 2. Goal: Produce a JSON object that strictly matches the supplied schema.
# 3. Constraints:
#    - Quote evidence verbatim; never invent text.
#    - Use null for policy_number when none is present.
#    - Choose category by primary customer intent; prefer the concrete category
#      over "complaint" unless the dominant purpose is pure dissatisfaction.
# 4. Output format: pure JSON matching the schema – no markdown, no commentary.
# 5. Reasoning style: decide evidence first, then every other field.
# 6. Edge cases: Hindi-English code-mix → language="hi-en"; missing product → "unknown".
# 7. Ticket text follows below.
# """
SYSTEM_PROMPT = """\
You classify one insurance support ticket into the supplied structured schema.

Follow the field descriptions and allowed values exactly. Use the ticket text only;
do not invent facts. Return only a JSON object matching the schema.

The ticket appears below.
"""

def extract_b(ticket: str) -> TicketRecord:
    """Part B: the model decides everything."""
    # TODO B3: call aip.llm.structured with TicketRecord.
    try:
        return structured(
            prompt_or_messages=ticket,
            system=SYSTEM_PROMPT,
            schema=TicketRecord,
        )

        # <-- the model's output, validated and coerced to TicketRecord
    # TODO B4: catch StructuredOutputError and return a record with
    #          needs_human_review=True. This function must never raise.
    except StructuredOutputError as exc:
        return TicketRecord(
            evidence="",
            category="information",          # safe default
            urgency=1,
            sentiment="neutral",
            product="unknown",
            language="en",
            policy_number=None,
            contains_pii=False,
            needs_human_review=True,
            review_reason=f"StructuredOutputError: {exc}",
        )


# ===========================================================================
# PART C — move the deterministic work out of the model
# ===========================================================================
POLICY_RE = re.compile(r"\bAUR-\d{7}\b")

# The quoted-reply marker. Everything after this is history, not the current
# message. Part C3 asks you to decide what that means for policy extraction.
QUOTE_MARKER = re.compile(r"^\s*>", re.MULTILINE)


def extract_deterministic(ticket: str) -> dict:
    """TODO C1: return {'policy_number', 'contains_pii'} without a model call.

    policy_number:
        Find AUR-<7 digits>.

    TODO C3 -- the trap. Some tickets contain TWO policy-number-shaped strings:
        one in the live body, and one in a quoted reply below a '>' line from
        an earlier thread. They are not always the same number.

        Decide a rule. Write it down in a comment right here. Implement it.
        Then ask yourself whether it generalises or whether you have fitted it
        to this dataset -- the honest answer is worth marks.

    contains_pii:
        True if the ticket contains a phone number or an email address.
        aip.guards._PII_PATTERNS has the patterns. Note that a *name* alone
        does not count for this dataset's labels -- check the gold data and
        say in your report whether you think that definition is right.
    """
    # raise NotImplementedError
    """Extract fields that should not be decided by the model.

    Policy-number rule (matches annotation guidelines):
    Only accept a policy number that appears in the *live* message
    (text before any line starting with '>'). Lines beginning with '>'
    are quoted history from an earlier thread and may carry a different,
    stale number; a ticket whose only policy-shaped string is inside a
    quoted reply is labelled null. Signature blocks are treated the same
    way by restricting the search to live_text.
    This rule generalises: it follows the written annotation contract
    rather than fitting idiosyncrasies of this particular dataset.
    """
    quote_match = QUOTE_MARKER.search(ticket)

    if quote_match:
        live_text = ticket[:quote_match.start()]
    else:
        live_text = ticket

    # Strict: only the live message. No fallback to quoted history.
    live_match = POLICY_RE.search(live_text)
    policy_number = live_match.group(0) if live_match else None

    # Use the guard's own PII patterns. redact_pii() returns
    # (redacted_text, counts), so the counts are the reliable signal.
    from aip.guards import redact_pii

    _, pii_counts = redact_pii(ticket)
    contains_pii = bool(pii_counts)

    return {
        "policy_number": policy_number,
        "contains_pii": contains_pii,
    }

def apply_business_rules(rec_fields: dict, ticket: str) -> dict:
    """TODO C1b: compute `escalate` in code.

        escalate = urgency >= 4 or 'ombudsman' appears in the ticket

    This is a business rule. It belongs in code where it can be read by a
    compliance officer, changed without touching a prompt, and unit-tested.
    Write the unit test in tests/ while you are here.
    """
    # raise NotImplementedError
    urgency = rec_fields.get("urgency", 1)

    escalate = (
        urgency >= 4
        or "ombudsman" in ticket.lower()
    )

    return {
        **rec_fields,
        "escalate": escalate,
    }


class TicketRecordC(BaseModel):
    """TODO C2: the reduced schema the model sees in Part C.

    Copy TicketRecord and delete the fields you now compute in code. Fewer
    fields means a shorter prompt, fewer output tokens, and three fields at
    100% accuracy. Measure all three effects.
    """
    evidence: str = Field(
        max_length=200,
        description=(
            "Quote verbatim the shortest span of the ticket that provides the "
            "clearest evidence for the chosen category. The text must come "
            "directly from the ticket; never paraphrase, summarize, or invent "
            "evidence. Maximum 200 characters."
        ),
    )

    category: CATEGORIES = Field(
        description=(
            "Choose exactly one category based on the customer's primary intent. "
            "billing = charges, payments, invoices, refunds, or fees; "
            "claims = filing, checking, or resolving an insurance claim; "
            "policy_change = changing or updating an insurance policy; "
            "technical = problems with a website, app, system, login, or other "
            "technical functionality; "
            "complaint = the primary purpose is expressing dissatisfaction rather "
            "than resolving a billing, claims, policy, or technical issue; "
            "information = a request for information that does not fit the other "
            "categories. If dissatisfaction accompanies a specific billing, "
            "claims, policy-change, or technical request, choose that specific "
            "category rather than complaint."
        ),
    )

    urgency: int = Field(
        ge=1,
        le=5,
        description=(
            "Assign exactly one urgency score from 1 to 5. Judge the situation, "
            "not the volume or emotional tone. "
            "Decision question for 1 vs 2: can this be answered without opening "
            "the customer's record? If yes → 1; if Aurora must look something up, "
            "act, or fix a defect → at least 2. "
            "1 = answerable from general product knowledge or self-service how-to "
            "(e.g. waiting period, where to download e-card). "
            "2 = requires lookup of this customer's account, an action, a defect "
            "fix, or a transaction in flight (e.g. wellness points, add newborn, "
            "app crashes on upload). "
            "3 = something has already gone wrong or is stuck and the customer is "
            "waiting (e.g. debited twice, portability request with no reply). "
            "4 = repeated failure to resolve, money or access at risk now, or an "
            "explicit escalation threat (e.g. standing at hospital desk, portal down). "
            "5 = emergency in progress, formal denial demanding immediate reversal, "
            "or the customer states they ARE escalating to the Ombudsman "
            "(threatening to escalate is 4; stating they are filing is 5). "
            "Modifier: +1 (capped at 5) if the message states a same-day or "
            "next-morning deadline. Do not raise urgency for shouting or anger alone."
        ),
    )

    sentiment: Literal[
        "angry",
        "frustrated",
        "neutral",
        "satisfied",
    ] = Field(
        description=(
            "Classify the customer's expressed emotional attitude. "
            "angry = clear anger, hostility, outrage, or strong resentment; "
            "frustrated = annoyance, disappointment, difficulty, or exasperation "
            "without clear strong anger or hostility; "
            "neutral = factual or informational language without a clear positive "
            "or negative emotional attitude; "
            "satisfied = happiness, gratitude, approval, relief, or positive "
            "satisfaction. Do not infer negative sentiment merely because a "
            "problem is described."
        ),
    )

    product: Literal[
        "bronze",
        "silver",
        "gold",
        "platinum",
        "unknown",
    ] = Field(
        description=(
            "Identify the product tier only when explicitly stated or clearly "
            "identified in the ticket. "
            "bronze = Bronze; silver = Silver; gold = Gold; platinum = Platinum; "
            "unknown = the product tier is not stated or cannot be determined. "
            "Never infer the product tier."
        ),
    )

    language: Literal["en", "hi-en"] = Field(
        description=(
            "en = the ticket is written in English. "
            "hi-en = the ticket mixes Hindi and English (Hinglish). "
            "Use hi-en when Hindi words or phrases are mixed with English; "
            "otherwise use en."
        ),
    )



def extract_c(ticket: str) -> dict:
    """Part C: model for judgement, code for everything else.

    Returns a plain dict (model fields + deterministic fields + business rules)
    so that run_eval.py can score it against the gold labels directly.
    """
    # raise NotImplementedError
    try:
        model_record = structured(
            prompt_or_messages=ticket,
            system=SYSTEM_PROMPT,
            schema=TicketRecordC,
        )

        model_fields = model_record.model_dump()
        deterministic_fields = extract_deterministic(ticket)

        result = apply_business_rules(
            {
                **model_fields,
                **deterministic_fields,
            },
            ticket,
        )

        return result

    except StructuredOutputError as exc:
        return {
            "evidence": "",
            "category": "information",
            "urgency": 1,
            "sentiment": "neutral",
            "product": "unknown",
            "language": "en",
            "policy_number": None,
            "contains_pii": False,
            "escalate": False,
            "needs_human_review": True,
            "review_reason": f"StructuredOutputError: {exc}",
        }


if __name__ == "__main__":
    import json

    root = Path(__file__).resolve().parents[2]
    sample = json.loads(
        (root / "data/eval/extraction_dev.jsonl").open(encoding="utf-8").readline()
    )
    print("--- ticket ---")
    print(sample["input"][:600])
    print("\n--- gold ---")
    print(sample["expected"])
    print("\n--- yours ---")
    print(extract_c(sample["input"]))
