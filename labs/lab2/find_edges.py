import json

path = "data/eval/extraction_dev.jsonl"

with open(path, encoding="utf-8") as f:
    rows = [json.loads(line) for line in f]

print("\n=== SATISFIED + URGENT ===")
for r in rows:
    e = r["expected"]
    if e["sentiment"] == "satisfied" and e["urgency"] >= 3:
        print(r["id"], e["sentiment"], e["urgency"])
        print(r["input"])
        print()

print("\n=== NO POLICY NUMBER + QUOTED HISTORY ===")
for r in rows:
    e = r["expected"]
    if e["policy_number"] is None and ">" in r["input"]:
        print(r["id"])
        print(r["input"])
        print()

print("\n=== BILLING ===")
for r in rows:
    e = r["expected"]
    if e["category"] == "billing":
        text = r["input"].lower()
        if any(x in text for x in ["ombudsman", "refund", "double debit", "twice"]):
            print(r["id"])
            print(r["input"])
            print()

print("\n=== HINGLISH ===")
for r in rows:
    if r["expected"]["language"] == "hi-en":
        print(r["id"], "|", r["input"].replace("\n", " ")[:250])

print("\n=== NO POLICY NUMBER ===")
for r in rows:
    if r["expected"]["policy_number"] is None:
        print(r["id"], "|", r["input"].replace("\n", " ")[:250])
