"""Agentes semanais de análise (relatório de domingo e comandos do bot).

- Analista de mercado: compara todos os nichos (ativos e candidatos) pelo potencial de comissão
  do mercado e sugere qual candidato ativar, com a mudança exata no niches.yaml.
- Otimizador de horários: cruza cliques e comissão por horário de publicação e sugere
  `publish_slots` (e o cron correspondente).
- Laboratório A/B: compara as variantes de copy (A x B) por clique e comissão por post.

Só sugerem; nenhuma mudança de configuração é aplicada sozinha.
"""

from __future__ import annotations

import hashlib
import html
import json
import statistics
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from src.common.util import brl, dec, iso, parse_iso
from src.config.models import Niche
from src.context import AppContext

CANCELLED = ("cancelled", "canceled", "cancelado", "invalid")
MARKET_DAYS = 7
SLOT_DAYS = 28
AB_DAYS = 28
AB_MIN_POSTS = 10


# ------------------------------------------------------------ Analista de mercado
def market_metrics(ctx: AppContext, niche: Niche) -> dict[str, Any] | None:
    """Potencial do mercado do nicho na última semana, a partir dos produtos já pontuados todo dia."""
    since = (ctx.run_date - timedelta(days=MARKET_DAYS)).isoformat()
    latest = ctx.db.scalar(
        "SELECT max(run_date) FROM product_score WHERE niche_id = ? AND run_date >= ?", (niche.id, since)
    )
    if not latest:
        return None
    rows = ctx.db.fetchall(
        "SELECT s.score, s.components, s.eligible, p.price, p.commission_rate FROM product_score s "
        "JOIN product p ON p.id = s.product_id WHERE s.niche_id = ? AND s.run_date = ?",
        (niche.id, latest),
    )
    eligible = [r for r in rows if r["eligible"]]
    if not eligible:
        return {"niche": niche, "eligible": 0, "potential": 0.0, "avg_commission": 0.0, "avg_score": 0.0}
    weekly = []
    for r in eligible:
        sold_7d = json.loads(r["components"]).get("sales_7d") or 0
        weekly.append(float(sold_7d) * r["price"] * (r["commission_rate"] or 0))
    top = sorted(weekly, reverse=True)[:20]
    per_sale = [r["price"] * (r["commission_rate"] or 0) for r in eligible]
    return {
        "niche": niche,
        "eligible": len(eligible),
        "potential": sum(top),  # comissão semanal do mercado nos 20 melhores (se você levasse 100%)
        "avg_commission": statistics.mean(per_sale),
        "avg_score": statistics.mean(sorted((r["score"] for r in eligible), reverse=True)[:10]),
    }


def market_report(ctx: AppContext) -> list[str]:
    metrics = [m for n in ctx.niches(("active", "candidate")) if (m := market_metrics(ctx, n))]
    if not metrics:
        return ["Sem dados de mercado ainda (precisa de pelo menos 1 dia de coleta)."]
    metrics.sort(key=lambda m: -m["potential"])
    lines = ["<b>📈 Analista de mercado (7 dias)</b>"]
    for m in metrics:
        tag = "ativo" if m["niche"].is_active else "candidato"
        lines.append(
            f"{html.escape(m['niche'].name)} ({tag}): potencial {brl(m['potential'])}/sem · "
            f"comissão média {brl(m['avg_commission'])}/venda · {m['eligible']} elegíveis"
        )
    if all(m["potential"] == 0 for m in metrics):
        lines.append("O potencial precisa de 7 dias de histórico de vendas; a comparação vale a partir da 2ª semana.")
        return lines
    active = [m for m in metrics if m["niche"].is_active]
    floor = statistics.mean(m["potential"] for m in active) if active else 0.0
    best = next((m for m in metrics if not m["niche"].is_active and m["potential"] > floor), None)
    if best:
        lines.append(
            f"👉 Sugestão: ativar <b>{html.escape(best['niche'].name)}</b>. O potencial supera a média dos ativos "
            f"({brl(floor)}). Confirme por 2 semanas e siga docs/SETUP.md §16.2 (status: active)."
        )
    return lines


# ------------------------------------------------------- Otimizador de horários
def slot_stats(ctx: AppContext, niche: Niche) -> list[dict[str, Any]]:
    since = iso(ctx.now - timedelta(days=SLOT_DAYS))
    placeholders = ", ".join("?" for _ in CANCELLED)
    rows = ctx.db.fetchall(
        "SELECT c.published_at, "
        "(SELECT count(*) FROM click_event e WHERE e.content_id = c.id) AS clicks, "
        "(SELECT coalesce(sum(v.commission), 0) FROM conversion v WHERE v.content_id = c.id "
        f" AND lower(coalesce(v.status, '')) NOT IN ({placeholders})) AS commission "
        "FROM content_item c WHERE c.niche_id = ? AND c.status = 'published' AND c.published_at >= ?",
        (*CANCELLED, niche.id, since),
    )
    tz = ZoneInfo(niche.settings.timezone)
    by_hour: dict[int, dict[str, float]] = defaultdict(lambda: {"posts": 0, "clicks": 0, "commission": 0.0})
    for r in rows:
        hour = parse_iso(r["published_at"]).astimezone(tz).hour
        by_hour[hour]["posts"] += 1
        by_hour[hour]["clicks"] += int(r["clicks"])
        by_hour[hour]["commission"] += float(r["commission"])
    out = []
    for hour, s in by_hour.items():
        out.append(
            {"hour": hour, **s, "per_post": s["commission"] / s["posts"], "clicks_per_post": s["clicks"] / s["posts"]}
        )
    return sorted(out, key=lambda s: (-s["per_post"], -s["clicks_per_post"]))


