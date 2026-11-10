"""Статические проверки SQL и входящих вопросов (до обращения к песочнице)."""
import re

KNOWN_TABLES = {"categories", "customers", "products", "orders", "order_items"}

FORBIDDEN = re.compile(
    r"\b(insert|update|delete|drop|alter|create|replace|attach|detach|pragma|vacuum|reindex)\b", re.I)


def _strip_comments(sql):
    return re.sub(r"--.*?$|/\*.*?\*/", " ", sql or "", flags=re.S | re.M).strip()


def is_select_only(sql):
    """Ровно одна инструкция SELECT/WITH без запрещённых ключевых слов."""
    s = _strip_comments(sql).rstrip(";").strip()
    if not s or ";" in s:
        return False
    if not re.match(r"(?i)^(select|with)\b", s):
        return False
    return not FORBIDDEN.search(s)


def unknown_tables(sql):
    """Таблицы после FROM/JOIN, которых нет в схеме (CTE-имена исключаются)."""
    s = _strip_comments(sql)
    ctes = {m.lower() for m in re.findall(r"(\w+)\s+AS\s*\(", s, flags=re.I)}
    used = re.findall(r"\b(?:from|join)\s+([A-Za-z_]\w*)", s, flags=re.I)
    return sorted({t for t in used if t.lower() not in KNOWN_TABLES and t.lower() not in ctes})


MALICIOUS_RE = re.compile(
    r"\b(удали(ть)?|сотри|очисти(ть)?|обнови(ть)?|измени(ть)?|увеличь|уменьши(ть)?|добавь|вставь|создай)\b"
    r"|\b(drop\s+table|delete\s+from|truncate|insert\s+into|alter\s+table|update\s+\w+\s+set)\b"
    r"|игнорируй\s+(все\s+)?(предыдущие\s+)?инструкции"
    r"|ignore\s+(all\s+)?(previous\s+)?instructions"
    r"|системн\w+\s+промпт|system\s+prompt",
    re.I)


def looks_malicious(question):
    """Быстрый фильтр запросов на изменение данных и prompt injection."""
    return bool(MALICIOUS_RE.search(question or ""))


# Термины предметной области интернет-магазина. Если вопрос явно касается
# этих сущностей, не отдаём решение о маршруте малой LLM: она часто
# ошибочно классифицирует короткие аналитические формулировки как off_topic.
DOMAIN_TERMS_RE = re.compile(
    r"\b(товар\w*|продукт\w*|каталог\w*|клиент\w*|покупател\w*|заказ\w*|"
    r"выручк\w*|продаж\w*|склад\w*|остат\w*|цен\w*|стоимост\w*|"
    r"категор\w*|корзин\w*|позици\w*|город\w*|регистрац\w*|"
    r"доставк\w*|отменённ\w*|отмененн\w*|возврат\w*|бренд\w*|"
    r"рейтинг\w*|отзыв\w*|месяц\w*|квартал\w*|год\w*|дат\w*)\b",
    re.I,
)


def is_shop_domain_question(question):
    """True для вопросов о сущностях и показателях интернет-магазина."""
    return bool(DOMAIN_TERMS_RE.search(question or ""))
