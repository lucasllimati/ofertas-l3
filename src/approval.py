"""Humano no loop: prévias no Telegram com botões assinados (HMAC) e processamento das respostas.

Nesta versão as respostas são lidas por getUpdates no início de cada execução agendada
(ver docs/adr/0002). Por isso o botão só "responde" na próxima execução.
"""

from __future__ import annotations

import hashlib
import hmac
import html
import json
from datetime import date, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from src.common.logging import get_logger
from src.common.telegram import TelegramError, largest_photo_id
from src.common.util import iso, local_today, parse_iso, random_id, slot_to_utc
from src.config.models import Niche
from src.content.brand import load_brand
from src.content.render import render_post
from src.context import AppContext

log = get_logger(__name__)

ACTIONS = {"a": "approve", "r": "reject", "s": "reschedule"}
APPROVAL_MAX_AGE = timedelta(hours=72)
OFFSET_KEY = "telegram_update_offset"


# ------------------------------------------------------------------ assinatura
def _sig(secret: str, action: str, content_id: str) -> str:
    mac = hmac.new(secret.encode(), f"{action}:{content_id}".encode(), hashlib.sha256)
    return mac.hexdigest()[:16]


def sign_callback(secret: str, action: str, content_id: str) -> str:
    return f"{action}:{content_id}:{_sig(secret, action, content_id)}"  # <= 64 bytes


def verify_callback(secret: str, data: str) -> tuple[str, str] | None:
    parts = data.split(":")
    if len(parts) != 3 or parts[0] not in ACTIONS or not secret:
        return None
    action, content_id, sig = parts
    if not hmac.compare_digest(sig, _sig(secret, action, content_id)):
        return None
    return action, content_id


def keyboard(secret: str, content_id: str) -> dict[str, Any]:
    return {
        "inline_keyboard": [
            [
                {"text": "✅ Aprovar", "callback_data": sign_callback(secret, "a", content_id)},
                {"text": "❌ Rejeitar", "callback_data": sign_callback(secret, "r", content_id)},
                {"text": "⏭ Próximo horário", "callback_data": sign_callback(secret, "s", content_id)},
            ]
        ]
    }


def audit(ctx: AppContext, actor: str, action: str, target: str | None, detail: dict | None = None) -> None:
    ctx.db.execute(
        "INSERT INTO audit_log (id, ts, actor, action, target, detail) VALUES (?, ?, ?, ?, ?, ?)",
        (random_id(), iso(ctx.now), actor, action, target, json.dumps(detail or {}, ensure_ascii=False)),
    )


# --------------------------------------------------------------------- prévias
def product_for(ctx: AppContext, product_id: str) -> dict[str, Any]:
    return ctx.db.fetchone("SELECT * FROM product WHERE id = ?", (product_id,)) or {}


def render_for(ctx: AppContext, niche: Niche, item: dict[str, Any]) -> bytes:
    product = product_for(ctx, item["product_id"])
    # A arte usa exatamente os preços validados da legenda, nunca o "de" bruto do vendedor.
    product["price"] = item["price_at_creation"]
    product["price_original"] = item.get("price_original_shown")
    image = ctx.image_fetcher(product.get("image_url")) if ctx.image_fetcher else None
    png = render_post(product, load_brand(niche), date.fromisoformat(item["run_date"]), image)
    if ctx.demo:
        path = ctx.out_dir / "media" / item["run_date"] / niche.id / f"{item['id']}.png"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(png)
    return png


def send_previews(ctx: AppContext, niche: Niche) -> dict[str, int]:
    items = ctx.db.fetchall(
        "SELECT * FROM content_item WHERE niche_id = ? AND status = 'ready' ORDER BY scheduled_for",
        (niche.id,),
    )
    settings = niche.settings
    sent = auto = 0
    for item in items:
        png = render_for(ctx, niche, item)
        auto_ok = settings.approval == "auto_above_score" and item["score"] >= settings.auto_approve_min_score
        local_slot = parse_iso(item["scheduled_for"]).astimezone(ZoneInfo(settings.timezone)).strftime("%d/%m %H:%M")
        header = (
            f"<b>[{html.escape(niche.name)}]</b> score {item['score']:.2f} · {item['pick_reason']} · "
            f"{'copy LLM' if item['copy_source'] == 'llm' else 'copy template'} · slot {local_slot}\n"
            f"{'🤖 autoaprovado' if auto_ok else 'Aprovar para publicar no canal:'}\n\n"
        )
        caption = header + item["caption"]
        if len(caption) > 1024:
            caption = header + "(legenda completa será publicada)"
        msg = ctx.telegram.send_photo(
            ctx.admin_chat_id, png, caption, None if auto_ok else keyboard(ctx.hmac_secret, item["id"])
        )
        new_status = "approved" if auto_ok else "pending_approval"
        ctx.db.execute(
            "UPDATE content_item SET status = ?, preview_message_id = ?, media_file_id = ?, "
            "updated_at = ? WHERE id = ? AND status = 'ready'",
            (new_status, str(msg["message_id"]), largest_photo_id(msg), iso(ctx.now), item["id"]),
        )
        if auto_ok:
            audit(ctx, "system", "auto_approve", item["id"], {"score": item["score"]})
            auto += 1
        else:
            sent += 1
    return {"previews": sent, "auto_approved": auto}


