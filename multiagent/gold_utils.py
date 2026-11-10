"""Помощники для сравнения результата SQL с эталоном из gold.json."""
import json
import sqlite3
from pathlib import Path

HERE = Path(__file__).parent


def load_gold():
    return json.loads((HERE / "gold.json").read_text(encoding="utf-8"))


def _norm_value(v):
    if isinstance(v, float):
        return round(v, 2)
    return v


def _norm_rows(rows):
    return [tuple(_norm_value(v) for v in r) for r in rows]


def results_match(expected, actual, order_matters=False):
    """Сравнивает эталон и результат запроса.

    - числа округляются до 2 знаков;
    - порядок строк учитывается только если order_matters=True;
    - если эталон - одна строка, а в результате есть лишние столбцы, достаточно
      чтобы значения эталона нашлись в строке (модель может добавить доп. поле).
    """
    exp, act = _norm_rows(expected), _norm_rows(actual)
    if not order_matters:
        exp, act = sorted(exp, key=repr), sorted(act, key=repr)
    if exp == act:
        return True
    if len(exp) == len(act) == 1 and set(exp[0]) <= set(act[0]):
        return True
    return False


def run_query(sql, db_path=HERE / "shop.db"):
    """Выполняет запрос в режиме только для чтения (для тестов вне песочницы)."""
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        return con.execute(sql).fetchall()
    finally:
        con.close()


if __name__ == "__main__":
    # самопроверка: эталонный SQL должен совпадать со своим же эталоном
    ok = 0
    for g in load_gold():
        if g["ref_sql"]:
            assert results_match(g["expected"], run_query(g["ref_sql"]), g["order"]), g["id"]
            ok += 1
    print(f"OK: {ok} эталонных запросов воспроизводятся")
