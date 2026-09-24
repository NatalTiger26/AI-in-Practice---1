#!/usr/bin/env python3
"""Compact Lab 4 calibration (autosave). Open listed corpus files in another pane.

    python labs/lab4/calibrate_interactive.py
    python labs/lab4/evaluate.py --kappa   # when all 20 done
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FULL = ROOT / "reports" / "lab4.json"
GOLDEN = ROOT / "data" / "eval" / "rag_golden.jsonl"
OUT = ROOT / "labs" / "lab4" / "calibration_labels.jsonl"
N = 20


def load_golden() -> dict[str, dict]:
    return {r["id"]: r for r in (json.loads(l) for l in GOLDEN.open(encoding="utf-8"))}


def load_existing() -> dict[str, dict]:
    if not OUT.exists():
        return {}
    out = {}
    for line in OUT.read_text(encoding="utf-8").splitlines():
        if line.strip():
            r = json.loads(line)
            out[r["id"]] = r
    return out


def save_all(rows: list[dict]) -> None:
    OUT.write_text(
        "\n".join(json.dumps({
            "id": r["id"],
            "answer": r.get("answer", ""),
            "human_faithfulness": r.get("human_faithfulness"),
            "human_correctness": r.get("human_correctness"),
        }, ensure_ascii=False) for r in rows) + "\n",
        encoding="utf-8",
    )


def ask(prompt: str, allowed: set[int]) -> int | None:
    while True:
        raw = input(prompt).strip().lower()
        if raw in {"q", "quit"}:
            return None
        if raw in {"s", "skip"}:
            return -999
        try:
            v = int(raw)
            if v in allowed:
                return v
        except ValueError:
            pass
        print(f"  use {sorted(allowed)} | s=skip | q=quit")


def main() -> None:
    if not FULL.exists():
        print(f"Need {FULL} — run evaluate.py --full --save first")
        sys.exit(1)

    golden = load_golden()
    existing = load_existing()
    rows_in = json.loads(FULL.read_text(encoding="utf-8"))[:N]

    work = []
    for r in rows_in:
        g = golden.get(r["id"], {})
        prev = existing.get(r["id"], {})
        work.append({
            "id": r["id"],
            "kind": r.get("kind"),
            "unanswerable": r.get("unanswerable"),
            "refused": r.get("refused"),
            "answer": r.get("answer", ""),
            "retrieved": r.get("retrieved") or [],
            "question": g.get("question", ""),
            "gold_answer": g.get("gold_answer", ""),
            "human_faithfulness": prev.get("human_faithfulness"),
            "human_correctness": prev.get("human_correctness"),
        })

    done = sum(1 for r in work if r["human_faithfulness"] is not None and r["human_correctness"] is not None)
    print(f"Calibration {done}/{len(work)} done → {OUT.name}")
    print("faith: 1=supported by sources / honest refuse; 0=any unsupported claim")
    print("corr:  2=matches gold (or both refuse); 1=partial; 0=wrong/mismatched refuse")
    print("Open files under data/corpus/<id>.md for the listed source ids.\n")

    for i, r in enumerate(work):
        if r["human_faithfulness"] is not None and r["human_correctness"] is not None:
            continue

        cites = sorted({int(m) for m in __import__("re").findall(r"\[(\d+)\]", r["answer"] or "")})
        paths = [f"data/corpus/{d}.md" for d in r["retrieved"]]

        print("=" * 60)
        print(f"[{i+1}/{len(work)}] {r['id']}  kind={r['kind']}  refused={r['refused']}")
        print(f"Q: {r['question']}")
        print(f"GOLD: {r['gold_answer']}")
        print(f"OPEN: {', '.join(paths) if paths else '(none)'}")
        print(f"CITES in answer: {cites}  → [1]=1st OPEN file, [2]=2nd, …")
        print(f"ANSWER: {r['answer']}")
        print("-" * 60)

        f = ask("faithfulness 0/1: ", {0, 1})
        if f is None:
            save_all(work)
            print("saved, quit")
            return
        if f != -999:
            r["human_faithfulness"] = f

        c = ask("correctness 0/1/2: ", {0, 1, 2})
        if c is None:
            save_all(work)
            print("saved, quit")
            return
        if c != -999:
            r["human_correctness"] = c

        save_all(work)
        n = sum(1 for x in work if x["human_faithfulness"] is not None and x["human_correctness"] is not None)
        print(f"saved ({n}/{len(work)})\n")

    save_all(work)
    print(f"Done → {OUT}")
    print("Next: python labs/lab4/evaluate.py --kappa")


if __name__ == "__main__":
    main()
