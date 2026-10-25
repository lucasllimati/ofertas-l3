"""Fonte determinística para o modo demo e para testes (sem rede).

Simula também o que a API real devolveria para os agentes: preço atual por item (Vigia de preço)
e vendas atribuídas aos links gerados (Financeiro, Sentinela, Contador)."""

from __future__ import annotations

import hashlib
from datetime import UTC, date, datetime, time

from src.agents.price_guard import PriceStatus
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
        self.catalog: dict[str, Offer] = {}  # item_id -> última oferta gerada
        self.price_overrides: dict[str, float] = {}  # testes: preço atual diferente do anunciado
        self.unavailable: set[str] = set()  # testes: itens esgotados

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
            offer = Offer(
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
            self.catalog[item_id] = offer
            offers.append(offer)
        return offers

    def item_status(self, item_id: str) -> PriceStatus:
        if item_id in self.unavailable or item_id not in self.catalog:
            return PriceStatus(available=False)
        return PriceStatus(available=True, price=self.price_overrides.get(item_id, self.catalog[item_id].price))

    def short_link(self, url: str, sub_ids: list[str]) -> str:
        self.links.append((url, sub_ids))
        return f"https://s.shopee.com.br/{short_id(url, *sub_ids, length=8)}"

    def conversions(self, start_ts: int, end_ts: int) -> list[ConversionRecord]:
        """Cerca de 1 em cada 3 links gerados "vende" (determinístico), com comissão real do item."""
        records = []
        purchase = datetime.combine(self.run_date, time(15, 0), tzinfo=UTC).isoformat(timespec="seconds")
        for url, sub_ids in self.links:
            item_id = url.rstrip("/").rsplit("/", 1)[-1]
            offer = self.catalog.get(item_id)
            if not offer or int(short_id(url, *sub_ids, length=6), 36) % 3:
                continue
            records.append(
                ConversionRecord(
                    platform="shopee",
                    conversion_id=short_id("conv", url, *sub_ids),
                    order_id=short_id("order", url, *sub_ids),
                    item_id=item_id,
                    purchase_time=purchase,
                    status="COMPLETED",
                    amount=offer.price,
                    commission=round(offer.price * (offer.commission_rate or 0), 2),
                    sub_ids=list(sub_ids),
                )
            )
        return records
