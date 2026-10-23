"""Relatório diário (Financeiro): consolidado e por nicho, no chat de admin."""

from __future__ import annotations

import html
from datetime import timedelta
from typing import Any

from src.common.util import brl, local_day_bounds_utc
from src.context import AppContext

CANCELLED = ("cancelled", "canceled", "cancelado", "invalid")


def niche_metrics(ctx: AppContext, niche_id: str, tz: str) -> dict[str, Any]:
    day = ctx.run_date
    start, end = local_day_bounds_utc(day, tz)
    start7, _ = local_day_bounds_utc(day - timedelta(days=6), tz)
    db = ctx.db
    q = db.scalar
    m: dict[str, Any] = {
        "scored": q(
            "SELECT count(*) FROM product_score WHERE niche_id = ? AND run_date = ?", (niche_id, day.isoformat())
        ),
        "eligible": q(
            "SELECT count(*) FROM product_score WHERE niche_id = ? AND run_date = ? AND eligible = 1",
            (niche_id, day.isoformat()),
        ),
        "created": q(
            "SELECT count(*) FROM content_item WHERE niche_id = ? AND run_date = ?", (niche_id, day.isoformat())
        ),
        "pending": q(
            "SELECT count(*) FROM content_item WHERE niche_id = ? AND status = 'pending_approval'", (niche_id,)
        ),
        "published": q(
            "SELECT count(*) FROM content_item WHERE niche_id = ? AND status = 'published' "
            "AND published_at >= ? AND published_at < ?",
            (niche_id, start, end),
        ),
        "clicks": q(
            "SELECT count(*) FROM click_event WHERE niche_id = ? AND ts >= ? AND ts < ?", (niche_id, start, end)
        ),
        "clicks7": q(
            "SELECT count(*) FROM click_event WHERE niche_id = ? AND ts >= ? AND ts < ?", (niche_id, start7, end)
        ),
    }
    placeholders = ", ".join("?" for _ in CANCELLED)
    for key, since in (("", start), ("7", start7)):
        row = db.fetchone(
            "SELECT count(*) AS orders, coalesce(sum(commission), 0) AS commission, "
            "coalesce(sum(amount), 0) AS gmv FROM conversion WHERE niche_id = ? "
            f"AND purchase_time >= ? AND purchase_time < ? AND lower(coalesce(status, '')) NOT IN ({placeholders})",
            (niche_id, since, end, *CANCELLED),
        )
        m[f"orders{key}"] = row["orders"]
        m[f"commission{key}"] = float(row["commission"])
        m[f"gmv{key}"] = float(row["gmv"])
    m["epc7"] = m["commission7"] / m["clicks7"] if m["clicks7"] else None
    return m


def llm_cost_today(ctx: AppContext) -> float:
    start, end = local_day_bounds_utc(ctx.run_date, ctx.config.defaults.timezone)
    return float(
        ctx.db.scalar(
            "SELECT coalesce(sum(cost_usd), 0) FROM agent_run WHERE created_at >= ? AND created_at < ?",
            (start, end),
        )
        or 0
    )


def build_report(ctx: AppContext) -> str:
    lines = [f"<b>📊 Garimpo · {ctx.run_date.strftime('%d/%m/%Y')}</b>", ""]
    total_comm = total_comm7 = 0.0
    total_clicks = total_orders = 0
    for niche in ctx.niches():
        m = niche_metrics(ctx, niche.id, niche.settings.timezone)
        total_comm += m["commission"]
        total_comm7 += m["commission7"]
        total_clicks += m["clicks"]
        total_orders += m["orders"]
        epc = brl(m["epc7"]) if m["epc7"] is not None else "-"
        lines += [
            f"<b>{html.escape(niche.name)}</b>",
            f"Produtos: {m['scored']} avaliados, {m['eligible']} elegíveis",
            f"Conteúdo: {m['created']} criados · {m['published']} publicados · {m['pending']} aguardando você",
            f"Cliques: {m['clicks']} hoje · {m['clicks7']} em 7d",
            f"Pedidos: {m['orders']} hoje · comissão {brl(m['commission'])} (7d: {brl(m['commission7'])})",
            f"EPC 7d (comissão/clique): {epc}",
            "",
        ]
    lines += [
        "<b>Total</b>",
        f"Hoje: {total_clicks} cliques · {total_orders} pedidos · {brl(total_comm)}",
        f"7 dias: {brl(total_comm7)} de comissão estimada",
        f"Custo de LLM hoje: US$ {llm_cost_today(ctx):.3f}",
        "",
        "<i>Comissão estimada: só vira confirmada quando o pedido é concluído na loja.</i>",
    ]
    failed = ctx.db.fetchall(
        "SELECT step, niche_id, detail FROM pipeline_run WHERE run_date = ? AND status = 'failed'",
        (ctx.run_date.isoformat(),),
    )
    if failed:
        lines += ["", "<b>⚠️ Falhas hoje</b>"]
        lines += [f"{f['step']} [{f['niche_id']}]: {html.escape((f['detail'] or '')[:120])}" for f in failed]
    return "\n".join(lines)


def send_report(ctx: AppContext) -> dict[str, int]:
    ctx.telegram.send_message(ctx.admin_chat_id, build_report(ctx))
    return {"sent": 1}
