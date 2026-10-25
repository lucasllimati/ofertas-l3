"""Agente Detector de link quebrado: confere os posts publicados nos últimos 30 dias.

Produto removido da loja = clique perdido e seguidor frustrado. Shopee via API (mesma consulta do
Vigia de preço); Mercado Livre e Amazon por HTTP (o destino final precisa responder < 400 e estar
na allowlist de domínios). Cada post é avisado uma vez só (marcado em `status_reason`).
O bot não apaga posts antigos: o relatório diz qual post revisar no canal.
"""

from __future__ import annotations

import html
from datetime import timedelta
from typing import Any

import httpx

from src.common.logging import get_logger
from src.common.util import host_allowed, iso
from src.context import AppContext
from src.sources.base import allowed_domains

log = get_logger(__name__)

LOOKBACK_DAYS = 30
MAX_CHECKS_PER_RUN = 40
BROKEN_MARK = "link quebrado"


def http_link_ok(url: str) -> bool | None:
    """True/False = conferido; None = não deu para conferir (rede)."""
    try:
        with httpx.Client(timeout=15, follow_redirects=True) as client:
            resp = client.get(url, headers={"User-Agent": "Mozilla/5.0 (garimpo link check)"})
    except httpx.HTTPError:
        return None
    return resp.status_code < 400 and host_allowed(str(resp.url), allowed_domains())


def check_published_links(ctx: AppContext) -> list[dict[str, Any]]:
    since = iso(ctx.now - timedelta(days=LOOKBACK_DAYS))
    rows = ctx.db.fetchall(
        # Colunas com apelido: post e produto têm "id" e "affiliate_url" com significados diferentes.
        "SELECT c.id AS content_id, c.niche_id, c.affiliate_url AS post_url, p.platform, p.item_id, "
        "p.product_url, p.affiliate_url, p.title FROM content_item c "
        "JOIN product p ON p.id = c.product_id WHERE c.status = 'published' AND c.published_at >= ? "
        "AND (c.status_reason IS NULL OR c.status_reason <> ?) ORDER BY c.published_at DESC",
        (since, BROKEN_MARK),
    )
    broken = []
    known = {n.id: n for n in ctx.config.niches}
    for row in rows[:MAX_CHECKS_PER_RUN]:
        niche = known.get(row["niche_id"])  # nicho removido do YAML: não confere
        if niche is None or not niche.settings.agents.broken_links:
            continue
        ok: bool | None = None
        try:
            status = ctx.price_checker.status(row) if ctx.price_checker else None
            if status is not None:
                ok = status.available
            elif ctx.link_checker is not None:
                ok = ctx.link_checker(row["post_url"])
        except Exception as exc:  # uma consulta com erro não derruba a checagem dos outros posts
            log.warning("não foi possível conferir o link", extra={"data": {"error": type(exc).__name__}})
            continue
        if ok is False:
            content_id = row["content_id"]
            ctx.db.execute(
                "UPDATE content_item SET status_reason = ?, updated_at = ? WHERE id = ?",
                (BROKEN_MARK, iso(ctx.now), content_id),
            )
            broken.append({"content_id": content_id, "niche": niche.name, "title": row["title"]})
    return broken


def broken_lines(ctx: AppContext) -> list[str]:
    try:
        broken = check_published_links(ctx)
    except Exception:
        log.exception("detector de link quebrado falhou")
        return []
    return [
        f"⚠️ [{html.escape(b['niche'])}] produto indisponível num post publicado: "
        f"{html.escape(b['title'][:50])} (post {b['content_id']}). Revise no canal."
        for b in broken
    ]
