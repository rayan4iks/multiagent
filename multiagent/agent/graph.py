"""Граф мультиагентной системы на LangGraph.

START -> classify -> plan -> write_sql -> execute -> verify -+-> respond -> END
            |                   ^                            |
            |                   +------- retry (<=3) --------+
            +-> respond (отказ / не по теме)
write_sql -> respond, если модель решила, что данных нет (no_data)
"""
import json
import re
import time
import uuid
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph

from . import config, llm, memory, prompts, sandbox
from .config import Settings
from .sql_guard import (is_select_only, looks_malicious, unknown_tables,
                        is_shop_domain_question)


class AgentState(TypedDict, total=False):
    session_id: str
    question: str
    route: str               # answer | refuse | off_topic
    reason: str
    standalone_question: str
    plan: str
    examples: list
    action: str              # sql | no_data
    sql: str
    attempts: int
    feedback: str
    result: dict
    error: str
    error_kind: str          # no_sql | unsafe | schema | sql | infra
    verdict: str             # accept | retry | fail | no_data | refuse | error
    checks: list
    status: str              # answered | no_data | refused | off_topic | failed | error
    answer: str
    trace: list


def _trace(state, node, t0, **detail):
    tr = list(state.get("trace", []))
    tr.append({"node": node, "ms": int((time.time() - t0) * 1000), **detail})
    return tr


def _is_empty(rows):
    return not rows or all(all(c is None for c in r) for r in rows)


def _has_negative(rows):
    return any(isinstance(c, (int, float)) and c < 0 for r in rows for c in r)


def _fmt_rows(columns, rows, limit=10):
    lines = [" | ".join(columns)] + [" | ".join(str(c) for c in r) for r in rows[:limit]]
    if len(rows) > limit:
        lines.append(f"... и ещё {len(rows) - limit} строк")
    return "\n".join(lines)


