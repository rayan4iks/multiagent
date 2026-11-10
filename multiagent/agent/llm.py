"""Минимальный клиент Ollama (без внешних зависимостей)."""
import json
import re
import urllib.error
import urllib.request

from . import config


class LLMError(RuntimeError):
    """Ollama недоступна или вернула ошибку."""


THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL)
FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


def _post(path, payload):
    host = config.OLLAMA_HOST
    base = host if host.startswith("http") else f"http://{host}"
    req = urllib.request.Request(
        base + path, data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=config.LLM_TIMEOUT_S) as r:
        return json.loads(r.read().decode("utf-8"))


def _chat(model, system, user, fmt, num_predict):
    payload = {
        "model": model,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        "stream": False,
        "think": False,
        "keep_alive": "10m",
        "options": {"temperature": 0, "seed": 0, "num_ctx": config.NUM_CTX, "num_predict": num_predict},
    }
    if fmt:
        payload["format"] = fmt
    try:
        try:
            data = _post("/api/chat", payload)
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", "ignore")
            if e.code == 400 and "think" in body.lower():
                payload.pop("think")
                data = _post("/api/chat", payload)
            else:
                raise LLMError(f"Ollama вернула ошибку {e.code}: {body[:200]}")
    except urllib.error.URLError as e:
        raise LLMError(f"Ollama не отвечает ({config.OLLAMA_HOST}): {e.reason}. "
                       "Запущено ли приложение Ollama и скачана ли модель?")
    text = THINK_RE.sub("", data.get("message", {}).get("content", "")).strip()
    meta = {"model": model, "tokens": data.get("eval_count", 0),
            "llm_ms": int((data.get("total_duration") or 0) / 1e6)}
    return text, meta


def extract_json(text):
    try:
        obj = json.loads(text)
        return obj if isinstance(obj, dict) else None
    except json.JSONDecodeError:
        pass
    cands = []
    m = FENCE_RE.search(text)
    if m:
        cands.append(m.group(1).strip())
    s, e = text.find("{"), text.rfind("}")
    if s != -1 and e > s:
        cands.append(text[s:e + 1])
    for c in cands:
        try:
            obj = json.loads(c)
            if isinstance(obj, dict):
                return obj
        except json.JSONDecodeError:
            continue
    return None


def chat_json(model, system, user, role="", num_predict=300):
    """Возвращает (dict | None, meta). role нужен для трассировки и тестов."""
    text, meta = _chat(model, system, user, "json", num_predict)
    return extract_json(text), meta


def chat_text(model, system, user, role="", num_predict=250):
    """Возвращает (str, meta)."""
    return _chat(model, system, user, None, num_predict)
