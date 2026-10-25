"""Planejamento do conteúdo do dia: escolhe produtos (topo + exploração), gera link
rastreável, copy e legenda, e cria content_item em `ready`."""

from __future__ import annotations

import random
from datetime import timedelta
from typing import Any

from src.agents.coupons import best_for
from src.agents.insights import variant_for
from src.agents.seasonal import scaled
from src.agents.sentinel import recycle_picks
from src.common.logging import get_logger
from src.common.util import host_allowed, iso, short_id, slot_to_utc
from src.config.models import Niche
from src.content.brand import load_brand
from src.content.caption import build_caption, compliance_issues
from src.content.copy import CopyResult, TemplateCopywriter
from src.context import AppContext
from src.sources.base import allowed_domains

log = get_logger(__name__)

CHANNEL = "telegram"
CHANNEL_CODE = {"telegram": "tg", "instagram": "ig", "tiktok": "tt"}
CODE_CHANNEL = {v: k for k, v in CHANNEL_CODE.items()}


def pick_products(
    ranked: list[dict[str, Any]], n: int, exploration_rate: float, seed: str
) -> list[tuple[dict[str, Any], str]]:
    """Top (1-ε) + ε sorteados entre as posições seguintes (até 4n). Determinístico pelo seed."""
    if n <= 0 or not ranked:
        return []
    n_explore = int(round(n * exploration_rate))
    pool_after_top = ranked[n - n_explore : n - n_explore + 4 * n]
    if len(pool_after_top) < n_explore:  # pouco produto: fica só com o topo
        n_explore = 0
    top = [(p, "top") for p in ranked[: n - n_explore]]
    explore = random.Random(seed).sample(pool_after_top, n_explore) if n_explore else []
    return top + [(p, "exploration") for p in explore]


def eligible_products(ctx: AppContext, niche: Niche) -> list[dict[str, Any]]:
    cooldown = ctx.config.global_.repost_cooldown_days
    since = (ctx.run_date - timedelta(days=cooldown)).isoformat()
    return ctx.db.fetchall(
        "SELECT p.*, s.score, s.rank FROM product_score s JOIN product p ON p.id = s.product_id "
        "WHERE s.niche_id = ? AND s.run_date = ? AND s.eligible = 1 "
        "AND NOT EXISTS (SELECT 1 FROM content_item c WHERE c.niche_id = s.niche_id "
        "  AND c.product_id = s.product_id AND c.run_date >= ?) "
        "ORDER BY s.rank",
        (niche.id, ctx.run_date.isoformat(), since),
    )


FULL_PRICE_TOLERANCE = 0.98
FULL_PRICE_LOOKBACK_DAYS = 30


def verified_original(ctx: AppContext, product: dict[str, Any]) -> float | None:
    """Preço "de" só aparece se o sistema viu o produto custando isso nos últimos 30 dias.

    O desconto declarado pelo vendedor não basta: inflar o "de" antes da promoção é o golpe
    mais comum, e divulgar "de/por" falso é publicidade enganosa (CDC art. 37).
    """
    original = product.get("price_original")
    if not original or original <= product["price"]:
        return None
    since = (ctx.run_date - timedelta(days=FULL_PRICE_LOOKBACK_DAYS)).isoformat()
    highest = ctx.db.scalar(
        "SELECT max(price) FROM product_daily WHERE product_id = ? AND run_date >= ? AND run_date < ?",
        (product["id"], since, ctx.run_date.isoformat()),
    )
    return original if highest is not None and highest >= original * FULL_PRICE_TOLERANCE else None


def affiliate_link(ctx: AppContext, niche: Niche, product: dict[str, Any], content_id: str) -> str:
    """Link com subIds <nicho>, <canal>, <conteúdo>: a Shopee devolve isso no relatório de conversões."""
    is_manual = product.get("affiliate_url") == product.get("product_url")
    if product["platform"] == "shopee" and ctx.linker and not is_manual:
        try:
            return ctx.linker.short_link(
                product["product_url"], [niche.tracking.sub_id, CHANNEL_CODE[CHANNEL], content_id]
            )
        except Exception as exc:
            log.warning("short link falhou; usando offerLink", extra={"data": {"error": str(exc)[:200]}})
    return product.get("affiliate_url") or product["product_url"]


def coupon_for(ctx: AppContext, niche: Niche, product: dict[str, Any], price: float):
    """Caçador de cupons: melhor cupom válido para o produto (ou None)."""
    if not ctx.coupons:
        return None
    return best_for(ctx.coupons, niche, product["platform"], price, ctx.now)


def make_caption(
    ctx: AppContext,
    niche: Niche,
    copy: CopyResult,
    price: float,
    shown_original: float | None,
    tracked: str,
    coupon_code: str | None,
) -> str:
    brand = load_brand(niche)
    badge = ctx.calendar.badge(ctx.run_date, niche.id) if ctx.calendar else None
    coupon = next((c for c in ctx.coupons if c.code == coupon_code), None) if coupon_code else None
    line = coupon.caption_line(niche.settings.timezone) if coupon else None
    return build_caption(copy, price, shown_original, tracked, ctx.run_date, brand.get("hashtags", []), badge, line)


def stored_copy(ctx: AppContext, niche: Niche, item: dict[str, Any], product: dict[str, Any]) -> CopyResult:
    """Copy original do post (gravada na criação); posts antigos sem copy_json caem no template."""
    if item.get("copy_json"):
        return CopyResult.model_validate_json(item["copy_json"])
    return TemplateCopywriter().write(product, niche, load_brand(niche), item.get("copy_variant") or "A")[0]


