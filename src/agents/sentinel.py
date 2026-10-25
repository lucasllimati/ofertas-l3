"""Agentes Sentinela e Reciclador: usam o desempenho real dos posts (cliques e comissão).

Sentinela (relatório diário): marca, por nicho, os posts dos últimos 7 dias
- 🔥 campeões: comissão (ou cliques) >= `winner_multiplier` x a média do nicho;
- 💤 sem resultado: publicados há 3+ dias com zero pedido (e zero clique, se o /go estiver ativo).
Só avisa e sugere; não impulsiona nada sozinho.

Reciclador (Editor de pauta): devolve à pauta produtos que já geraram comissão, depois do cooldown
(`repost_cooldown_days`) e só se continuarem elegíveis hoje (preço atual, filtros e score do dia).
Ocupa até `max_share` dos posts do dia e entra com `pick_reason = recycled`.
"""

from __future__ import annotations

import html
from datetime import timedelta
from typing import Any

from src.common.util import brl, iso
from src.config.models import Niche
from src.context import AppContext

CANCELLED = ("cancelled", "canceled", "cancelado", "invalid")
QUIET_AFTER_DAYS = 3


def post_performance(ctx: AppContext, niche_id: str, days: int = 7) -> list[dict[str, Any]]:
    since = iso(ctx.now - timedelta(days=days))
    placeholders = ", ".join("?" for _ in CANCELLED)
    return ctx.db.fetchall(
        "SELECT c.id, c.product_id, c.published_at, p.title, "
        "(SELECT count(*) FROM click_event e WHERE e.content_id = c.id) AS clicks, "
        "(SELECT count(*) FROM conversion v WHERE v.content_id = c.id "
        f" AND lower(coalesce(v.status, '')) NOT IN ({placeholders})) AS orders, "
        "(SELECT coalesce(sum(v.commission), 0) FROM conversion v WHERE v.content_id = c.id "
        f" AND lower(coalesce(v.status, '')) NOT IN ({placeholders})) AS commission "
        "FROM content_item c JOIN product p ON p.id = c.product_id "
        "WHERE c.niche_id = ? AND c.status = 'published' AND c.published_at >= ?",
        (*CANCELLED, *CANCELLED, niche_id, since),
    )


def sentinel(ctx: AppContext, niche: Niche) -> dict[str, list[dict[str, Any]]]:
    posts = post_performance(ctx, niche.id)
    if not posts:
        return {"winners": [], "quiet": []}
    rules = niche.settings.agents.sentinel
    avg_comm = sum(float(p["commission"]) for p in posts) / len(posts)
    avg_clicks = sum(int(p["clicks"]) for p in posts) / len(posts)
    tracking_clicks = ctx.clicks_source is not None or any(int(p["clicks"]) for p in posts)
    winners, quiet = [], []
    quiet_before = iso(ctx.now - timedelta(days=QUIET_AFTER_DAYS))
    for p in posts:
        comm, clicks = float(p["commission"]), int(p["clicks"])
        by_money = comm > 0 and comm >= rules.winner_multiplier * avg_comm and len(posts) > 1
        by_clicks = clicks >= rules.min_clicks and clicks >= rules.winner_multiplier * max(avg_clicks, 1)
        if by_money or by_clicks:
            winners.append(p)
        elif p["published_at"] <= quiet_before and int(p["orders"]) == 0 and (not tracking_clicks or clicks == 0):
            quiet.append(p)
    winners.sort(key=lambda p: (-float(p["commission"]), -int(p["clicks"])))
    return {"winners": winners[:5], "quiet": quiet[:5]}


def sentinel_lines(ctx: AppContext) -> list[str]:
    lines: list[str] = []
    for niche in ctx.niches():
        result = sentinel(ctx, niche)
        for p in result["winners"]:
            lines.append(
                f"🔥 [{html.escape(niche.name)}] {html.escape(p['title'][:50])}: "
                f"{p['clicks']} cliques, {p['orders']} pedidos, {brl(float(p['commission']))}. Vale impulsionar."
            )
        if result["quiet"]:
            lines.append(
                f"💤 [{html.escape(niche.name)}] {len(result['quiet'])} post(s) sem nenhum resultado em 3+ dias: "
                "revise horário, nicho ou produto."
            )
    return lines


def champions(ctx: AppContext, niche: Niche) -> list[str]:
    """Produtos do nicho que geraram comissão na janela do Reciclador, do maior para o menor."""
    since = iso(ctx.now - timedelta(days=niche.settings.agents.recycle.lookback_days))
    placeholders = ", ".join("?" for _ in CANCELLED)
    rows = ctx.db.fetchall(
        "SELECT c.product_id, sum(v.commission) AS total FROM conversion v "
        "JOIN content_item c ON c.id = v.content_id "
        f"WHERE c.niche_id = ? AND v.purchase_time >= ? AND lower(coalesce(v.status, '')) NOT IN ({placeholders}) "
        "GROUP BY c.product_id HAVING sum(v.commission) > 0 ORDER BY total DESC",
        (niche.id, since, *CANCELLED),
    )
    return [r["product_id"] for r in rows]


def recycle_picks(
    ctx: AppContext, niche: Niche, eligible: list[dict[str, Any]], wanted: int
) -> list[tuple[dict[str, Any], str]]:
    """Campeões que estão elegíveis hoje (o `eligible` já exclui quem está no cooldown)."""
    rules = niche.settings.agents.recycle
    limit = int(wanted * rules.max_share)
    if not rules.enabled or limit <= 0:
        return []
    by_id = {p["id"]: p for p in eligible}
    picks = [(by_id[pid], "recycled") for pid in champions(ctx, niche) if pid in by_id]
    return picks[:limit]
