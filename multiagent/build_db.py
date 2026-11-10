"""Создаёт учебную базу интернет-магазина (shop.db) и эталонные ответы (gold.json).

Запуск:  python build_db.py
Данные детерминированы (фиксированный seed), поэтому у всех получится одна и та же база.
"""
import json
import random
import sqlite3
from datetime import date, timedelta
from pathlib import Path

from questions import QUESTIONS

HERE = Path(__file__).parent
DB_PATH = HERE / "shop.db"
GOLD_PATH = HERE / "gold.json"

SCHEMA = """
CREATE TABLE categories (
    category_id INTEGER PRIMARY KEY,
    name        TEXT NOT NULL
);
CREATE TABLE customers (
    customer_id   INTEGER PRIMARY KEY,
    name          TEXT NOT NULL,
    city          TEXT NOT NULL,
    registered_at TEXT NOT NULL            -- YYYY-MM-DD
);
CREATE TABLE products (
    product_id  INTEGER PRIMARY KEY,
    name        TEXT NOT NULL,
    category_id INTEGER NOT NULL REFERENCES categories(category_id),
    price       REAL NOT NULL,
    stock       INTEGER NOT NULL           -- остаток на складе
);
CREATE TABLE orders (
    order_id    INTEGER PRIMARY KEY,
    customer_id INTEGER NOT NULL REFERENCES customers(customer_id),
    order_date  TEXT NOT NULL,             -- YYYY-MM-DD
    status      TEXT NOT NULL              -- delivered | shipped | pending | cancelled
);
CREATE TABLE order_items (
    item_id    INTEGER PRIMARY KEY,
    order_id   INTEGER NOT NULL REFERENCES orders(order_id),
    product_id INTEGER NOT NULL REFERENCES products(product_id),
    quantity   INTEGER NOT NULL,
    unit_price REAL NOT NULL
);
"""

CATEGORIES = ["Ноутбуки и ПК", "Смартфоны и планшеты", "Аксессуары", "Аудио", "Умный дом"]

# (название, id категории, цена)
PRODUCTS = [
    ("Ноутбук Pro 15", 1, 89990), ("Ноутбук Air 13", 1, 74990),
    ("Моноблок Office 24", 1, 64990), ("Игровой ПК Titan", 1, 129990),
    ("Смартфон Nova X", 2, 54990), ("Смартфон Lite 5", 2, 19990),
    ("Планшет Tab 10", 2, 32990), ("Смартфон Ultra Z", 2, 99990),
    ("Чехол для Nova X", 3, 1290), ("Зарядка быстрая 65W", 3, 2490),
    ("Кабель USB-C 2м", 3, 590), ("Мышь беспроводная", 3, 1990),
    ("Клавиатура механическая", 3, 5490), ("Рюкзак для ноутбука", 3, 3290),
    ("Наушники Pro ANC", 4, 12990), ("Наушники Sport", 4, 4990),
    ("Колонка Mini", 4, 3990), ("Саундбар Home", 4, 15990), ("Микрофон USB", 4, 6490),
    ("Умная лампа", 5, 1490), ("Умная розетка", 5, 1190),
    ("Камера видеонаблюдения", 5, 4590), ("Датчик движения", 5, 1690),
    ("Робот-пылесос Clean", 5, 27990),
]
NEVER_ORDERED = {"Моноблок Office 24", "Саундбар Home"}
OUT_OF_STOCK = {"Игровой ПК Titan", "Смартфон Ultra Z", "Датчик движения"}

FIRST_NAMES = [
    ("Анна", "f"), ("Иван", "m"), ("Мария", "f"), ("Дмитрий", "m"), ("Елена", "f"),
    ("Алексей", "m"), ("Ольга", "f"), ("Сергей", "m"), ("Наталья", "f"), ("Андрей", "m"),
    ("Татьяна", "f"), ("Павел", "m"), ("Юлия", "f"), ("Михаил", "m"), ("Екатерина", "f"),
    ("Николай", "m"), ("Светлана", "f"), ("Артём", "m"), ("Ирина", "f"), ("Владимир", "m"),
]
LAST_NAMES = ["Иванов", "Петров", "Смирнов", "Кузнецов", "Попов",
              "Васильев", "Соколов", "Михайлов", "Новиков", "Фёдоров"]
