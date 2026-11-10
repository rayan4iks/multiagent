"""Запуск агента из командной строки.

    python run_agent.py "Какие 3 товара принесли наибольшую выручку?"
    python run_agent.py                       # интерактивный режим с памятью диалога
    python run_agent.py -v "вопрос"           # + трассировка шагов
    python run_agent.py --sandbox local "вопрос"   # без Docker (только для отладки)
"""
import argparse
import sys
import uuid

from agent import llm
from agent.config import Settings
from agent.graph import build_app, run_question


def show(state, verbose):
    print(f"\nОтвет: {state['answer']}")
    if state.get("status") == "answered":
        print(f"\nSQL: {state['sql']}")
        for c in state.get("checks", []):
            print(f"  ✓ {c}")
        res = state.get("result") or {}
        if res.get("truncated"):
            print("  ! результат усечён до 100 строк")
    print(f"\n[статус: {state.get('status')}, попыток SQL: {state.get('attempts')}, "
          f"время: {state['total_ms'] / 1000:.1f} с]")
    if verbose:
        print("\nТрассировка:")
        for t in state["trace"]:
            extra = {k: v for k, v in t.items() if k not in ("node", "ms")}
            print(f"  {t['node']:<10} {t['ms']:>6} мс  {extra}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("question", nargs="?")
    ap.add_argument("-v", "--verbose", action="store_true")
    ap.add_argument("--small", help="малая модель (оркестратор, ответчик)")
    ap.add_argument("--main", help="основная модель (планировщик, SQL, верификатор)")
    ap.add_argument("--sandbox", choices=["docker", "local"])
    ap.add_argument("--no-llm-verify", action="store_true", help="отключить семантическую проверку LLM")
    ap.add_argument("--no-memory", action="store_true")
    args = ap.parse_args()

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    s = Settings()
    if args.small: s.small_model = args.small
    if args.main: s.main_model = args.main
    if args.sandbox: s.sandbox_mode = args.sandbox
    if args.no_llm_verify: s.llm_verify = False
    if args.no_memory: s.use_memory = False
    app = build_app(s)
    session = uuid.uuid4().hex[:8]

    try:
        if args.question:
            show(run_question(app, args.question, session), args.verbose)
            return
        print(f"Аналитик данных (малая: {s.small_model}, основная: {s.main_model}, "
              f"песочница: {s.sandbox_mode}). Пустая строка или Ctrl+C для выхода.")
        while True:
            q = input("\nВопрос> ").strip()
            if not q:
                break
            show(run_question(app, q, session), args.verbose)
    except llm.LLMError as e:
        sys.exit(f"\nОшибка LLM: {e}")
    except (KeyboardInterrupt, EOFError):
        print()


if __name__ == "__main__":
    main()
