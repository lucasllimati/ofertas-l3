"""Modelos Pydantic da configuração multi-nicho (config/niches.yaml)."""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

SLOT_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PostsPerDay(Strict):
    instagram: int = Field(3, ge=0)
    tiktok: int = Field(2, ge=0)
    telegram: int = Field(8, ge=0)
    stories: int = Field(5, ge=0)


class Limits(Strict):
    posts_per_day: PostsPerDay = PostsPerDay()
    llm_budget_usd_per_day: float = Field(0.30, ge=0)
    products_in_store: int = Field(60, ge=1)
    new_content_per_day: int = Field(5, ge=0)


class Filters(Strict):
    min_rating: float = Field(0, ge=0, le=5)
    min_reviews: int = Field(0, ge=0)
    min_commission_rate: float = Field(0, ge=0, le=1)
    blocked_categories: list[str] = []
    price_min: float | None = Field(None, ge=0)
    price_max: float | None = Field(None, ge=0)


class ScoreWeights(Strict):
    acceleration: float = Field(0.30, ge=0)
    consistency: float = Field(0.15, ge=0)
    commission: float = Field(0.20, ge=0)
    quality: float = Field(0.15, ge=0)
    my_channel: float = Field(0.15, ge=0)
    real_discount: float = Field(0.05, ge=0)

    @model_validator(mode="after")
    def _non_zero(self) -> ScoreWeights:
        if sum(self.model_dump().values()) <= 0:
            raise ValueError("score_weights: a soma dos pesos precisa ser maior que zero")
        return self


class Coupons(Strict):
    min_discount_pct: float = 10
    min_discount_brl: float = 20
    min_hours_valid: float = 6


class LlmSettings(Strict):
    enabled: bool = True
    copy_model: str = "claude-sonnet-5-5"
    review_model: str = "claude-haiku-5-5"


class PriceGuard(Strict):
    """Vigia de preço e estoque: reconsulta o produto antes de publicar."""

    enabled: bool = True
    tolerance_pct: float = Field(2.0, ge=0, le=50)  # diferença aceita entre o preço do post e o atual


class Recycle(Strict):
    """Reciclador: devolve à pauta produtos que já venderam, depois do cooldown."""

    enabled: bool = True
    max_share: float = Field(0.2, ge=0, le=1)  # fração dos posts do dia reservada a campeões
    lookback_days: int = Field(60, ge=7, le=365)


class Sentinel(Strict):
    """Sentinela: destaca posts muito acima (ou sem nenhum resultado) da média do nicho."""

    winner_multiplier: float = Field(2.0, ge=1)
    min_clicks: int = Field(20, ge=0)


class AgentSettings(Strict):
    price_guard: PriceGuard = PriceGuard()
    recycle: Recycle = Recycle()
    sentinel: Sentinel = Sentinel()
    compliance_llm: bool = True  # Classificador de conformidade (Claude Haiku), se houver chave
    ab_test: bool = True  # Laboratório A/B de copy
    broken_links: bool = True  # Detector de link quebrado


class NicheSettings(Strict):
    """Campos que existem em `defaults` e podem ser sobrescritos por nicho."""

    timezone: str = "America/Sao_Paulo"
    approval: Literal["manual", "auto_above_score"] = "manual"
    auto_approve_min_score: float = Field(0.85, ge=0, le=1)
    publish_slots: list[str] = ["08:07", "12:07", "19:07", "21:07"]
    exploration_rate: float = Field(0.20, ge=0, le=1)
    limits: Limits = Limits()
    filters: Filters = Filters()
    score_weights: ScoreWeights = ScoreWeights()
    coupons: Coupons = Coupons()
    llm: LlmSettings = LlmSettings()
    agents: AgentSettings = AgentSettings()

    @field_validator("publish_slots")
    @classmethod
    def _slots(cls, v: list[str]) -> list[str]:
        if not v:
            raise ValueError("publish_slots não pode ser vazio")
        for slot in v:
            if not SLOT_RE.match(slot):
                raise ValueError(f"slot inválido {slot!r}: use HH:MM")
        return sorted(set(v))


