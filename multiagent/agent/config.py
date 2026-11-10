"""Настройки системы. Всё можно переопределить переменными окружения."""
import os
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "shop.db"
SCHEMA_PATH = ROOT / "schema_description.md"
MEMORY_DB = ROOT / "data" / "memory.db"
LOG_PATH = ROOT / "logs" / "agent.jsonl"
RUNNER_PATH = ROOT / "sandbox" / "runner.py"

# Собственная переменная, чтобы не конфликтовать с OLLAMA_HOST самой Ollama
OLLAMA_HOST = os.getenv("AGENT_OLLAMA_HOST", "localhost:11434")
NUM_CTX = 4096
LLM_TIMEOUT_S = 600

SANDBOX_IMAGE = "multiagent-sandbox:latest"
SQL_TIMEOUT_S = 5          # лимит выполнения SQL внутри песочницы
DOCKER_TIMEOUT_S = 40      # общий лимит на запуск контейнера (включая старт)
MAX_ROWS = 100
EMPTY_RETRIES = 1          # сколько раз повторять запрос, вернувший пустой результат


@dataclass
class Settings:
    small_model: str = os.getenv("SMALL_MODEL", "qwen3:1.7b")   # оркестратор, ответчик
    main_model: str = os.getenv("MAIN_MODEL", "llama3.2:3b")       # планировщик, SQL, верификатор
    sandbox_mode: str = os.getenv("SANDBOX_MODE", "docker")     # docker | local (только для отладки)
    llm_verify: bool = os.getenv("LLM_VERIFY", "1") == "1"      # семантическая проверка LLM
    use_memory: bool = True
    max_attempts: int = 3
    sql_timeout_s: int = SQL_TIMEOUT_S
    extra: dict = field(default_factory=dict)
