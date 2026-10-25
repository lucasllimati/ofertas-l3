"""Agente Calendário sazonal: datas de pico (Black Friday, 11.11, 12.12, Natal, Dia das Mães...).

Num evento ativo para o nicho:
- Rastreador busca também as palavras-chave extras do evento;
- Editor de pauta e Publicador multiplicam o volume do dia (`content_multiplier`);
- Designer e legenda ganham o selo do evento (`badge`);
- o relatório avisa `heads_up_days` antes de começar, para você preparar ofertas.

Eventos ficam em config/calendar.yaml; adicionar uma data é só configuração.
"""

from __future__ import annotations

import math
from datetime import date
from functools import lru_cache
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

ROOT = Path(__file__).resolve().parents[2]
CALENDAR_PATH = ROOT / "config" / "calendar.yaml"


class SeasonalEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^[a-z0-9-]{2,40}$")
    name: str
    start: date
    end: date
    niches: list[str] = []  # vazio = todos os nichos
    extra_keywords: dict[str, list[str]] = {}  # nicho -> palavras-chave extras
    content_multiplier: float = Field(1.0, ge=1.0, le=3.0)
    badge: str | None = Field(None, max_length=24)
    heads_up_days: int = Field(7, ge=0, le=60)

    @model_validator(mode="after")
    def _dates(self) -> SeasonalEvent:
        if self.end < self.start:
            raise ValueError(f"evento {self.id}: end antes de start")
        return self

    def applies_to(self, niche_id: str) -> bool:
        return not self.niches or niche_id in self.niches

    def active_on(self, day: date) -> bool:
        return self.start <= day <= self.end


class Calendar(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: int = 1
    events: list[SeasonalEvent] = []

    @model_validator(mode="after")
    def _unique(self) -> Calendar:
        ids = [e.id for e in self.events]
        dupes = {i for i in ids if ids.count(i) > 1}
        if dupes:
            raise ValueError(f"evento duplicado no calendário: {sorted(dupes)}")
        return self

    def active(self, day: date, niche_id: str) -> list[SeasonalEvent]:
        return [e for e in self.events if e.active_on(day) and e.applies_to(niche_id)]

    def upcoming(self, day: date) -> list[tuple[SeasonalEvent, int]]:
        """Eventos que começam dentro do aviso prévio: [(evento, dias até começar)]."""
        out = []
        for e in self.events:
            days = (e.start - day).days
            if 0 < days <= e.heads_up_days:
                out.append((e, days))
        return sorted(out, key=lambda x: x[1])

    def extra_keywords(self, day: date, niche_id: str) -> list[str]:
        words: list[str] = []
        for e in self.active(day, niche_id):
            words += [w for w in e.extra_keywords.get(niche_id, []) if w not in words]
        return words

    def multiplier(self, day: date, niche_id: str) -> float:
        return max((e.content_multiplier for e in self.active(day, niche_id)), default=1.0)

    def badge(self, day: date, niche_id: str) -> str | None:
        return next((e.badge for e in self.active(day, niche_id) if e.badge), None)


def scaled(value: int, multiplier: float) -> int:
    """Aplica o multiplicador do evento a um limite diário (arredonda para cima)."""
    return int(math.ceil(value * multiplier))


@lru_cache(maxsize=4)
def load_calendar(path: str | None = None) -> Calendar:
    file = Path(path) if path else CALENDAR_PATH
    if not file.exists():
        return Calendar()
    return Calendar.model_validate(yaml.safe_load(file.read_text(encoding="utf-8")) or {})
