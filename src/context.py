"""Contexto de execução: tudo que os passos precisam, montado uma vez por execução.

Todo acesso externo fica atrás de uma interface para os testes usarem fakes.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any

from src.common.db import Database
from src.config.models import AppConfig, Niche
from src.sources.base import AffiliateLinker, ConversionSource, OfferSource

ROOT = Path(__file__).resolve().parents[1]


@dataclass
class AppContext:
    config: AppConfig
    db: Database
    run_date: date
    now: datetime
    run_id: str
    telegram: Any  # TelegramClient | FakeTelegram
    shopee: OfferSource | None = None
    linker: AffiliateLinker | None = None
    conversions_source: ConversionSource | None = None
    copywriter: Any = None  # Copywriter
    image_fetcher: Any = None  # Callable[[str], bytes | None]
    redirect: Any = None  # RedirectRegistry | None
    clicks_source: Any = None  # ClickSource | None
    env: dict[str, str] = field(default_factory=lambda: dict(os.environ))
    out_dir: Path = ROOT / "out"
    demo: bool = False

    @property
    def admin_chat_id(self) -> str:
        return self.env.get("TELEGRAM_ADMIN_CHAT_ID", "")

    @property
    def admin_user_ids(self) -> set[int]:
        raw = self.env.get("TELEGRAM_ADMIN_USER_IDS", "")
        return {int(x) for x in raw.replace(";", ",").split(",") if x.strip().lstrip("-").isdigit()}

    @property
    def hmac_secret(self) -> str:
        return self.env.get("APPROVAL_HMAC_SECRET", "")

    def channel_chat_id(self, niche: Niche) -> str:
        channel = niche.channels.telegram
        return self.env.get(f"{channel.channel_ref}_CHAT_ID", "") if channel else ""

    def niches(self, statuses: tuple[str, ...] = ("active",), only: str | None = None) -> list[Niche]:
        return [n for n in self.config.niches if n.status in statuses and (only is None or n.id == only)]
