# Lab 2 Report — The Prompt Lab

## Setup

Lab 2 builds on Lab 1 Part C (`TicketRecordC` + deterministic fields).  
Seven configurations in `variants.py`; grid run on dev (n=60).

```bash
python labs/lab2/grid.py --all --split dev --save reports/lab2_grid.json
```

**Run caveat.** Free-tier Gemini quotas still blocked MAIN-tier models (daily limit on `gemini-3.7-flash`). SMALL variants completed with low error rates on the second run; several rows were served from cache ($0 / 0 ms). Numbers below are from the second full grid.

---

## Part A — Few-shot selection

### The six examples

| ID | What it teaches that prose cannot |
|---|---|
| T0054 | Pure `complaint` (angry conduct grievance, no policy) — anger alone ≠ billing |
| T0097 | Angry **billing** ticket — concrete money issue wins over complaint |
| T0200 | Hinglish claims ticket — forces `language=hi-en` |
| T0187 | Pure information, urgency 1 — answerable without opening the record |
| T0029 | Null policy number + satisfied — teaches `null` and tone ≠ urgency |
| T0021 | Hinglish + technical + urgency 5 — high-urgency code-mix edge |

### A4 — Same-split leakage

Examples were drawn from **dev** and scored on **dev**. That optimistically biases few-shot on those six items (and similar neighbours).

Mitigation: treat few-shot gains as an upper bound; decide with paired tests and cost. The lab’s expected lesson holds if few-shot does not significantly beat zero-shot (rules already live in field descriptions).

---

## Part B — Grid table (dev, n=60)

| Configuration | record_acc | field_acc | schema_valid | error_rate | cost_usd | cost/1k | p95_ms |
|---|---|---|---|---|---|---|---|
| zero_shot (SMALL) | 0.300 | 0.867 | 1.000 | 0.000 | ~0* | ~0* | ~0* |
| zero_shot_main | 0.000† | 0.812† | 1.000† | **0.900** | ~0† | — | — |
| few_shot (SMALL) | 0.386 | 0.882 | 1.000 | 0.050 | 0.023 | $0.38 | 1286 |
| few_shot_main | 1.000† | 1.000† | 1.000† | **0.983** | ~0† | — | — |
| few_shot_reasoned (SMALL) | 0.429 | 0.897 | 1.000 | 0.067 | 0.022 | $0.37 | 1342 |
| few_shot_reasoned_main | — | — | — | **1.000** | 0 | — | — |
| cascade | 0.300 | 0.867 | 1.000 | 0.000 | ~0* | ~0* | ~0* |

\* Cached from earlier successful SMALL calls.  
† MAIN rows dominated by rate-limit failures — not a fair model comparison.

**1. Which axis moved numbers most?**  
Among measurable SMALL configs, prompt strategy lifted record accuracy from 0.300 → 0.386 (few-shot) → 0.429 (reasoned), but all differences stay inside paired-test noise. Model tier was not measurable. **Cost and reliability moved more than quality.**

**2. Reasoning field — tokens vs accuracy?**  
`few_shot_reasoned` has the highest field_acc (0.897) and record_acc (0.429) among completed SMALL runs, at similar cost to few-shot ($0.022 vs $0.023). Paired vs zero_shot: **p=0.286** — not significant. Points per rupee not distinguishable from noise.

**3. Dominated configurations?**  
MAIN variants are unusable here (quota), not dominated on merit. Among SMALL: none is better on quality **and** cost **and** latency with statistical support; cascade ≡ zero_shot.

---

## Part C — Cascade

| Metric | Value |
|---|---|
| Escalation rate | **0.00** |
| Blended cost | same as pure SMALL (all on small path / cache) |
| Blended accuracy | identical to zero_shot (record 0.300, field 0.867) |
| vs pure SMALL | identical on every item (b=0, c=0) |
| vs pure MAIN | MAIN not measurable |

**Trigger:** validation failure / `needs_human_review`, or evidence length < 12.

**Interpretation:** Escalation rate 0 ⇒ cascade was operationally pure SMALL. A weak free trigger can look like a routing system while never routing. Report the rate; do not assume benefit. Stronger triggers (e.g. disagreement at T>0) need a separate experiment when quota allows.

---

## Part D — Is the difference real?

Paired tests vs **zero_shot**:

| Comparison | b | c | p-value | Verdict |
|---|---|---|---|---|
| zero_shot vs zero_shot_main | 18 | 0 | 0.0000 | A better — **MAIN rate-limit artefact** |
| zero_shot vs few_shot | 5 | 9 | **0.4240** | no significant difference — choose on cost |
| zero_shot vs few_shot_main | 18 | 1 | 0.0001 | A better — **MAIN rate-limit artefact** |
| zero_shot vs few_shot_reasoned | 8 | 14 | **0.2863** | no significant difference — choose on cost |
| zero_shot vs cascade | 0 | 0 | 1.0 | identical on every item |

Wilson CI for few_shot_reasoned record accuracy [0.316, 0.559] overlaps zero_shot’s [0.199, 0.425]. **No configuration is detectably better than zero_shot SMALL.**

---

## Part E — Error analysis and recommendation

### Top three error clusters (SMALL)

1. **Urgency 1/2 and 2/3 boundaries** — account lookups as 1; first-time defects as 3.  
2. **Complaint vs concrete category** — angry claims/billing labelled `complaint`.  
3. **Sentiment neutral/frustrated** — first contact as frustrated, or prior-delay as neutral.

### Worst field

**Urgency** — systematic off-by-one at annotation boundaries (same as Lab 1).

### Recommendation

**Ship `zero_shot` on SMALL (Lab 1 Part C).**  
Few-shot and few-shot_reasoned show higher point estimates (record 0.386 / 0.429) but paired tests do not reject equality (p=0.42 / 0.29). They add example and reasoning tokens on every call. Schema validity is 1.0 on successful SMALL runs. Cascade did not escalate and matched zero_shot exactly.

Annual cost at 10,000 tickets/day tracks SMALL unit cost (this run’s live few-shot scale ≈ $0.37/1k → on the order of ~$1.3k/year if every ticket paid that rate; pure zero_shot is cheaper when not paying for few-shot tokens).

**I would change my mind if** a full MAIN run without rate limits, or a cascade with a stronger trigger, showed a paired-significant record-accuracy gain large enough to justify the extra cost.

---

## Negative results (required)

1. **Few-shot does not significantly beat zero-shot** (p=0.42) despite a higher point estimate.  
2. **Reasoning field** improves the point estimate (0.429) but not significantly (p=0.29); extra tokens are not clearly earned.  
3. **Cascade escalation rate = 0** — routing never fired; cascade ≡ zero_shot.  
4. **Free-tier quota** made all MAIN configurations unmeasurable (error rates 0.90–1.00). Claims that “MAIN is worse” would be wrong; the failure is infrastructure.

---

## Files submitted

- `labs/lab2/variants.py` — configurations + cascade  
- `labs/lab2/report.md` — this file  
- `reports/lab2_grid.json` — raw / summary harness output  
