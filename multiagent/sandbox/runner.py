"""Выполняет один SELECT в режиме «только чтение». Работает ВНУТРИ контейнера-песочницы.

Вход (stdin):  {"sql": "SELECT ...", "max_rows": 100, "timeout_s": 5}
Выход (stdout): {"ok": bool, "columns": [...], "rows": [[...]], "truncated": bool, "error": str|null}

Три независимых слоя защиты внутри процесса:
  1) база открыта как mode=ro & immutable=1 (запись невозможна);
  2) authorizer SQLite разрешает только чтение (SELECT/READ/FUNCTION/RECURSIVE);
  3) progress handler прерывает слишком долгие запросы.
"""
import json
import os
import sqlite3
import sys
import time

DB_PATH = os.environ.get("SANDBOX_DB", "/data/shop.db")

ALLOWED = {
    sqlite3.SQLITE_SELECT, sqlite3.SQLITE_READ,
    sqlite3.SQLITE_FUNCTION, sqlite3.SQLITE_RECURSIVE,
}


def authorizer(action, arg1, arg2, db_name, trigger):
    return sqlite3.SQLITE_OK if action in ALLOWED else sqlite3.SQLITE_DENY


def main():
    req = json.loads(sys.stdin.buffer.read().decode("utf-8"))   # не зависим от кодировки консоли
    sql = req.get("sql", "")
    max_rows = int(req.get("max_rows", 100))
    timeout_s = float(req.get("timeout_s", 5))
    out = {"ok": False, "columns": [], "rows": [], "truncated": False, "error": None}
    try:
        uri = "file:" + DB_PATH.replace("\\", "/") + "?mode=ro&immutable=1"
        con = sqlite3.connect(uri, uri=True)
        con.set_authorizer(authorizer)
        deadline = time.time() + timeout_s
        con.set_progress_handler(lambda: 1 if time.time() > deadline else 0, 10000)
        cur = con.execute(sql)
        rows = cur.fetchmany(max_rows + 1)
        out["columns"] = [d[0] for d in (cur.description or [])]
        out["truncated"] = len(rows) > max_rows
        out["rows"] = [list(r) for r in rows[:max_rows]]
        out["ok"] = True
        con.close()
    except Exception as e:  # noqa: BLE001
        msg = str(e)
        if "interrupted" in msg.lower():
            msg = f"превышен лимит времени выполнения ({timeout_s:g} с)"
        out["error"] = f"{type(e).__name__}: {msg}"
    print(json.dumps(out, ensure_ascii=True, default=str))   # только ASCII: безопасно для любой кодировки


if __name__ == "__main__":
    main()
