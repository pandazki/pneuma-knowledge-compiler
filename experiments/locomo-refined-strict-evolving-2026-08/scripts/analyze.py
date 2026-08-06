#!/usr/bin/env python3
"""Phase C: aggregate the official scored file into the report's tables.

Run only after 03-score.sh has landed. Produces:
  - the dual score (official full-set / burned-questions removed)
  - per-conversation and per-category breakdowns
  - a multimodal split
  - a sample of wrong answers

    python3 analyze.py [--sample N]
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path("/data/qiwei/lcr-final")
SCORED = ROOT / "data/outputs/predictions_scored.jsonl"
BURNED = {"conv-26#q0000", "conv-26#q0001"}
CATEGORY_NAMES = {"1": "1", "2": "2", "3": "3", "4": "4"}


def load() -> list[dict]:
    return [json.loads(line) for line in SCORED.read_text(encoding="utf-8").splitlines() if line.strip()]


def mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def table(rows: dict[str, list[dict]], label: str) -> str:
    out = [f"\n### 按{label}", "", "| " + label + " | 题数 | LLM judge | F1 | BLEU |", "|---|---:|---:|---:|---:|"]
    for key in sorted(rows, key=lambda k: (len(k), k)):
        items = rows[key]
        out.append(
            f"| {key} | {len(items)} | "
            f"{mean([float(r.get('llm_score') or 0) for r in items]) * 100:.2f}% | "
            f"{mean([float(r.get('f1_score') or 0) for r in items]):.4f} | "
            f"{mean([float(r.get('bleu_score') or 0) for r in items]):.4f} |"
        )
    return "\n".join(out)


def main() -> int:
    sample_n = 5
    if "--sample" in sys.argv:
        sample_n = int(sys.argv[sys.argv.index("--sample") + 1])
    if not SCORED.exists():
        print(f"error: {SCORED} not found — run 03-score.sh first", file=sys.stderr)
        return 1
    records = load()
    kept = [r for r in records if r.get("qa_id") not in BURNED]

    print(f"# 分数聚合\n")
    print(f"- 官方全量口径：{len(records)} 题，LLM judge **{mean([float(r.get('llm_score') or 0) for r in records]) * 100:.2f}%**"
          f"，F1 {mean([float(r.get('f1_score') or 0) for r in records]):.4f}"
          f"，BLEU {mean([float(r.get('bleu_score') or 0) for r in records]):.4f}")
    print(f"- 剔除烧题（{len(BURNED)} 题）：{len(kept)} 题，LLM judge **{mean([float(r.get('llm_score') or 0) for r in kept]) * 100:.2f}%**"
          f"，F1 {mean([float(r.get('f1_score') or 0) for r in kept]):.4f}"
          f"，BLEU {mean([float(r.get('bleu_score') or 0) for r in kept]):.4f}")
    delta = (mean([float(r.get('llm_score') or 0) for r in kept]) - mean([float(r.get('llm_score') or 0) for r in records])) * 100
    print(f"- 差值：{delta:+.4f} 个百分点")
    print(f"- 烧题两道各自的判分：" + ", ".join(
        f"{r['qa_id']}={float(r.get('llm_score') or 0):.0f}" for r in records if r.get("qa_id") in BURNED))

    by_conv: dict[str, list[dict]] = defaultdict(list)
    by_cat: dict[str, list[dict]] = defaultdict(list)
    by_mm: dict[str, list[dict]] = defaultdict(list)
    for r in records:
        by_conv[str(r.get("sample_id"))].append(r)
        by_cat[str(r.get("category"))].append(r)
        by_mm["多模态" if r.get("is_multi_modality") else "纯文本"].append(r)
    print(table(by_conv, "conversation"))
    print(table(by_cat, "category"))
    print(table(by_mm, "模态"))

    empties = [r for r in records if not str(r.get("response") or "").strip()]
    no_record = [r for r in records
                 if "no relevant record" in str(r.get("response") or "").lower()]
    print(f"\n- 空答案：{len(empties)} 题；答成「no relevant record」：{len(no_record)} 题"
          f"（其中判对 {sum(1 for r in no_record if float(r.get('llm_score') or 0) == 1)} 题）")

    wrong = [r for r in records if float(r.get("llm_score") or 0) == 0.0]
    print(f"\n### 错题抽样（共 {len(wrong)} 题判错，等距抽 {sample_n} 道）\n")
    step = max(1, len(wrong) // sample_n)
    for r in wrong[::step][:sample_n]:
        print(f"**{r.get('qa_id')}**（category {r.get('category')}"
              f"{'，多模态' if r.get('is_multi_modality') else ''}）")
        print(f"- 题：{r.get('question')}")
        print(f"- 金标：{r.get('answer')}")
        print(f"- 作答：{r.get('response')}")
        print(f"- F1 {float(r.get('f1_score') or 0):.3f} / BLEU {float(r.get('bleu_score') or 0):.3f}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
