"""Publicador determinístico do Telegram.

Garantias:
- só publica `approved` com scheduled_for <= agora, dentro do limite diário do nicho;
- "reivindica" o item (approved -> publishing) antes de enviar: reexecução nunca duplica;
- erro confirmado da API volta o item para `approved`; erro ambíguo (rede) vira
  `publish_unknown` e gera alerta, para você conferir no canal antes de republicar;
- circuit breaker: N falhas seguidas pausam o canal do nicho.
"""

from __future__ import annotations

import html
from datetime import timedelta

from src.agents import price_guard
from src.agents.coupons import still_valid
from src.agents.seasonal import scaled
from src.approval import audit, product_for, render_for
from src.common.logging import get_logger
from src.common.telegram import TelegramError
from src.common.util import iso, local_day_bounds_utc, local_today
from src.config.models import Niche
from src.context import AppContext
from src.pipeline.content import drop_expired_coupon, rebuild_for_price

log = get_logger(__name__)

CHANNEL = "telegram"
CIRCUIT_BREAKER_FAILURES = 3
STALE_AFTER_DAYS = 2


def channel_state(ctx: AppContext, niche_id: str) -> dict:
    row = ctx.db.fetchone(
        "SELECT paused, consecutive_failures FROM channel_state WHERE niche_id = ? AND channel = ?",
        (niche_id, CHANNEL),
    )
    return row or {"paused": 0, "consecutive_failures": 0}


def _set_failures(ctx: AppContext, niche_id: str, failures: int, paused: bool) -> None:
    ctx.db.execute(
        "INSERT INTO channel_state (niche_id, channel, paused, consecutive_failures, updated_at) "
        "VALUES (?, ?, ?, ?, ?) ON CONFLICT (niche_id, channel) DO UPDATE SET "
        "paused = excluded.paused, consecutive_failures = excluded.consecutive_failures, "
        "updated_at = excluded.updated_at",
        (niche_id, CHANNEL, int(paused), failures, iso(ctx.now)),
    )


def alert(ctx: AppContext, text: str) -> None:
    try:
        ctx.telegram.send_message(ctx.admin_chat_id, f"⚠️ {text}")
    except Exception:
        log.error("falha ao enviar alerta", extra={"data": {"alert": text[:200]}})


def expire_stale(ctx: AppContext, niche: Niche) -> int:
    """Aprovado e não publicado há dias: o preço provavelmente mudou. Não publica mais."""
    cutoff_day = (ctx.run_date - timedelta(days=STALE_AFTER_DAYS)).isoformat()
    return ctx.db.execute(
        "UPDATE content_item SET status = 'expired', updated_at = ? WHERE niche_id = ? "
        "AND status IN ('approved', 'pending_approval', 'ready') AND run_date < ?",
        (iso(ctx.now), niche.id, cutoff_day),
    )


