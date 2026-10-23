"""Logging JSON com contexto (run_id, correlation_id, niche_id) e redação de segredos."""

from __future__ import annotations

import contextvars
import json
import logging
import os
import re
import sys
from datetime import UTC, datetime

run_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("run_id", default="-")
correlation_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("correlation_id", default="-")
niche_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("niche_id", default="-")

SECRET_NAME_RE = re.compile(r"(TOKEN|SECRET|PASSWORD|API_KEY|DATABASE_URL|_KEY$)", re.I)
SECRET_PATTERNS = [
    re.compile(r"\b\d{6,12}:[A-Za-z0-9_-]{30,}\b"),  # token de bot do Telegram
    re.compile(r"sk-ant-[A-Za-z0-9_-]{10,}"),  # chave da Anthropic
    re.compile(r"(postgres(?:ql)?://[^:/\s]+:)[^@\s]+(@)"),  # senha em URL do Postgres
    re.compile(r"(Signature=)[0-9a-f]{16,}"),  # assinatura da Shopee
    re.compile(r"(Bearer\s+)[A-Za-z0-9._-]{16,}"),
]
MASK = "***"


def _secret_values() -> list[str]:
    values = [v for k, v in os.environ.items() if SECRET_NAME_RE.search(k) and v and len(v) >= 6]
    return sorted(values, key=len, reverse=True)


def redact(text: str, extra_values: list[str] | None = None) -> str:
    for value in (extra_values or []) + _secret_values():
        text = text.replace(value, MASK)
    for pattern in SECRET_PATTERNS:
        if pattern.groups:
            text = pattern.sub(lambda m: m.group(1) + MASK + (m.group(2) if m.lastindex == 2 else ""), text)
        else:
            text = pattern.sub(MASK, text)
    return text


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": datetime.now(UTC).isoformat(timespec="seconds"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
            "run_id": run_id_var.get(),
            "correlation_id": correlation_id_var.get(),
            "niche_id": niche_id_var.get(),
        }
        extra = getattr(record, "data", None)
        if extra:
            payload["data"] = extra
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return redact(json.dumps(payload, ensure_ascii=False, default=str))


def setup_logging(level: str | None = None) -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")  # console do Windows usa cp1252
    root = logging.getLogger()
    root.handlers.clear()
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root.addHandler(handler)
    root.setLevel(level or os.environ.get("LOG_LEVEL", "INFO"))
    # Bibliotecas HTTP logam URLs completas (a do Telegram contém o token).
    for noisy in ("httpx", "httpcore", "anthropic"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
