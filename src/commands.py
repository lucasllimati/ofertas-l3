"""Comandos do bot (só do admin, só no chat de admin). Respostas chegam na próxima execução."""

from __future__ import annotations

import html
import re
from typing import Any

from src.agents.coupons import valid_for_niche
from src.agents.finance import accountant_report, current_month, load_finance, previous_month
from src.agents.insights import market_report, slots_report
from src.approval import audit
from src.common.util import brl, iso
from src.context import AppContext

HELP = (
    "<b>Comandos</b>\n"
    "/status: fila de conteúdo por nicho\n"
    "/top &lt;nicho&gt;: 10 melhores produtos do dia\n"
    "/pausar &lt;nicho&gt; &lt;canal&gt;: para de publicar\n"
    "/retomar &lt;nicho&gt; &lt;canal&gt;: volta a publicar\n"
    "/imposto [AAAA-MM]: Contador (imposto estimado, como dividir o dinheiro, riscos)\n"
    "/fechamento [AAAA-MM]: Conciliador + Contador e o CSV para a contabilidade\n"
    "/mercado: Analista de mercado (qual nicho ativar)\n"
    "/horarios &lt;nicho&gt;: Otimizador de horários\n"
    "/cupons: cupons válidos agora"
)
MONTH_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
CHANNELS = {"telegram", "instagram", "tiktok"}


def set_paused(ctx: AppContext, niche_id: str, channel: str, paused: bool) -> None:
    ctx.db.execute(
        "INSERT INTO channel_state (niche_id, channel, paused, consecutive_failures, updated_at) "
        "VALUES (?, ?, ?, 0, ?) ON CONFLICT (niche_id, channel) DO UPDATE SET "
        "paused = excluded.paused, consecutive_failures = 0, updated_at = excluded.updated_at",
        (niche_id, channel, int(paused), iso(ctx.now)),
    )


def status_text(ctx: AppContext) -> str:
    lines = ["<b>Status</b>"]
    for niche in ctx.niches():
        rows = ctx.db.fetchall(
            "SELECT status, count(*) AS n FROM content_item WHERE niche_id = ? AND run_date >= ? GROUP BY status",
            (niche.id, ctx.run_date.isoformat()),
        )
        counts = ", ".join(f"{r['status']}={r['n']}" for r in rows) or "nada hoje"
        paused = ctx.db.fetchall("SELECT channel FROM channel_state WHERE niche_id = ? AND paused = 1", (niche.id,))
        flag = f" ⏸ {', '.join(p['channel'] for p in paused)}" if paused else ""
        lines.append(f"{html.escape(niche.name)}: {counts}{flag}")
    return "\n".join(lines)


def top_text(ctx: AppContext, niche_id: str) -> str:
    rows = ctx.db.fetchall(
        "SELECT p.title, p.price, s.score FROM product_score s JOIN product p ON p.id = s.product_id "
        "WHERE s.niche_id = ? AND s.run_date = (SELECT max(run_date) FROM product_score "
        "WHERE niche_id = ?) AND s.eligible = 1 ORDER BY s.rank LIMIT 10",
        (niche_id, niche_id),
    )
    if not rows:
        return f"Sem score para {html.escape(niche_id)}."
    body = "\n".join(
        f"{i}. {html.escape(r['title'][:60])} · {brl(r['price'])} · {r['score']:.2f}" for i, r in enumerate(rows, 1)
    )
    return f"<b>Top {html.escape(niche_id)}</b>\n{body}"


def coupons_text(ctx: AppContext) -> str:
    lines = ["<b>🎟 Cupons válidos agora</b>"]
    for niche in ctx.niches():
        for c in valid_for_niche(ctx.coupons, niche, ctx.now):
            lines.append(f"{html.escape(niche.name)}: {c.caption_line(niche.settings.timezone)}")
    if len(lines) == 1:
        lines.append("Nenhum. Cole cupons em config/coupons.csv.")
    return "\n".join(lines)


def handle_command(ctx: AppContext, message: dict[str, Any]) -> bool:
    text = (message.get("text") or "").strip()
    user_id = (message.get("from") or {}).get("id")
    chat_id = str((message.get("chat") or {}).get("id"))
    if not text.startswith("/"):
        return False
    if user_id not in ctx.admin_user_ids or chat_id != str(ctx.admin_chat_id):
        audit(ctx, f"tg:{user_id}", "unauthorized_command", None, {"command": text.split()[0][:32]})
        return False
    parts = text.split()
    cmd = parts[0].split("@")[0].lower()
    known = {n.id for n in ctx.config.niches}
    month = parts[1] if len(parts) == 2 and MONTH_RE.match(parts[1]) else None
    reply: str
    if cmd == "/fechamento":
        from src.reports.daily import send_monthly_close  # import tardio: o relatório importa este módulo

        send_monthly_close(ctx, month or previous_month(ctx))
        return True
    if cmd == "/imposto":
        reply = "\n".join(accountant_report(ctx, month or current_month(ctx), load_finance()))
    elif cmd == "/mercado":
        reply = "\n".join(market_report(ctx))
    elif cmd == "/horarios" and len(parts) == 2 and parts[1] in known:
        reply = "\n".join(slots_report(ctx, ctx.config.niche(parts[1])))
    elif cmd == "/cupons":
        reply = coupons_text(ctx)
    elif cmd == "/status":
        reply = status_text(ctx)
    elif cmd == "/top" and len(parts) == 2 and parts[1] in known:
        reply = top_text(ctx, parts[1])
    elif cmd in ("/pausar", "/retomar") and len(parts) == 3 and parts[1] in known and parts[2] in CHANNELS:
        paused = cmd == "/pausar"
        set_paused(ctx, parts[1], parts[2], paused)
        audit(ctx, f"tg:{user_id}", "pause" if paused else "resume", f"{parts[1]}:{parts[2]}")
        reply = f"{'⏸ Pausado' if paused else '▶️ Retomado'}: {parts[1]} / {parts[2]}"
    else:
        reply = HELP
    ctx.telegram.send_message(ctx.admin_chat_id, reply)
    return True
