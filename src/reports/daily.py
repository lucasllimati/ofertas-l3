"""Relatório diário (Financeiro) e as seções dos agentes de análise, no chat de admin.

- todo dia: números por nicho + Calendário, Sentinela, Detector de links e Caçador de cupons;
- domingo: Analista de mercado, Otimizador de horários e Laboratório A/B;
- dia de fechamento (config/finance.yaml): Conciliador + Contador do mês anterior e o CSV."""

from __future__ import annotations

import html
from datetime import timedelta
from typing import Any
from zoneinfo import ZoneInfo

from src.agents.coupons import expiring
from src.agents.finance import (
    accountant_report,
    is_closing_day,
    load_finance,
    previous_month,
    reconcile_csv,
    reconcile_report,
)
from src.agents.insights import ab_report, market_report, slots_report
from src.agents.links import broken_lines
from src.agents.sentinel import sentinel_lines
from src.common.util import brl, iso, local_day_bounds_utc
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
    if ctx.rehearsal:
        lines += [
            "🎭 <b>Modo ensaio ativo</b>: os posts foram só para você, nenhum canal recebeu nada. "
            "Para publicar de verdade, apague a variável GARIMPO_REHEARSAL (docs/SETUP.md §13.1).",
            "",
        ]
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
    events = security_events(ctx)
    if events:
        lines += ["", "<b>🔐 Segurança (24 h)</b>"]
        lines += [f"{SECURITY_LABELS[action]}: {n}" for action, n in events.items()]
        lines.append(
            "<i>Tentativas de terceiros são bloqueadas; muitas seguidas podem indicar que o bot está sendo testado.</i>"
        )
    return "\n".join(lines)


SECURITY_LABELS = {
    "unauthorized_callback": "Botão tocado por quem não é admin",
    "invalid_signature": "Botão com assinatura inválida",
    "unauthorized_command": "Comando de quem não é admin",
    "update_failed": "Botão/comando que falhou (toque de novo)",
    "circuit_breaker": "Canal pausado por falhas seguidas",
}


def security_events(ctx: AppContext) -> dict[str, int]:
    since = iso(ctx.now - timedelta(hours=24))
    placeholders = ", ".join("?" for _ in SECURITY_LABELS)
    rows = ctx.db.fetchall(
        f"SELECT action, count(*) AS n FROM audit_log WHERE ts >= ? AND action IN ({placeholders}) GROUP BY action",
        (since, *SECURITY_LABELS),
    )
    return {r["action"]: int(r["n"]) for r in sorted(rows, key=lambda r: r["action"])}


def agents_section(ctx: AppContext) -> list[str]:
    """Agentes diários: Calendário (aviso prévio), Sentinela, Detector de links e Caçador de cupons."""
    lines: list[str] = []
    if ctx.calendar:
        today = ctx.now.astimezone(ZoneInfo(ctx.config.defaults.timezone)).date()
        for event, days in ctx.calendar.upcoming(today):
            lines.append(
                f"📅 Em {days} dia(s): <b>{html.escape(event.name)}</b> ({event.start.strftime('%d/%m')}). "
                "Prepare ofertas de ML/Amazon no CSV e cupons em config/coupons.csv."
            )
        for niche in ctx.niches():
            active = ctx.calendar.active(today, niche.id)
            if active:
                names = ", ".join(e.name for e in active)
                lines.append(f"🏷 {html.escape(niche.name)}: em {html.escape(names)} (mais posts e selo na arte).")
    lines += sentinel_lines(ctx)
    lines += broken_lines(ctx)
    if ctx.coupons:
        for c in expiring(ctx.coupons, ctx.now):
            lines.append(f"🎟 Cupom {html.escape(c.code)} ({c.platform}) vence em menos de 24 h.")
    return (["<b>🧭 Agentes</b>", *lines]) if lines else []


def weekly_section(ctx: AppContext) -> list[str]:
    """Domingo: Analista de mercado, Otimizador de horários e Laboratório A/B."""
    lines = market_report(ctx)
    for niche in ctx.niches():
        lines += ["", *slots_report(ctx, niche)]
    ab = ab_report(ctx)
    if ab:
        lines += ["", *ab]
    return lines


def chunks(lines: list[str], limit: int = 3900) -> list[str]:
    """Divide em mensagens de até ~4.000 caracteres (limite do Telegram), sem cortar linhas."""
    out, current = [], ""
    for line in lines:
        if current and len(current) + len(line) + 1 > limit:
            out.append(current)
            current = ""
        current = f"{current}\n{line}" if current else line
    if current:
        out.append(current)
    return out


def send_monthly_close(ctx: AppContext, month: str | None = None) -> dict[str, int]:
    """Conciliador + Contador do mês (padrão: mês anterior) e o CSV para a contabilidade."""
    ym = month or previous_month(ctx)
    cfg = load_finance()
    lines = [*reconcile_report(ctx, ym, cfg), "", *accountant_report(ctx, ym, cfg)]
    for text in chunks(lines):
        ctx.telegram.send_message(ctx.admin_chat_id, text)
    ctx.telegram.send_document(
        ctx.admin_chat_id, f"fechamento-{ym}.csv", reconcile_csv(ctx, ym, cfg), f"Fechamento {ym} (para o contador)"
    )
    return {"month_closed": 1}


def send_report(ctx: AppContext) -> dict[str, int]:
    messages = [build_report(ctx)]
    extra = agents_section(ctx)
    if extra:
        messages += chunks(extra)
    local = ctx.now.astimezone(ZoneInfo(ctx.config.defaults.timezone))
    if local.weekday() == 6:  # domingo
        messages += chunks(weekly_section(ctx))
    for text in messages:
        ctx.telegram.send_message(ctx.admin_chat_id, text)
    closed = send_monthly_close(ctx)["month_closed"] if is_closing_day(ctx) else 0
    return {"sent": len(messages), "month_closed": closed}