def build_app(settings: Settings = None):
    S = settings or Settings()

    # ---------------------------------------------------------------- узлы
    def classify(state):
        t0 = time.time()
        q = state["question"]
        if looks_malicious(q):
            return {"route": "refuse", "reason": "запрос на изменение данных или обход правил",
                    "trace": _trace(state, "classify", t0, source="rules", route="refuse")}
        # Детерминированный маршрут для предметных вопросов. Это защищает
        # обычные запросы о товарах/заказах/выручке от ложного off_topic
        # у малой модели-классификатора.
        if is_shop_domain_question(q):
            return {"route": "answer", "reason": "обнаружены сущности предметной области магазина",
                    "trace": _trace(state, "classify", t0, source="domain_rules", route="answer")}
        obj, meta = llm.chat_json(S.small_model, prompts.CLASSIFY_SYSTEM, q, role="classify", num_predict=80)
        route = (obj or {}).get("route")
        if route not in ("answer", "refuse", "off_topic"):
            route = "answer"   # дальше всё равно стоят SQL-фильтр и песочница только для чтения
        return {"route": route, "reason": str((obj or {}).get("reason", "")),
                "trace": _trace(state, "classify", t0, source="llm", route=route, **meta)}

    def plan(state):
        t0 = time.time()
        q = state["question"]
        history = memory.last_turns(state["session_id"]) if S.use_memory else []
        examples = memory.search(q) if S.use_memory else []
        user = q
        if history:
            hist = "\n".join(f"Пользователь: {h[0]}\nСистема: {h[1]}" for h in history)
            user = f"История диалога:\n{hist}\n\nНовый вопрос: {q}"
        obj, meta = llm.chat_json(S.main_model, prompts.PLAN_SYSTEM, user, role="plan", num_predict=200)
        obj = obj or {}
        sq = obj.get("standalone_question")
        sq = sq if isinstance(sq, str) and 3 < len(sq) < 400 else q
        return {"standalone_question": sq, "plan": str(obj.get("plan", "")),
                "examples": examples, "attempts": 0, "checks": [],
                "trace": _trace(state, "plan", t0, memory_hits=len(examples), **meta)}

    def write_sql(state):
        t0 = time.time()
        parts = [f"Вопрос: {state['standalone_question']}"]
        if state.get("plan"):
            parts.append(f"План: {state['plan']}")
        if state.get("examples"):
            ex = "\n".join(f"Вопрос: {e[0]}\nSQL: {e[1]}" for e in state["examples"])
            parts.append(f"Похожие удачные запросы из памяти:\n{ex}")
        if state.get("feedback"):
            parts.append(f"Предыдущая попытка:\nSQL: {state.get('sql')}\n"
                         f"Проблема: {state['feedback']}\nИсправь запрос.")
        obj, meta = llm.chat_json(S.main_model, prompts.SQL_SYSTEM, "\n\n".join(parts),
                                  role="sql", num_predict=400)
        obj = obj or {}
        attempts = state.get("attempts", 0) + 1
        if obj.get("action") == "no_data":
            return {"action": "no_data", "sql": None, "attempts": attempts,
                    "reason": str(obj.get("reason", "")),
                    "trace": _trace(state, "write_sql", t0, attempt=attempts, action="no_data", **meta)}
        sql = obj.get("sql") if isinstance(obj.get("sql"), str) and obj["sql"].strip() else None
        return {"action": "sql", "sql": sql, "attempts": attempts,
                "trace": _trace(state, "write_sql", t0, attempt=attempts, sql=sql, **meta)}

    def execute(state):
        t0 = time.time()
        sql = state.get("sql")
        if not sql:
            out = {"result": None, "error": "модель не вернула SQL", "error_kind": "no_sql"}
        elif not is_select_only(sql):
            out = {"result": None, "error_kind": "unsafe",
                   "error": "разрешены только запросы SELECT"}
        elif unknown_tables(sql):
            out = {"result": None, "error_kind": "schema",
                   "error": f"таблицы {unknown_tables(sql)} нет в базе; доступны: "
                            "categories, customers, products, orders, order_items"}
        else:
            res = sandbox.run_sql(sql, S)
            if res.get("infra_error"):
                out = {"result": None, "error": res["error"], "error_kind": "infra"}
            elif not res["ok"]:
                out = {"result": None, "error": res["error"], "error_kind": "sql"}
            else:
                out = {"result": res, "error": "", "error_kind": ""}
        out["trace"] = _trace(state, "execute", t0, ok=not out["error"], error=out["error"] or None,
                              rows=len(out["result"]["rows"]) if out.get("result") else None)
        return out

    def verify(state):
        t0 = time.time()
        kind, attempts = state.get("error_kind"), state.get("attempts", 0)
        can_retry = attempts < S.max_attempts
        verdict, feedback, checks, meta = "accept", "", [], {}

        if kind == "unsafe":
            verdict, feedback = "refuse", state["error"]
        elif kind == "infra":
            verdict, feedback = "error", state["error"]
        elif kind in ("no_sql", "schema", "sql"):
            verdict, feedback = ("retry" if can_retry else "fail"), state["error"]
        else:
            res = state["result"]
            rows = res["rows"]
            checks.append("запрос только на чтение (SELECT), выполнен в песочнице")
            if _is_empty(rows):
                if attempts <= config.EMPTY_RETRIES and can_retry:
                    verdict = "retry"
                    feedback = ("запрос вернул пустой результат или NULL. Проверь фильтры и "
                                "соединения; если данных в базе действительно нет, верни action=no_data")
                else:
                    verdict = "no_data"
            elif _has_negative(rows):
                verdict = "retry" if can_retry else "fail"
                feedback = "в результате отрицательные значения, а в данных таких быть не может"
            else:
                checks.append("результат непустой, значения правдоподобны")
                if S.llm_verify:
                    user = (f"Вопрос: {state['standalone_question']}\nSQL: {state['sql']}\n"
                            f"Результат:\n{_fmt_rows(res['columns'], rows)}")
                    obj, meta = llm.chat_json(S.main_model, prompts.VERIFY_SYSTEM, user,
                                              role="verify", num_predict=120)
                    if (obj or {}).get("ok") is False:
                        reason = str((obj or {}).get("reason") or "запрос не соответствует вопросу")
                        sql_lower = (state.get("sql") or "").lower()
                        q_lower = state.get("standalone_question", "").lower()
                        reason_lower = reason.lower()
                        # Малые локальные модели иногда называют ошибкой сам
                        # корректный формат ответа: COUNT(*) для вопроса «сколько»,
                        # LIMIT 1 для топ-1 или явно написанный фильтр cancelled.
                        false_positive = False
                        if any(x in q_lower for x in ("сколько", "количество", "число")) and "count(" in sql_lower:
                            if any(x in reason_lower for x in ("счетчик", "счётчик", "count", "количеств", "просто число")):
                                false_positive = True
                        if "cancelled" in sql_lower and any(x in sql_lower for x in ("!=", "<>")):
                            if "cancelled" in reason_lower and any(x in reason_lower for x in ("не исключ", "не учиты", "не отфильтр", "не примен")):
                                false_positive = True
                        if "limit 1" in sql_lower and any(x in q_lower for x in ("больше всех", "наибольш", "самый", "топ-1", "топ 1")):
                            if any(x in reason_lower for x in ("только один", "одна строк", "не только", "не огранич")):
                                false_positive = True
                        if any(x in q_lower for x in ("названия", "имена", "выведи имя", "выведи назван")) and re.search(r"\bselect\b[\s\S]*\bname\b", sql_lower):
                            if (("некорректн" in reason_lower and "столб" in reason_lower) or "не те поля" in reason_lower):
                                false_positive = True
                        if false_positive:
                            checks.append("предупреждение LLM-верификатора проигнорировано: SQL явно содержит требуемую агрегацию/фильтр/лимит")
                        else:
                            verdict = "retry" if can_retry else "fail"
                            feedback = reason
                    else:
                        checks.append("семантическая проверка LLM: запрос соответствует вопросу")
        return {"verdict": verdict, "feedback": feedback,
                "checks": checks if verdict == "accept" else state.get("checks", []),
                "trace": _trace(state, "verify", t0, verdict=verdict, feedback=feedback or None, **meta)}

    def respond(state):
        t0 = time.time()
        route, verdict = state.get("route"), state.get("verdict")
        if route == "refuse":
            status = "refused"
        elif route == "off_topic":
            status = "off_topic"
        elif state.get("action") == "no_data" or verdict == "no_data":
            status = "no_data"
        elif verdict == "accept":
            status = "answered"
        elif verdict == "refuse":
            status = "refused"
        elif verdict == "error":
            status = "error"
        else:
            status = "failed"

        meta = {}
        if status == "refused":
            answer = ("Я не могу это выполнить: система работает только в режиме чтения и отвечает "
                      "на вопросы о данных, не изменяя их.")
        elif status == "off_topic":
            answer = "Я отвечаю только на вопросы о данных интернет-магазина."
        elif status == "no_data":
            answer = "В базе нет данных, чтобы ответить на этот вопрос."
            if state.get("reason") and state.get("action") == "no_data":
                answer += f" ({state['reason']})"
        elif status == "error":
            answer = f"Техническая ошибка: {state.get('error')}"
        elif status == "failed":
            answer = (f"Не удалось получить надёжный ответ (попыток SQL: {state.get('attempts', 0)}). "
                      f"Последняя проблема: {state.get('feedback') or state.get('error')}")
        else:
            res = state["result"]
            try:
                user = (f"Вопрос: {state['standalone_question']}\n"
                        f"Результат:\n{_fmt_rows(res['columns'], res['rows'], 20)}")
                answer, meta = llm.chat_text(S.small_model, prompts.RESPOND_SYSTEM, user, role="respond")
            except llm.LLMError:
                answer = ""
            if not answer.strip():   # запасной вариант без LLM
                answer = "Результат: " + "; ".join(", ".join(str(c) for c in r) for r in res["rows"][:20])

        if status == "answered" and S.use_memory:
            memory.remember(state["standalone_question"], state["sql"])
        if S.use_memory:
            memory.add_turn(state["session_id"], state["question"], answer)
        return {"status": status, "answer": answer, "trace": _trace(state, "respond", t0, status=status, **meta)}

    # ------------------------------------------------------------- рёбра
    def after_classify(state):
        return "plan" if state["route"] == "answer" else "respond"

    def after_write(state):
        return "respond" if state.get("action") == "no_data" else "execute"

    def after_verify(state):
        return "write_sql" if state["verdict"] == "retry" else "respond"

    g = StateGraph(AgentState)
    for name, fn in [("classify", classify), ("plan", plan), ("write_sql", write_sql),
                     ("execute", execute), ("verify", verify), ("respond", respond)]:
        g.add_node(name, fn)
    g.add_edge(START, "classify")
    g.add_conditional_edges("classify", after_classify, {"plan": "plan", "respond": "respond"})
    g.add_edge("plan", "write_sql")
    g.add_conditional_edges("write_sql", after_write, {"execute": "execute", "respond": "respond"})
    g.add_edge("execute", "verify")
    g.add_conditional_edges("verify", after_verify, {"write_sql": "write_sql", "respond": "respond"})
    g.add_edge("respond", END)
    return g.compile()


def run_question(app, question, session_id=None):
    """Прогоняет один вопрос через граф, пишет строку в logs/agent.jsonl и возвращает итоговое состояние."""
    t0 = time.time()
    state = app.invoke({"question": question, "session_id": session_id or uuid.uuid4().hex[:8],
                        "trace": [], "attempts": 0})
    state["total_ms"] = int((time.time() - t0) * 1000)
    try:
        config.LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with config.LOG_PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps({
                "ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "session": state["session_id"],
                "question": question, "status": state.get("status"), "sql": state.get("sql"),
                "attempts": state.get("attempts"), "total_ms": state["total_ms"],
                "trace": state.get("trace")}, ensure_ascii=False, default=str) + "\n")
    except OSError:
        pass
    return state
