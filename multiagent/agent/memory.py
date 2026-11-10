"""Память агента.

- Кратковременная: последние реплики сессии (таблица turns), нужны для уточнений («а за апрель?»).
- Эпизодическая: подтверждённые верификатором пары «вопрос -> SQL» (таблица episodes);
  похожие примеры подмешиваются в промпт SQL-агента.
Поиск похожих вопросов сейчас лексический (пересечение слов). Это осознанное упрощение:
интерфейс search() можно заменить на эмбеддинги/Chroma, не трогая остальной код.
"""
import re
import sqlite3
import time

from . import config


def _con():
    config.MEMORY_DB.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(config.MEMORY_DB)
    con.executescript("""
        CREATE TABLE IF NOT EXISTS turns (
            id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT, question TEXT, answer TEXT, ts REAL);
        CREATE TABLE IF NOT EXISTS episodes (
            id INTEGER PRIMARY KEY AUTOINCREMENT, question TEXT UNIQUE, sql TEXT,
            uses INTEGER DEFAULT 1, ts REAL);
    """)
    return con


def _tokens(text):
    words = re.findall(r"\w+", (text or "").lower())
    return {w[:5] for w in words if len(w) >= 3}


def add_turn(session_id, question, answer):
    with _con() as con:
        con.execute("INSERT INTO turns (session_id, question, answer, ts) VALUES (?,?,?,?)",
                    (session_id, question, answer, time.time()))


def last_turns(session_id, n=3):
    with _con() as con:
        rows = con.execute(
            "SELECT question, answer FROM turns WHERE session_id=? ORDER BY id DESC LIMIT ?",
            (session_id, n)).fetchall()
    return list(reversed(rows))


def remember(question, sql):
    with _con() as con:
        con.execute(
            """INSERT INTO episodes (question, sql, ts) VALUES (?,?,?)
               ON CONFLICT(question) DO UPDATE SET sql=excluded.sql, uses=uses+1, ts=excluded.ts""",
            (question, sql, time.time()))


def search(question, k=2, min_score=0.5):
    """Похожие прошлые удачные запросы: [(question, sql, score)]."""
    q = _tokens(question)
    if not q:
        return []
    with _con() as con:
        rows = con.execute("SELECT question, sql FROM episodes").fetchall()
    scored = []
    for old_q, sql in rows:
        t = _tokens(old_q)
        score = len(q & t) / len(q | t) if t else 0
        if score >= min_score:
            scored.append((old_q, sql, round(score, 2)))
    return sorted(scored, key=lambda x: -x[2])[:k]