class ShopeePlatform(Strict):
    mode: Literal["api", "off"] = "api"
    keywords: list[str] = []
    limit_per_keyword: int = Field(30, ge=1, le=50)


class ManualPlatform(Strict):
    mode: Literal["manual", "off"] = "manual"


class Platforms(Strict):
    shopee: ShopeePlatform | None = None
    mercadolivre: ManualPlatform | None = None
    amazon: ManualPlatform | None = None


REF_RE = r"^[A-Z][A-Z0-9_]{1,30}$"


class TelegramChannel(Strict):
    channel_ref: str = Field(pattern=REF_RE)
    enabled: bool = True


class SocialChannel(Strict):
    account_ref: str = Field(pattern=REF_RE)
    enabled: bool = False


class Channels(Strict):
    telegram: TelegramChannel | None = None
    instagram: SocialChannel | None = None
    tiktok: SocialChannel | None = None


class Store(Strict):
    subdomain: str = Field(pattern=r"^[a-z0-9-]{2,30}$")
    brand: str


class Competitors(Strict):
    instagram: list[str] = []


class Tracking(Strict):
    # Vai como subId na Shopee: só letras minúsculas e números.
    sub_id: str = Field(pattern=r"^[a-z0-9]{2,20}$")


class Niche(Strict):
    id: str = Field(pattern=r"^[a-z][a-z0-9-]{1,19}$")
    name: str
    status: Literal["candidate", "active", "paused"]
    platforms: Platforms = Platforms()
    manual_offers: str | None = None
    store: Store | None = None
    channels: Channels = Channels()
    competitors: Competitors = Competitors()
    tracking: Tracking
    settings: NicheSettings

    @property
    def is_active(self) -> bool:
        return self.status == "active"

    @property
    def uses_shopee_api(self) -> bool:
        return self.platforms.shopee is not None and self.platforms.shopee.mode == "api"

    @model_validator(mode="after")
    def _active_requirements(self) -> Niche:
        if self.status != "active":
            return self
        if not (self.uses_shopee_api or self.manual_offers):
            raise ValueError(f"nicho {self.id}: ativo sem fonte (shopee api ou manual_offers)")
        if not (self.channels.telegram and self.channels.telegram.enabled):
            raise ValueError(f"nicho {self.id}: ativo precisa de canal telegram habilitado")
        for name in ("instagram", "tiktok"):
            channel = getattr(self.channels, name)
            if channel and channel.enabled:
                raise ValueError(
                    f"nicho {self.id}: publicação em {name} ainda não implementada nesta versão; "
                    "mantenha enabled: false"
                )
        return self


class GlobalSettings(Strict):
    llm_budget_usd_per_day: float = Field(1.0, ge=0)
    repost_cooldown_days: int = Field(7, ge=0)


class AppConfig(Strict):
    version: Literal[1]
    global_: GlobalSettings = Field(GlobalSettings(), alias="global")
    defaults: NicheSettings
    niches: list[Niche]

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    @model_validator(mode="after")
    def _unique(self) -> AppConfig:
        for attr in ("id", "sub_id"):
            values = [n.id if attr == "id" else n.tracking.sub_id for n in self.niches]
            dupes = {v for v in values if values.count(v) > 1}
            if dupes:
                raise ValueError(f"{attr} duplicado entre nichos: {sorted(dupes)}")
        return self

    def niche(self, niche_id: str) -> Niche:
        for n in self.niches:
            if n.id == niche_id:
                return n
        raise KeyError(f"nicho desconhecido: {niche_id}")

    def by_sub_id(self, sub_id: str) -> Niche | None:
        return next((n for n in self.niches if n.tracking.sub_id == sub_id), None)