# -------------------------------------------------------------------- respostas
def next_slot(ctx: AppContext, niche: Niche, after_iso: str) -> str:
    after = max(parse_iso(after_iso), ctx.now)
    day = local_today(niche.settings.timezone, after)
    for offset in range(0, 3):
        for slot in niche.settings.publish_slots:
            candidate = slot_to_utc(day + timedelta(days=offset), slot, niche.settings.timezone)
            if candidate > after:
                return iso(candidate)
    return iso(after + timedelta(hours=4))


def handle_callback(ctx: AppContext, query: dict[str, Any]) -> str:
    user_id = (query.get("from") or {}).get("id")
    if user_id not in ctx.admin_user_ids:
        audit(ctx, f"tg:{user_id}", "unauthorized_callback", None)
        return "ignored"
    parsed = verify_callback(ctx.hmac_secret, query.get("data", ""))
    if not parsed:
        audit(ctx, f"tg:{user_id}", "invalid_signature", None)
        return "invalid"
    action, content_id = parsed
    item = ctx.db.fetchone("SELECT * FROM content_item WHERE id = ?", (content_id,))
    if not item:
        return "missing"
    niche = ctx.config.niche(item["niche_id"])
    if ctx.now - parse_iso(item["created_at"]) > APPROVAL_MAX_AGE:
        ctx.db.execute(
            "UPDATE content_item SET status = 'expired', updated_at = ? WHERE id = ? "
            "AND status IN ('pending_approval', 'ready')",
            (iso(ctx.now), content_id),
        )
        result = "expired"
    elif action == "a":
        changed = ctx.db.execute(
            "UPDATE content_item SET status = 'approved', updated_at = ? WHERE id = ? AND status = 'pending_approval'",
            (iso(ctx.now), content_id),
        )
        result = "approved" if changed else f"no-op ({item['status']})"
    elif action == "r":
        changed = ctx.db.execute(
            "UPDATE content_item SET status = 'rejected', updated_at = ? WHERE id = ? "
            "AND status IN ('pending_approval', 'approved')",
            (iso(ctx.now), content_id),
        )
        result = "rejected" if changed else f"no-op ({item['status']})"
    else:
        new_slot = next_slot(ctx, niche, item["scheduled_for"])
        changed = ctx.db.execute(
            "UPDATE content_item SET status = 'approved', scheduled_for = ?, updated_at = ? "
            "WHERE id = ? AND status IN ('pending_approval', 'approved')",
            (new_slot, iso(ctx.now), content_id),
        )
        result = f"rescheduled {new_slot}" if changed else f"no-op ({item['status']})"
    audit(ctx, f"tg:{user_id}", f"callback_{ACTIONS[action]}", content_id, {"result": result})
    _ack(ctx, query, result)
    return result


def _ack(ctx: AppContext, query: dict[str, Any], result: str) -> None:
    labels = {"approved": "✅ aprovado", "rejected": "❌ rejeitado", "expired": "⌛ expirado"}
    label = labels.get(result, "⏭ reagendado" if result.startswith("rescheduled") else result)
    try:
        ctx.telegram.answer_callback(query["id"], label)
    except (TelegramError, ConnectionError):
        pass  # callback antigo (o Telegram expira em poucos minutos): sem problema
    message = query.get("message") or {}
    try:
        ctx.telegram.edit_reply_markup(
            str((message.get("chat") or {}).get("id")),
            str(message.get("message_id")),
            {"inline_keyboard": [[{"text": label, "callback_data": "noop"}]]},
        )
    except (TelegramError, ConnectionError):
        pass


def _notify_failure(ctx: AppContext) -> None:
    try:
        ctx.telegram.send_message(
            ctx.admin_chat_id, "⚠️ Não consegui processar um botão ou comando. Se era uma aprovação, toque de novo."
        )
    except Exception:
        log.warning("aviso de falha não enviado")


def process_updates(ctx: AppContext) -> dict[str, int]:
    from src.commands import handle_command

    row = ctx.db.fetchone("SELECT value FROM kv_state WHERE key = ?", (OFFSET_KEY,))
    offset = int(row["value"]) if row else None
    counts = {"callbacks": 0, "commands": 0}
    for _ in range(10):  # até 1000 updates por execução
        updates = ctx.telegram.get_updates(offset)
        if not updates:
            break
        for update in updates:
            try:
                if "callback_query" in update:
                    handle_callback(ctx, update["callback_query"])
                    counts["callbacks"] += 1
                elif "message" in update:
                    if handle_command(ctx, update["message"]):
                        counts["commands"] += 1
            except Exception as exc:
                # Sem isso, uma única atualização com erro travaria a fila para sempre (o offset não
                # avançaria). O botão continua na mensagem: basta tocar de novo.
                counts["failed"] = counts.get("failed", 0) + 1
                log.exception("atualização do Telegram falhou; seguindo para a próxima")
                audit(ctx, "system", "update_failed", str(update.get("update_id")), {"error": type(exc).__name__})
                _notify_failure(ctx)
            offset = int(update["update_id"]) + 1
            ctx.db.execute(
                "INSERT INTO kv_state (key, value, updated_at) VALUES (?, ?, ?) "
                "ON CONFLICT (key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at",
                (OFFSET_KEY, str(offset), iso(ctx.now)),
            )
        if len(updates) < 100:
            break
    return counts
