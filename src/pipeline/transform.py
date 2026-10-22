"""Silver: bronze do dia -> product, product_niche, product_daily, price_history (SCD2)."""

from __future__ import annotations

from src.common.logging import get_logger
from src.common.util import host_allowed
from src.config.models import Niche
from src.context import AppContext
from src.sources.base import Offer, allowed_domains

log = get_logger(__name__)

MAX_INVALID_SHARE = 0.5


class DataQualityError(RuntimeError):
    pass


def quality_issue(offer: Offer, domains: list[str]) -> str | None:
    if not offer.title.strip():
        return "sem título"
    if offer.price <= 0 or offer.price > 100_000:
        return "preço fora da faixa"
    if offer.rating is not None and not 0 <= offer.rating <= 5:
        return "nota fora de 0..5"
    if offer.commission_rate is not None and not 0 <= offer.commission_rate <= 1:
        return "comissão fora de 0..1"
    link = offer.affiliate_url or offer.product_url
    if not host_allowed(link, domains):
        return "link fora da allowlist"
    return None


def load_day_offers(ctx: AppContext, niche: Niche) -> list[tuple[Offer, str]]:
    rows = ctx.db.fetchall(
        "SELECT s.payload, m.keyword FROM raw_offer_snapshot s "
        "JOIN raw_offer_niche m ON m.run_date = s.run_date AND m.platform = s.platform "
        "AND m.item_id = s.item_id WHERE s.run_date = ? AND m.niche_id = ?",
        (ctx.run_date.isoformat(), niche.id),
    )
    return [(Offer.from_json(r["payload"]), r["keyword"]) for r in rows]


def transform(ctx: AppContext, niche: Niche) -> dict[str, int]:
    day = ctx.run_date.isoformat()
    domains = allowed_domains()
    offers = load_day_offers(ctx, niche)
    valid: list[tuple[Offer, str]] = []
    invalid = 0
    for offer, keyword in offers:
        issue = quality_issue(offer, domains)
        if issue:
            invalid += 1
            log.info("oferta descartada", extra={"data": {"item": offer.item_id, "motivo": issue}})
        else:
            valid.append((offer, keyword))
    if offers and invalid / len(offers) > MAX_INVALID_SHARE:
        raise DataQualityError(f"{invalid}/{len(offers)} ofertas inválidas: verifique a fonte")

    with ctx.db.transaction():
        for offer, keyword in valid:
            pid = offer.product_id
            ctx.db.execute(
                "INSERT INTO product (id, platform, item_id, title, image_url, product_url, "
                "affiliate_url, shop_name, category, rating, reviews, commission_rate, price, "
                "price_original, sales_total, first_seen, last_seen) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT (id) DO UPDATE SET title = excluded.title, "
                "image_url = excluded.image_url, product_url = excluded.product_url, "
                "affiliate_url = excluded.affiliate_url, shop_name = excluded.shop_name, "
                "category = excluded.category, rating = excluded.rating, "
                "reviews = excluded.reviews, commission_rate = excluded.commission_rate, "
                "price = excluded.price, price_original = excluded.price_original, "
                "sales_total = excluded.sales_total, last_seen = excluded.last_seen",
                (
                    pid,
                    offer.platform,
                    offer.item_id,
                    offer.title,
                    offer.image_url,
                    offer.product_url,
                    offer.affiliate_url,
                    offer.shop_name,
                    offer.category,
                    offer.rating,
                    offer.reviews,
                    offer.commission_rate,
                    offer.price,
                    offer.price_original,
                    offer.sales_total,
                    day,
                    day,
                ),
            )
            ctx.db.execute(
                "INSERT INTO product_niche (product_id, niche_id, keyword, first_seen, last_seen) "
                "VALUES (?, ?, ?, ?, ?) ON CONFLICT (product_id, niche_id) DO UPDATE SET "
                "keyword = excluded.keyword, last_seen = excluded.last_seen",
                (pid, niche.id, keyword, day, day),
            )
            ctx.db.execute(
                "INSERT INTO product_daily (product_id, run_date, price, sales_total, rating, "
                "commission_rate) VALUES (?, ?, ?, ?, ?, ?) "
                "ON CONFLICT (product_id, run_date) DO UPDATE SET price = excluded.price, "
                "sales_total = excluded.sales_total, rating = excluded.rating, "
                "commission_rate = excluded.commission_rate",
                (pid, day, offer.price, offer.sales_total, offer.rating, offer.commission_rate),
            )
            update_price_history(ctx, pid, day, offer.price)
    return {"valid": len(valid), "invalid": invalid}


def update_price_history(ctx: AppContext, product_id: str, day: str, price: float) -> None:
    current = ctx.db.fetchone(
        "SELECT valid_from, price FROM price_history WHERE product_id = ? AND valid_to IS NULL",
        (product_id,),
    )
    if current and abs(current["price"] - price) < 0.005:
        return
    if current and current["valid_from"] == day:
        # Reprocessamento do mesmo dia: corrige o registro em vez de abrir outro.
        ctx.db.execute(
            "UPDATE price_history SET price = ? WHERE product_id = ? AND valid_from = ?",
            (price, product_id, day),
        )
        return
    if current and current["valid_from"] > day:
        return  # reprocessando um dia antigo: não reescreve o histórico mais novo
    if current:
        ctx.db.execute(
            "UPDATE price_history SET valid_to = ? WHERE product_id = ? AND valid_to IS NULL",
            (day, product_id),
        )
    ctx.db.execute(
        "INSERT INTO price_history (product_id, valid_from, valid_to, price) VALUES (?, ?, NULL, ?)",
        (product_id, day, price),
    )
