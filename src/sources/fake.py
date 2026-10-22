"""Fonte determinística para o modo demo e para testes (sem rede)."""

from __future__ import annotations

import hashlib
from datetime import date

from src.common.util import short_id
from src.sources.base import ConversionRecord, Offer

ADJECTIVES = ["Premium", "Compacto", "Dobrável", "Kit 3 em 1", "Inox", "Silicone", "Portátil", "LED"]


class FakeShopee:
    """Gera ofertas estáveis por palavra-chave; as vendas crescem com a data (para janelas 1d/7d)."""

    def __init__(self, run_date: date, per_keyword: int = 8, fail_keywords: set[str] | None = None):
        self.run_date = run_date
        self.per_keyword = per_keyword
        self.fail_keywords = fail_keywords or set()
        self.links: list[tuple[str, list[str]]] = []

    def search(self, keyword: str, limit: int) -> list[Offer]:
        if keyword in self.fail_keywords:
            raise RuntimeError(f"falha simulada na palavra-chave {keyword}")
        day = self.run_date.toordinal() - date(2026, 1, 1).toordinal()
        offers = []
        for i in range(min(limit, self.per_keyword)):
            seed = int(hashlib.sha256(f"{keyword}|{i}".encode()).hexdigest()[:8], 16)
            item_id = str(10_000_000 + seed % 89_999_999)
            price = round(15 + seed % 180 + 0.9, 2)
            velocity = 3 + seed % 40
            offers.append(
                Offer(
                    platform="shopee",
                    item_id=item_id,
                    title=f"{keyword.title()} {ADJECTIVES[seed % len(ADJECTIVES)]}",
                    price=price,
                    price_original=round(price * (1.2 + (seed % 5) / 10), 2),
                    product_url=f"https://shopee.com.br/product/1/{item_id}",
                    affiliate_url=f"https://s.shopee.com.br/{short_id(item_id, length=8)}",
                    image_url=None,
                    rating=round(4.2 + (seed % 9) / 10, 1),
                    sales_total=500 + velocity * day,
                    commission_rate=round(0.04 + (seed % 8) / 100, 2),
                    category="demo",
                    shop_name="Loja Demo",
                )
            )
        return offers

    def short_link(self, url: str, sub_ids: list[str]) -> str:
        self.links.append((url, sub_ids))
        return f"https://s.shopee.com.br/{short_id(url, *sub_ids, length=8)}"

    def conversions(self, start_ts: int, end_ts: int) -> list[ConversionRecord]:
        return []