CITIES = ["Москва", "Санкт-Петербург", "Казань", "Новосибирск", "Екатеринбург"]
CITY_WEIGHTS = [14, 9, 6, 6, 5]
STATUSES = ["delivered", "shipped", "pending", "cancelled"]
STATUS_WEIGHTS = [70, 10, 8, 12]

N_CUSTOMERS = 40
N_NEVER_ORDERED_CUSTOMERS = 5
N_ORDERS = 320


def rand_date(rng, start, end):
    return start + timedelta(days=rng.randint(0, (end - start).days))


def build():
    rng = random.Random(42)
    if DB_PATH.exists():
        DB_PATH.unlink()
    con = sqlite3.connect(DB_PATH)
    con.executescript(SCHEMA)

    con.executemany("INSERT INTO categories VALUES (?, ?)", list(enumerate(CATEGORIES, 1)))

    # товары
    for pid, (name, cat, price) in enumerate(PRODUCTS, 1):
        stock = 0 if name in OUT_OF_STOCK else rng.randint(3, 80)
        con.execute("INSERT INTO products VALUES (?, ?, ?, ?, ?)", (pid, name, cat, price, stock))

    # клиенты
    customers = []
    for i in range(N_CUSTOMERS):
        first, gender = FIRST_NAMES[i % 20]
        last = LAST_NAMES[(i * 7 + (i // 20) * 3) % 10]
        name = f"{first} {last}{'а' if gender == 'f' else ''}"
        city = rng.choices(CITIES, CITY_WEIGHTS)[0]
        reg = rand_date(rng, date(2023, 1, 1), date(2025, 6, 30))
        customers.append((i + 1, name, city, reg.isoformat()))
    assert len({c[1] for c in customers}) == N_CUSTOMERS, "имена клиентов должны быть уникальны"
    con.executemany("INSERT INTO customers VALUES (?, ?, ?, ?)", customers)

    # заказы
    orderable_customers = customers[: N_CUSTOMERS - N_NEVER_ORDERED_CUSTOMERS]
    orderable_products = [
        (pid, price, name) for pid, (name, _c, price) in enumerate(PRODUCTS, 1)
        if name not in NEVER_ORDERED
    ]
    # дешёвые товары берут чаще, дорогие реже
    weights = [2 + 40000 / price for _pid, price, _n in orderable_products]

    item_id = 1
    orders = []
    for oid in range(1, N_ORDERS + 1):
        cust = rng.choice(orderable_customers)
        start = max(date.fromisoformat(cust[3]), date(2025, 1, 1))
        odate = rand_date(rng, start, date(2025, 12, 31))
        status = rng.choices(STATUSES, STATUS_WEIGHTS)[0]
        orders.append((oid, cust[0], odate.isoformat(), status))
    orders.sort(key=lambda o: o[2])
    orders = [(i + 1, o[1], o[2], o[3]) for i, o in enumerate(orders)]
    con.executemany("INSERT INTO orders VALUES (?, ?, ?, ?)", orders)

    for oid, *_ in orders:
        n_items = rng.choices([1, 2, 3, 4], [45, 30, 18, 7])[0]
        chosen = set()
        while len(chosen) < n_items:
            chosen.add(rng.choices(range(len(orderable_products)), weights)[0])
        for idx in sorted(chosen):
            pid, price, _name = orderable_products[idx]
            qty = 1 if price > 20000 else rng.randint(1, 3)
            con.execute("INSERT INTO order_items VALUES (?, ?, ?, ?, ?)",
                        (item_id, oid, pid, qty, price))
            item_id += 1
    con.commit()
    return con


def run_gold(con):
    gold = []
    for q in QUESTIONS:
        entry = {k: q[k] for k in ("id", "category", "question", "behavior", "ref_sql", "order")}
        if q["ref_sql"]:
            rows = con.execute(q["ref_sql"]).fetchall()
            entry["expected"] = [list(r) for r in rows]
        else:
            entry["expected"] = None
        gold.append(entry)
    GOLD_PATH.write_text(json.dumps(gold, ensure_ascii=False, indent=2), encoding="utf-8")
    return gold


def sanity_checks(con, gold):
    """Проверяем, что ответы однозначны (нет ничьих в топ-N) и вопросы осмысленны."""
    by_id = {g["id"]: g for g in gold}
    problems = []

    def top_gap(sql_body, label, n):
        rows = con.execute(sql_body).fetchall()
        if len(rows) > n and rows[n - 1][-1] == rows[n][-1]:
            problems.append(f"{label}: ничья на границе топ-{n}")

    top_gap("""SELECT p.name, ROUND(SUM(oi.quantity*oi.unit_price),2) r FROM order_items oi
               JOIN orders o ON o.order_id=oi.order_id JOIN products p ON p.product_id=oi.product_id
               WHERE o.status!='cancelled' GROUP BY p.product_id ORDER BY r DESC""", "J01", 3)
    top_gap("""SELECT c.name, ROUND(SUM(oi.quantity*oi.unit_price),2) r FROM order_items oi
               JOIN orders o ON o.order_id=oi.order_id JOIN products p ON p.product_id=oi.product_id
               JOIN categories c ON c.category_id=p.category_id
               WHERE o.status!='cancelled' GROUP BY c.category_id ORDER BY r DESC""", "J02", 1)
    top_gap("""SELECT c.city, ROUND(SUM(oi.quantity*oi.unit_price),2) r FROM order_items oi
               JOIN orders o ON o.order_id=oi.order_id JOIN customers c ON c.customer_id=o.customer_id
               WHERE o.status!='cancelled' GROUP BY c.city ORDER BY r DESC""", "J05", 1)
    top_gap("""SELECT c.name, ROUND(SUM(oi.quantity*oi.unit_price),2) r FROM order_items oi
               JOIN orders o ON o.order_id=oi.order_id JOIN customers c ON c.customer_id=o.customer_id
               WHERE o.status!='cancelled' GROUP BY c.customer_id ORDER BY r DESC""", "J07", 1)
    top_gap("""SELECT strftime('%Y-%m',order_date) m, COUNT(*) c FROM orders
               WHERE strftime('%Y',order_date)='2025' GROUP BY m ORDER BY c DESC""", "D04", 1)

    top_gap("SELECT name, price FROM products ORDER BY price DESC", "S03", 1)

    for qid in ("J03", "J06", "D01", "D05", "S06"):
        v = by_id[qid]["expected"]
        if not v or v[0][0] in (0, None):
            problems.append(f"{qid}: эталон пустой или нулевой")
    for qid in ("S07", "J04", "J08"):
        if not by_id[qid]["expected"]:
            problems.append(f"{qid}: эталонный список пуст")
    if by_id["N01"]["expected"] != [[None]]:
        problems.append("N01: ожидался NULL для 2031 года")
    return problems


if __name__ == "__main__":
    connection = build()
    gold_data = run_gold(connection)
    issues = sanity_checks(connection, gold_data)
    cnt = {t: connection.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
           for t in ("categories", "customers", "products", "orders", "order_items")}
    print("База создана:", DB_PATH.name, cnt)
    print("Эталоны сохранены:", GOLD_PATH.name, f"({len(gold_data)} вопросов)")
    if issues:
        print("ВНИМАНИЕ, проблемы:")
        for p in issues:
            print(" -", p)
    else:
        print("Проверки пройдены: ответы однозначны.")
    connection.close()
