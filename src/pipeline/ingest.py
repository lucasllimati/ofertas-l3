"""Bronze: grava as ofertas do dia (API + CSV manual) em raw_offer_snapshot."""

from __future__ import annotations

from datetime import timedelta

from src.common.logging import get_logger
from src.common.util import iso
from src.config.models import Niche
from src.context import AppContext
from src.sources.base import Offer
from src.sources.manual import load_manual_offers

log = get_logger(__name__)

RETENTION_DAYS = 60


def collect(ctx: AppContext, niche: Niche) -> list[tuple[Offer, str]]:
    """Retorna (oferta, palavra-chave). Falha de uma palavra-chave não derruba as outras."""
    found: list[tuple[Offer, str]] = []
    shopee_cfg = niche.platforms.shopee
    failures = 0
    if niche.uses_shopee_api and shopee_cfg and ctx.shopee is None:
        if niche.is_active:
            raise RuntimeError("Shopee API não configurada (SHOPEE_APP_ID/SHOPEE_APP_SECRET)")
        # Nicho candidate só monitora: sem API ainda, pula em vez de alertar todo dia.
        log.info("Shopee API não configurada; nicho candidato sem coleta hoje")
    elif niche.uses_shopee_api and shopee_cfg:
        keywords = list(shopee_cfg.keywords)
        if ctx.calendar:  # Calendário sazonal: palavras-chave extras do evento ativo
            keywords += [k for k in ctx.calendar.extra_keywords(ctx.run_date, niche.id) if k not in keywords]
        for keyword in keywords:
            try:
                for offer in ctx.shopee.search(keyword, shopee_cfg.limit_per_keyword):
                    found.append((offer, keyword))
            except Exception as exc:
                failures += 1
                log.warning(
                    "palavra-chave falhou",
                    extra={"data": {"keyword": keyword, "error": str(exc)[:200]}},
                )
        if keywords and failures == len(keywords):
            raise RuntimeError("todas as palavras-chave da Shopee falharam")
    if niche.manual_offers:
        found.extend((offer, "manual") for offer in load_manual_offers(niche.manual_offers))
    return found


def ingest(ctx: AppContext, niche: Niche) -> dict[str, int]:
    offers = collect(ctx, niche)
    day = ctx.run_date.isoformat()
    fetched = iso(ctx.now)
    snap_rows, map_rows = {}, {}
    for offer, keyword in offers:
        key = (offer.platform, offer.item_id)
        snap_rows[key] = (day, offer.platform, offer.item_id, offer.to_json(), fetched)
        map_rows[key] = (day, offer.platform, offer.item_id, niche.id, keyword)
    with ctx.db.transaction():
        ctx.db.executemany(
            "INSERT INTO raw_offer_snapshot (run_date, platform, item_id, payload, fetched_at) "
            "VALUES (?, ?, ?, ?, ?) ON CONFLICT (run_date, platform, item_id) DO UPDATE SET "
            "payload = excluded.payload, fetched_at = excluded.fetched_at",
            list(snap_rows.values()),
        )
        # Reprocessar o dia substitui o mapeamento do nicho (idempotente).
        ctx.db.execute("DELETE FROM raw_offer_niche WHERE run_date = ? AND niche_id = ?", (day, niche.id))
        ctx.db.executemany(
            "INSERT INTO raw_offer_niche (run_date, platform, item_id, niche_id, keyword) "
            "VALUES (?, ?, ?, ?, ?) ON CONFLICT DO NOTHING",
            list(map_rows.values()),
        )
    return {"offers": len(snap_rows)}


def purge_old_snapshots(ctx: AppContext) -> int:
    cutoff = (ctx.run_date - timedelta(days=RETENTION_DAYS)).isoformat()
    with ctx.db.transaction():
        ctx.db.execute("DELETE FROM raw_offer_niche WHERE run_date < ?", (cutoff,))
        return ctx.db.execute("DELETE FROM raw_offer_snapshot WHERE run_date < ?", (cutoff,))