def publish_niche(ctx: AppContext, niche: Niche) -> dict[str, int]:
    expired = expire_stale(ctx, niche)
    channel = niche.channels.telegram
    if not channel or not channel.enabled:
        return {"published": 0, "expired": expired}
    state = channel_state(ctx, niche.id)
    if state["paused"]:
        return {"published": 0, "expired": expired, "paused": 1}
    chat_id = ctx.channel_chat_id(niche)
    if not chat_id:
        raise RuntimeError(f"{channel.channel_ref}_CHAT_ID não configurado")

    tz = niche.settings.timezone
    start, end = local_day_bounds_utc(local_today(tz, ctx.now), tz)
    published_today = int(
        ctx.db.scalar(
            "SELECT count(*) FROM content_item WHERE niche_id = ? AND channel = ? "
            "AND status IN ('published', 'publishing', 'publish_unknown') "
            "AND published_at >= ? AND published_at < ?",
            (niche.id, CHANNEL, start, end),
        )
        or 0
    )
    daily_limit = niche.settings.limits.posts_per_day.telegram
    if ctx.calendar:  # Calendário sazonal: o limite de publicação acompanha o volume do evento
        daily_limit = scaled(daily_limit, ctx.calendar.multiplier(local_today(tz, ctx.now), niche.id))
    budget = daily_limit - published_today
    if budget <= 0:
        return {"published": 0, "expired": expired}

    due = ctx.db.fetchall(
        "SELECT * FROM content_item WHERE niche_id = ? AND channel = ? AND status = 'approved' "
        "AND scheduled_for <= ? ORDER BY scheduled_for, score DESC",
        (niche.id, CHANNEL, iso(ctx.now)),
    )
    published = 0
    guarded: list[str] = []
    failures = int(state["consecutive_failures"])
    for item in due[:budget]:
        claimed = ctx.db.execute(
            "UPDATE content_item SET status = 'publishing', published_at = ?, updated_at = ? "
            "WHERE id = ? AND status = 'approved'",
            (iso(ctx.now), iso(ctx.now), item["id"]),
        )
        if claimed != 1:
            continue
        # Vigia de preço e estoque: reconsulta logo antes de enviar.
        guard = niche.settings.agents.price_guard
        if guard.enabled:
            decision = price_guard.check(
                ctx.price_checker, product_for(ctx, item["product_id"]), item["price_at_creation"], guard.tolerance_pct
            )
            if decision.action == "unavailable":
                ctx.db.execute(
                    "UPDATE content_item SET status = 'unavailable', published_at = NULL, status_reason = ?, "
                    "updated_at = ? WHERE id = ?",
                    (decision.reason, iso(ctx.now), item["id"]),
                )
                audit(ctx, "system", "price_guard_unavailable", item["id"], {"reason": decision.reason})
                guarded.append(f"⛔ post {item['id']}: {decision.reason}. Não publicado.")
                continue
            if decision.action == "reapprove":
                rebuild_for_price(ctx, niche, item, decision.new_price, decision.reason)
                audit(ctx, "system", "price_guard_reapprove", item["id"], {"reason": decision.reason})
                guarded.append(f"🔁 post {item['id']}: {decision.reason}. Nova prévia para reaprovar.")
                continue
        # Caçador de cupons: cupom venceu depois da aprovação -> sai da legenda, post segue.
        if item.get("coupon_code") and not still_valid(ctx.coupons, item["coupon_code"], ctx.now):
            item = {**item, "caption": drop_expired_coupon(ctx, niche, item)}
        try:
            photo = item["media_file_id"] or render_for(ctx, niche, item)
        except Exception:
            # Falhou antes de enviar: com certeza não saiu. Volta para a fila em vez de "não sei se saiu".
            log.exception("arte não gerada; post volta para a fila", extra={"data": {"content": item["id"]}})
            ctx.db.execute(
                "UPDATE content_item SET status = 'approved', published_at = NULL, updated_at = ? WHERE id = ?",
                (iso(ctx.now), item["id"]),
            )
            continue
        try:
            msg = ctx.telegram.send_photo(chat_id, photo, item["caption"])
        except TelegramError as exc:
            failures += 1
            ctx.db.execute(
                "UPDATE content_item SET status = 'approved', published_at = NULL, updated_at = ? WHERE id = ?",
                (iso(ctx.now), item["id"]),
            )
            tripped = failures >= CIRCUIT_BREAKER_FAILURES
            _set_failures(ctx, niche.id, failures, tripped)
            log.warning("publicação falhou", extra={"data": {"content": item["id"], "error": str(exc)}})
            if tripped:
                audit(ctx, "system", "circuit_breaker", f"{niche.id}:{CHANNEL}", {"error": str(exc)})
                alert(
                    ctx,
                    f"{html.escape(niche.name)}: {failures} falhas seguidas no Telegram. Canal pausado. "
                    f"Último erro: {html.escape(str(exc))}. Corrija e use /retomar {niche.id} telegram",
                )
                break
            continue
        except Exception as exc:
            ctx.db.execute(
                "UPDATE content_item SET status = 'publish_unknown', updated_at = ? WHERE id = ?",
                (iso(ctx.now), item["id"]),
            )
            alert(
                ctx,
                f"{html.escape(niche.name)}: não sei se o post {item['id']} saiu ({type(exc).__name__}). "
                "Confira o canal; ele não será reenviado automaticamente.",
            )
            continue
        ctx.db.execute(
            "UPDATE content_item SET status = 'published', external_id = ?, updated_at = ? WHERE id = ?",
            (str(msg["message_id"]), iso(ctx.now), item["id"]),
        )
        failures = 0
        _set_failures(ctx, niche.id, 0, False)
        published += 1
    if guarded:  # um aviso só com tudo que o Vigia de preço segurou nesta execução
        body = "\n".join(html.escape(g) for g in guarded)
        alert(ctx, f"{html.escape(niche.name)} · Vigia de preço:\n{body}")
    return {"published": published, "expired": expired, "price_guard": len(guarded)}
