"""Запуск SQL в изолированной среде.

Режим docker (основной): одноразовый контейнер на каждый запрос, без сети, read-only файловая
система, все capabilities сброшены, лимиты памяти/CPU/процессов, БД смонтирована read-only.
Режим local (только для отладки без Docker): тот же runner.py в отдельном процессе.
"""
import json
import subprocess
import sys
import uuid

from . import config


def _parse(stdout, stderr, returncode):
    try:
        return json.loads(stdout.strip().splitlines()[-1])
    except Exception:  # noqa: BLE001
        err = (stderr or "").strip()[-300:] or f"пустой ответ песочницы (код {returncode})"
        return {"ok": False, "columns": [], "rows": [], "truncated": False,
                "error": err, "infra_error": True}


def _payload(sql, s):
    return json.dumps({"sql": sql, "max_rows": config.MAX_ROWS, "timeout_s": s.sql_timeout_s})


def run_sql(sql, settings):
    if settings.sandbox_mode == "local":
        return _run_local(sql, settings)
    return _run_docker(sql, settings)


def _run_local(sql, s):
    import os
    env = dict(os.environ, SANDBOX_DB=str(config.DB_PATH))
    try:
        p = subprocess.run([sys.executable, "-I", str(config.RUNNER_PATH)], input=_payload(sql, s),
                           capture_output=True, text=True, encoding="utf-8", errors="replace", env=env,
                           timeout=s.sql_timeout_s + 10)
    except subprocess.TimeoutExpired:
        return {"ok": False, "columns": [], "rows": [], "truncated": False,
                "error": "превышен лимит времени", "infra_error": False}
    return _parse(p.stdout, p.stderr, p.returncode)


def _run_docker(sql, s):
    name = f"sandbox-{uuid.uuid4().hex[:8]}"
    cmd = [
        "docker", "run", "--rm", "-i", "--name", name,
        "--network", "none",                       # нет сети
        "--read-only",                             # корневая ФС только для чтения
        "--tmpfs", "/tmp:size=16m,noexec,nosuid",  # единственное место для записи, в памяти
        "--cap-drop", "ALL",                       # никаких Linux capabilities
        "--security-opt", "no-new-privileges",     # запрет повышения привилегий
        "--user", "10001:10001",                   # не root
        "--memory", "256m", "--memory-swap", "256m",
        "--cpus", "0.5", "--pids-limit", "64",
        "--mount", f"type=bind,source={config.DB_PATH.resolve()},target=/data/shop.db,readonly",
        config.SANDBOX_IMAGE,
    ]
    try:
        p = subprocess.run(cmd, input=_payload(sql, s), capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=config.DOCKER_TIMEOUT_S)
    except FileNotFoundError:
        return {"ok": False, "columns": [], "rows": [], "truncated": False, "infra_error": True,
                "error": "Docker не найден. Установи/запусти Docker Desktop или используй SANDBOX_MODE=local."}
    except subprocess.TimeoutExpired:
        subprocess.run(["docker", "kill", name], capture_output=True)
        return {"ok": False, "columns": [], "rows": [], "truncated": False, "infra_error": False,
                "error": "песочница не уложилась во время и была остановлена"}
    res = _parse(p.stdout, p.stderr, p.returncode)
    if res.get("infra_error") and "Unable to find image" in (p.stderr or ""):
        res["error"] = ("Образ песочницы не найден. Выполни:  "
                        "docker build -t multiagent-sandbox:latest ./sandbox")
    return res