def rebuild_for_price(ctx: AppContext, niche: Niche, item: dict[str, Any], new_price: float, reason: str) -> None:
    """Vigia de preço: refaz legenda e arte com o preço novo e devolve o post para a sua aprovação."""
    product = ctx.db.fetchone("SELECT * FROM product WHERE id = ?", (item["product_id"],)) or {}
    priced = {**product, "price": new_price}
    shown = verified_original(ctx, priced)
    code = item.get("coupon_code")
    coupon = next((c for c in ctx.coupons if c.code == code), None) if code else None
    if coupon is None or not coupon.applies(product.get("platform", ""), niche.id, new_price):
        code = None
    copy = stored_copy(ctx, niche, item, product)
    caption = make_caption(ctx, niche, copy, new_price, shown, item["tracked_url"], code)
    ctx.db.execute(
        "UPDATE content_item SET status = 'ready', caption = ?, price_at_creation = ?, price_original_shown = ?, "
        "coupon_code = ?, media_file_id = NULL, preview_message_id = NULL, published_at = NULL, status_reason = ?, "
        "updated_at = ? WHERE id = ?",
        (caption, new_price, shown, code, reason, iso(ctx.now), item["id"]),
    )


def drop_expired_coupon(ctx: AppContext, niche: Niche, item: dict[str, Any]) -> str:
    """Caçador de cupons: cupom venceu entre a aprovação e a publicação -> tira da legenda (mesmo preço)."""
    product = ctx.db.fetchone("SELECT * FROM product WHERE id = ?", (item["product_id"],)) or {}
    copy = stored_copy(ctx, niche, item, product)
    caption = make_caption(
        ctx, niche, copy, item["price_at_creation"], item.get("price_original_shown"), item["tracked_url"], None
    )
    ctx.db.execute(
        "UPDATE content_item SET caption = ?, coupon_code = NULL, status_reason = ?, updated_at = ? WHERE id = ?",
        (caption, "cupom vencido removido da legenda", iso(ctx.now), item["id"]),
    )
    return caption


def create_content(ctx: AppContext, niche: Niche) -> dict[str, int]:
    settings = niche.settings
    day = ctx.run_date.isoformat()
    existing = ctx.db.scalar(
        "SELECT count(*) FROM content_item WHERE niche_id = ? AND run_date = ? AND channel = ?",
        (niche.id, day, CHANNEL),
    )
    # Calendário sazonal: em evento ativo, mais posts no dia.
    multiplier = ctx.calendar.multiplier(ctx.run_date, niche.id) if ctx.calendar else 1.0
    wanted = scaled(settings.limits.new_content_per_day, multiplier) - int(existing or 0)
    if wanted <= 0:
        return {"created": 0, "skipped": 0}

    eligible = eligible_products(ctx, niche)
    # Reciclador: campeões (já venderam) primeiro; o resto vem do topo + exploração.
    recycled = recycle_picks(ctx, niche, eligible, wanted)
    taken = {p["id"] for p, _ in recycled}
    remaining = [p for p in eligible if p["id"] not in taken]
    rest = pick_products(remaining, wanted - len(recycled), settings.exploration_rate, f"{niche.id}|{day}")
    picks = recycled + rest
    brand = load_brand(niche)
    domains = allowed_domains()
    created = skipped = blocked = 0
    for i, (product, reason) in enumerate(picks):
        # Classificador de conformidade (Haiku): barra proibidos que o filtro por palavra deixou passar.
        if ctx.compliance:
            allowed, why = ctx.compliance.allowed(ctx, niche, product)
            if not allowed:
                log.warning("produto barrado pela conformidade", extra={"data": {"product": product["id"], "why": why}})
                blocked += 1
                continue
        content_id = short_id(niche.id, product["id"], CHANNEL, day)
        link = affiliate_link(ctx, niche, product, content_id)
        if not host_allowed(link, domains):
            log.warning("link de afiliado fora da allowlist", extra={"data": {"product": product["id"]}})
            skipped += 1
            continue
        tracked = link
        if ctx.redirect:
            tracked = ctx.redirect.register(content_id, link, niche.id, CHANNEL_CODE[CHANNEL])

        variant = variant_for(content_id, settings.agents.ab_test)  # Laboratório A/B
        copy, source = ctx.copywriter.write(product, niche, brand, variant)
        shown_original = verified_original(ctx, product)
        coupon = coupon_for(ctx, niche, product, product["price"])
        code = coupon.code if coupon else None
        caption = make_caption(ctx, niche, copy, product["price"], shown_original, tracked, code)
        link_ok = host_allowed(tracked, domains) or (
            ctx.redirect is not None and tracked.startswith(ctx.redirect.base_url)
        )
        issues = compliance_issues(caption, link_ok)
        if issues:
            log.warning("conteúdo reprovado nas regras", extra={"data": {"product": product["id"], "issues": issues}})
            skipped += 1
            continue

        slots = settings.publish_slots
        slot = slots[(int(existing or 0) + i) % len(slots)]
        scheduled = slot_to_utc(ctx.run_date, slot, settings.timezone)
        now = iso(ctx.now)
        inserted = ctx.db.execute(
            "INSERT INTO content_item (id, niche_id, product_id, channel, run_date, status, score, "
            "pick_reason, caption, copy_source, affiliate_url, tracked_url, price_at_creation, "
            "price_original_shown, copy_json, copy_variant, coupon_code, scheduled_for, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, 'ready', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT DO NOTHING",
            (
                content_id,
                niche.id,
                product["id"],
                CHANNEL,
                day,
                product["score"],
                reason,
                caption,
                source,
                link,
                tracked,
                product["price"],
                shown_original,
                copy.model_dump_json(),
                variant,
                code,
                iso(scheduled),
                now,
                now,
            ),
        )
        created += max(inserted, 0)
    return {"created": created, "skipped": skipped, "blocked": blocked, "recycled": len(recycled)}
