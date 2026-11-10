"""Оценка всей агентной системы (а не отдельной модели) на gold.json.

    python eval_agent.py                      # все 30 вопросов
    python eval_agent.py --limit 5            # быстрый пробный прогон
    python eval_agent.py --only S01 J01 N01 M01
    python eval_agent.py --main qwen3:4b --small qwen3:1.7b
    python eval_agent.py --no-llm-verify      # без семантической проверки (для сравнения)

Метрики: доля верных итоговых ответов (task success), корректные отказы/«нет данных»,
число попыток и шагов, задержка, сколько ответов верификатор отправил на доработку.
Память отключена, чтобы удачные ответы не «подсказывали» следующим вопросам.
"""
import argparse
import json
import sys
import time
from collections import defaultdict
from pathlib import Path

from agent import llm
from agent.config import Settings
from agent.graph import build_app, run_question
from gold_utils import load_gold, results_match

OUT_DIR = Path(__file__).parent / "results_agent"


def grade(g, state):
    status = state.get("status")
    if g["behavior"] == "answer":
        rows = (state.get("result") or {}).get("rows")
        return status == "answered" and rows is not None and \
            results_match(g["expected"], rows, g["order"])
    if g["behavior"] == "no_data":
        return status == "no_data"
    return status == "refused"


def pct(n, d):
    return f"{100 * n / d:.1f}%" if d else "n/a"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int)
    ap.add_argument("--only", nargs="+")
    ap.add_argument("--small"); ap.add_argument("--main")
    ap.add_argument("--sandbox", choices=["docker", "local"])
    ap.add_argument("--no-llm-verify", action="store_true")
    ap.add_argument("--tag", default="run", help="имя прогона для файлов результатов")
    args = ap.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    s = Settings(use_memory=False)
    if args.small: s.small_model = args.small
    if args.main: s.main_model = args.main
    if args.sandbox: s.sandbox_mode = args.sandbox
    if args.no_llm_verify: s.llm_verify = False

    gold = load_gold()
    if args.only: gold = [g for g in gold if g["id"] in set(args.only)]
    if args.limit: gold = gold[:args.limit]

    app = build_app(s)
    OUT_DIR.mkdir(exist_ok=True)
    out_path = OUT_DIR / f"{args.tag}.jsonl"
    out_path.write_text("", encoding="utf-8")
    print(f"Система: малая={s.small_model}, основная={s.main_model}, песочница={s.sandbox_mode}, "
          f"LLM-верификация={s.llm_verify}; вопросов: {len(gold)}")

    recs = []
    for i, g in enumerate(gold, 1):
        try:
            st = run_question(app, g["question"])
        except llm.LLMError as e:
            sys.exit(f"Ошибка LLM: {e}")
        ok = grade(g, st)
        retries = sum(1 for t in st["trace"] if t["node"] == "verify" and t.get("verdict") == "retry")
        rec = {"id": g["id"], "category": g["category"], "behavior": g["behavior"], "correct": ok,
               "status": st.get("status"), "attempts": st.get("attempts"), "retries": retries,
               "steps": len(st["trace"]), "total_s": round(st["total_ms"] / 1000, 1),
               "sql": st.get("sql"), "answer": st.get("answer")}
        recs.append(rec)
        with out_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        print(f"[{i:>2}/{len(gold)}] {'OK ' if ok else '-- '}{g['id']} status={rec['status']} "
              f"попыток={rec['attempts']} {rec['total_s']} с")

    by_cat = defaultdict(list)
    for r in recs: by_cat[r["category"]].append(r)
    ans = [r for r in recs if r["category"] in ("simple", "joins", "dates")]
    lines = [
        f"| Показатель | Значение |", "|---|---|",
        f"| Task success (все вопросы) | {pct(sum(r['correct'] for r in recs), len(recs))} |",
        f"| Верные ответы на вопросы по данным | {pct(sum(r['correct'] for r in ans), len(ans))} |",
    ]
    for c in ("simple", "joins", "dates", "no_data", "malicious"):
        if c in by_cat:
            lines.append(f"| {c} | {pct(sum(r['correct'] for r in by_cat[c]), len(by_cat[c]))} |")
    n = len(recs)
    lines += [
        f"| Среднее число попыток SQL | {sum(r['attempts'] or 0 for r in recs) / n:.2f} |",
        f"| Вопросов, где верификатор требовал доработку | {sum(r['retries'] > 0 for r in recs)} из {n} |",
        f"| Средняя задержка, с | {sum(r['total_s'] for r in recs) / n:.1f} |",
        f"| Максимальная задержка, с | {max(r['total_s'] for r in recs):.1f} |",
    ]
    md = "\n".join(lines)
    (OUT_DIR / f"{args.tag}_summary.md").write_text(md + "\n", encoding="utf-8")
    print("\n" + md)
    print(f"\nПодробности: {out_path}")


if __name__ == "__main__":
    main()
