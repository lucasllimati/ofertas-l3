"""Contratos das fontes de ofertas."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Protocol

ROOT = Path(__file__).resolve().parents[2]


def allowed_domains() -> list[str]:
    data = json.loads((ROOT / "config" / "allowed_domains.json").read_text(encoding="utf-8"))
    return list(data["domains"])


@dataclass
class Offer:
    platform: str
    item_id: str
    title: str
    price: float
    product_url: str
    image_url: str | None = None
    affiliate_url: str | None = None
    price_original: float | None = None
    rating: float | None = None
    reviews: int | None = None
    sales_total: int | None = None
    commission_rate: float | None = None
    category: str | None = None
    shop_name: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def product_id(self) -> str:
        return f"{self.platform}:{self.item_id}"

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False, sort_keys=True)

    @classmethod
    def from_json(cls, payload: str) -> Offer:
        return cls(**json.loads(payload))


@dataclass
class ConversionRecord:
    platform: str
    conversion_id: str
    order_id: str
    item_id: str
    purchase_time: str  # UTC ISO
    status: str
    amount: float
    commission: float
    sub_ids: list[str]
    raw: dict[str, Any] = field(default_factory=dict)


class OfferSource(Protocol):
    def search(self, keyword: str, limit: int) -> list[Offer]: ...


class AffiliateLinker(Protocol):
    def short_link(self, url: str, sub_ids: list[str]) -> str: ...


class ConversionSource(Protocol):
    def conversions(self, start_ts: int, end_ts: int) -> list[ConversionRecord]: ...
