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

    # TODO B1a: Should `evidence` be declared here, BEFORE the fields it
    #           justifies, or after them? T2 §3.3. Decide, move it, and leave
    #           a one-line comment saying which effect you chose and why.
    evidence: str = Field(
        max_length=200,
        description="evidence is a string field containing the span of the ticket that determined the "
                    "category, quoted verbatim. It is allowed a max of 200 characters."
    )

    category: CATEGORIES = Field(
        description="TODO B1b: define each of the six categories in one clause "
                    "each. Pay particular attention to the boundary between "
                    "'complaint' and the category the complaint is about."
    )

    urgency: int = Field(
        ge=1, le=5,
        # description="TODO B1c: define the 1-5 scale concretely. Anchor at least "
        #             "points 1, 3 and 5 with a describable situation. If you do "
        #             "not define the scale, the model invents one, and it will "
        #             "not be the one the gold labels use."
        # description="Urgency is an integer field with values from 1 to 5, where: "
        #             "1: the ticket is not urgent and can be addressed at leisure, "
        #             "2: the ticket is somewhat urgent and should be addressed soon, "
        #             "3: the ticket is moderately urgent and should be addressed promptly, "
        #             "4: the ticket is urgent and requires immediate attention, "
        #             "5: the ticket is extremely urgent and requires immediate action."
    description=(
        "Rate urgency from 1 to 5 using the immediate impact and time sensitivity "
        "described in the ticket. "
        "1 = no immediate action is needed; the issue is routine, informational, "
        "or can safely wait several days. "
        "2 = low urgency; the customer needs assistance but there is no immediate "
        "impact, deadline, or meaningful consequence from waiting. "
        "3 = moderate urgency; the issue is affecting the customer now or requires "
        "a timely response, but waiting a short period does not create a serious "
        "consequence. "
        "4 = high urgency; the issue is materially disrupting the customer or "
        "creating a significant financial, access, coverage, or time-sensitive "
        "problem and should be handled promptly. "
        "5 = critical urgency; the ticket describes an immediate or imminent "
        "serious consequence, major loss, inability to access essential service, "
        "or a time-critical situation requiring immediate intervention. "
        "Base the score only on the situation described in the ticket, not on "
        "politeness, capitalization, exclamation marks, or emotional tone. "
        "Do not increase urgency merely because the customer is angry or "
        "frustrated."
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
        description="TODO B1h: state the exact format, and state explicitly "
                    "that null is required when no policy number appears. "
                    "Forbid inventing or reformatting one."
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

    Policy-number rule:
    Prefer a policy number appearing in the live/current message. If the
    current message contains no policy number, fall back to the first policy
    number found in quoted history. This is a general rule because quoted
    replies represent historical context, while the live message is the
    user's current request.
    """
    quote_match = QUOTE_MARKER.search(ticket)

    if quote_match:
        live_text = ticket[:quote_match.start()]
        history_text = ticket[quote_match.start():]
    else:
        live_text = ticket
        history_text = ""

    # Prefer the policy number in the current/live message.
    live_match = POLICY_RE.search(live_text)

    if live_match:
        policy_number = live_match.group(0)
    else:
        # Only use quoted history when the live message has no policy number.
        history_match = POLICY_RE.search(history_text)
        policy_number = history_match.group(0) if history_match else None

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
        "Assign exactly one urgency score from 1 to 5 based on the severity "
        "and time sensitivity of the customer's actual problem. "
        "1 = routine or informational request; no meaningful harm or consequence "
        "if handled later. "
        "2 = minor issue that should be handled eventually, but delay causes "
        "little or no meaningful consequence. "
        "3 = important issue affecting the customer now or requiring a timely "
        "response, but a short delay is unlikely to cause serious harm or loss. "
        "4 = urgent issue where delay is likely to cause significant financial "
        "loss, loss of access, disruption of coverage/service, missed deadline, "
        "or another substantial consequence. "
        "5 = critical issue involving an immediate or imminent serious "
        "consequence, such as a major financial loss, inability to access an "
        "essential service, imminent deadline, active fraud/security concern, "
        "or another situation requiring immediate intervention. "
        "Use the highest score clearly supported by the ticket, but do not "
        "infer urgency from anger, frustration, capitalization, exclamation "
        "marks, or the mere fact that the customer has a problem."
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
