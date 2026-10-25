"""Utilitários pequenos: ids, datas, texto."""

from __future__ import annotations

import base64
import hashlib
import secrets
import unicodedata
from datetime import UTC, date, datetime, time, timedelta
from urllib.parse import urlparse
from zoneinfo import ZoneInfo


def utcnow() -> datetime:
    return datetime.now(UTC)


def iso(dt: datetime) -> str:
    return dt.astimezone(UTC).isoformat(timespec="seconds")


def parse_iso(value: str) -> datetime:
    dt = datetime.fromisoformat(value)
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def short_id(*parts: object, length: int = 10) -> str:
    """Id determinístico e curto (base32 minúsculo): mesmo input -> mesmo id (idempotência)."""
    digest = hashlib.sha256("|".join(str(p) for p in parts).encode()).digest()
    return base64.b32encode(digest).decode().lower().rstrip("=")[:length]


def random_id(length: int = 16) -> str:
    return base64.b32encode(secrets.token_bytes(16)).decode().lower().rstrip("=")[:length]


def local_today(tz: str, now: datetime | None = None) -> date:
    return (now or utcnow()).astimezone(ZoneInfo(tz)).date()


def slot_to_utc(day: date, slot: str, tz: str) -> datetime:
    hh, mm = (int(x) for x in slot.split(":"))
    return datetime.combine(day, time(hh, mm), tzinfo=ZoneInfo(tz)).astimezone(UTC)


def local_day_bounds_utc(day: date, tz: str) -> tuple[str, str]:
    start = datetime.combine(day, time(0, 0), tzinfo=ZoneInfo(tz))
    return iso(start), iso(start + timedelta(days=1))


def normalize_text(text: str) -> str:
    """minúsculas e sem acento, para comparar palavras bloqueadas."""
    decomposed = unicodedata.normalize("NFKD", text.lower())
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def host_allowed(url: str, allowed: list[str]) -> bool:
    try:
        parsed = urlparse(url)
    except ValueError:
        return False
    if parsed.scheme != "https" or not parsed.hostname:
        return False
    host = parsed.hostname.lower()
    return any(host == d or host.endswith("." + d) for d in allowed)


def parse_money(value: str | None) -> float:
    """'R$ 1.234,50' / '1234.50' / '39,90' -> float. Vazio vira 0; texto inválido levanta ValueError."""
    text = (value or "").replace("R$", "").strip()
    if not text:
        return 0.0
    if "," in text:  # formato brasileiro: ponto é milhar, vírgula é decimal
        text = text.replace(".", "").replace(",", ".")
    try:
        return float(text)
    except ValueError:
        raise ValueError(f"valor inválido: {value!r}") from None


def pct(value: float, digits: int = 1) -> str:
    """Formata 0.155 -> '15,5%' (vírgula decimal, como no resto das mensagens)."""
    return f"{value:.{digits}%}".replace(".", ",")


def dec(value: float, digits: int = 1) -> str:
    """Formata 2.5 -> '2,5'."""
    return f"{value:.{digits}f}".replace(".", ",")


def brl(value: float) -> str:
    """Formata 1234.5 -> 'R$ 1.234,50'."""
    text = f"{value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"R$ {text}"
