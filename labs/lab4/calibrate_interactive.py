#!/usr/bin/env python3
"""Interactive hand-labeler for Lab 4 D2 calibration (autosaves after each item).

    python labs/lab4/calibrate_interactive.py

Reads reports/lab4.json (first 20 rows), writes/updates
labs/lab4/calibration_labels.jsonl after every answer so you can quit
and resume anytime. Then run:

    python labs/lab4/evaluate.py --kappa
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FULL = ROOT / "reports" / "lab4.json"
OUT = ROOT / "labs" / "lab4" / "calibration_labels.jsonl"
N = 20


def load_existing() -> dict[str, dict]:
    if not OUT.exists():
        return {}
    by_id = {}
    for line in OUT.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        row = json.loads(line)
        by_id[row["id"]] = row
    return by_id


def save_all(rows: list[dict]) -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n",
        encoding="utf-8",
    )


def ask_int(prompt: str, allowed: set[int]) -> int | None:
    """Return int in allowed, or None to skip. 'q' quits."""
    while True:
        raw = input(prompt).strip().lower()
        if raw in {"q", "quit", "exit"}:
            return None
        if raw in {"s", "skip"}:
            return -999  # signal skip keep existing
        try:
            v = int(raw)
        except ValueError:
            print(f"  enter one of {sorted(allowed)}, or s=skip, q=quit")
            continue
        if v in allowed:
            return v
        print(f"  enter one of {sorted(allowed)}, or s=skip, q=quit")


def main() -> None:
    if not FULL.exists():
        print(f"missing {FULL}")
        print("Run first: python labs/lab4/evaluate.py --full --save reports/lab4.json")
        sys.exit(1)

    all_rows = json.loads(FULL.read_text(encoding="utf-8"))
    sample = all_rows[:N]
    existing = load_existing()

    # merge: prefer already-labeled values from disk
    work = []
    for r in sample:
        prev = existing.get(r["id"], {})
        work.append({
            "id": r["id"],
            "kind": r.get("kind"),
            "question_hint": r.get("id"),  # id is enough; answer is below
            "answer": r.get("answer", ""),
            "refused": r.get("refused"),
            "machine_faithfulness": r.get("faithfulness"),
            "machine_correctness": r.get("correctness"),
            "human_faithfulness": prev.get("human_faithfulness"),
            "human_correctness": prev.get("human_correctness"),
        })

    done = sum(
        1 for r in work
        if r["human_faithfulness"] is not None and r["human_correctness"] is not None
    )
    print(f"Lab 4 calibration — {done}/{len(work)} already labeled")
    print(f"Autosave file: {OUT}")
    print("For each item:")
    print("  faithfulness: 1 = fully supported by context, 0 = any unsupported claim")
    print("  correctness:  2 = matches gold substance (or correct refuse),")
    print("                1 = partial, 0 = wrong / answered when should refuse")
    print("Commands: number to score | s = skip | q = quit & save\n")

    for i, r in enumerate(work):
        if r["human_faithfulness"] is not None and r["human_correctness"] is not None:
            continue

        print("=" * 72)
        print(f"[{i+1}/{len(work)}] id={r['id']}  kind={r.get('kind')}  refused={r.get('refused')}")
        print(f"machine: faithfulness={r.get('machine_faithfulness')}  correctness={r.get('machine_correctness')}")
        print("-" * 72)
        ans = r["answer"] or ""
        if len(ans) > 900:
            print(ans[:900] + "\n… [truncated for display]")
        else:
            print(ans)
        print("-" * 72)

        f = ask_int("  human_faithfulness (0/1): ", {0, 1})
        if f is None:
            save_all(work)
            print(f"saved → {OUT}  (quit)")
            return
        if f != -999:
            r["human_faithfulness"] = f

        c = ask_int("  human_correctness (0/1/2): ", {0, 1, 2})
        if c is None:
            save_all(work)
            print(f"saved → {OUT}  (quit)")
            return
        if c != -999:
            r["human_correctness"] = c

        save_all(work)
        print(f"  saved ({sum(1 for x in work if x['human_faithfulness'] is not None and x['human_correctness'] is not None)}/{len(work)})\n")

    save_all(work)
    labeled = sum(
        1 for r in work
        if r["human_faithfulness"] is not None and r["human_correctness"] is not None
    )
    print(f"Done. {labeled}/{len(work)} labeled → {OUT}")
    print("Next: python labs/lab4/evaluate.py --kappa")


if __name__ == "__main__":
    main()