def cron_for_slots(slots: list[str], tz: str) -> str:
    """Horários locais -> expressão cron em UTC (assume deslocamento fixo do fuso, como Brasília)."""
    offset = int(datetime.now(ZoneInfo(tz)).utcoffset().total_seconds() // 3600)
    hours = sorted({(int(s[:2]) - offset) % 24 for s in slots})
    minute = int(slots[0][3:]) if slots else 7
    return f'"{minute} {",".join(str(h) for h in hours)} * * *"'


def slots_report(ctx: AppContext, niche: Niche) -> list[str]:
    stats = slot_stats(ctx, niche)
    lines = [f"<b>⏰ Horários: {html.escape(niche.name)} (28 dias)</b>"]
    if sum(s["posts"] for s in stats) < 8:
        return [*lines, "Poucos posts ainda; mantenha os horários atuais."]
    for s in stats:
        lines.append(
            f"{s['hour']:02d}h: {s['posts']} posts · {dec(s['clicks_per_post'])} cliques/post · "
            f"{brl(s['per_post'])}/post"
        )
    current = niche.settings.publish_slots
    if len(stats) < len(current):
        note = f"Só {len(stats)} horário(s) com posts: dados insuficientes para trocar os {len(current)} slots."
        return [*lines, note]
    best_hours = [s["hour"] for s in stats[: len(current)]]
    suggestion = sorted(f"{h:02d}:07" for h in best_hours)
    if sorted(int(c[:2]) for c in current) != sorted(best_hours):
        lines.append(
            f"👉 Sugestão: publish_slots {suggestion} (hoje: {current}). No garimpo.yml, cron de publish "
            f"{cron_for_slots(suggestion, niche.settings.timezone)}. Só horários já testados entram na conta."
        )
    return lines


# ------------------------------------------------------------- Laboratório A/B
def ab_report(ctx: AppContext) -> list[str]:
    since = iso(ctx.now - timedelta(days=AB_DAYS))
    placeholders = ", ".join("?" for _ in CANCELLED)
    rows = ctx.db.fetchall(
        "SELECT c.niche_id, c.copy_variant, count(*) AS posts, "
        "sum((SELECT count(*) FROM click_event e WHERE e.content_id = c.id)) AS clicks, "
        "sum((SELECT coalesce(sum(v.commission), 0) FROM conversion v WHERE v.content_id = c.id "
        f" AND lower(coalesce(v.status, '')) NOT IN ({placeholders}))) AS commission "
        "FROM content_item c WHERE c.status = 'published' AND c.published_at >= ? AND c.copy_variant IS NOT NULL "
        "GROUP BY c.niche_id, c.copy_variant",
        (*CANCELLED, since),
    )
    if not rows:
        return []
    lines = ["<b>🧪 Laboratório A/B de copy (28 dias)</b>"]
    by_niche: dict[str, dict[str, dict]] = defaultdict(dict)
    for r in rows:
        by_niche[r["niche_id"]][r["copy_variant"]] = r
    for niche_id, variants in by_niche.items():
        parts = []
        for v in ("A", "B"):
            r = variants.get(v)
            if r:
                parts.append(
                    f"{v}: {r['posts']} posts, {dec(int(r['clicks'] or 0) / r['posts'])} cliques/post, "
                    f"{brl(float(r['commission'] or 0) / r['posts'])}/post"
                )
        lines.append(f"{html.escape(niche_id)}: " + " · ".join(parts))
        a, b = variants.get("A"), variants.get("B")
        if a and b and min(a["posts"], b["posts"]) >= AB_MIN_POSTS:
            pa = float(a["commission"] or 0) / a["posts"]
            pb = float(b["commission"] or 0) / b["posts"]
            if max(pa, pb) > 0 and abs(pa - pb) / max(pa, pb) >= 0.2:
                lines.append(f"👉 {niche_id}: variante {'A' if pa > pb else 'B'} vende ≥ 20% mais por post.")
    return lines


def variant_for(content_id: str, enabled: bool) -> str:
    """Divisão 50/50 determinística pelo id do post."""
    if not enabled:
        return "A"
    return "A" if hashlib.sha256(content_id.encode()).digest()[0] % 2 == 0 else "B"
