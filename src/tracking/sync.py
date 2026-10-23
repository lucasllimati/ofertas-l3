"""Cliques (D1 -> click_event) e conversões (Shopee / CSV -> conversion)."""

from __future__ import annotations

import csv
import io
import json
from datetime import timedelta
from pathlib import Path

from src.common.logging import get_logger
from src.common.util import iso
from src.context import AppContext
from src.pipeline.content import CODE_CHANNEL
from src.sources.base import ConversionRecord

log = get_logger(__name__)

CLICK_WATERMARK_KEY = "d1_click_watermark"
CONVERSION_LOOKBACK_DAYS = 14  # status muda (pendente -> concluído/cancelado): reimporta a janela
D1_RETENTION_DAYS = 7


def _set_state(ctx: AppContext, key: str, value: str) -> None:
    ctx.db.execute(
        "INSERT INTO kv_state (key, value, updated_at) VALUES (?, ?, ?) ON CONFLICT (key) "
        "DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at",
        (key, value, iso(ctx.now)),
    )


def sync_clicks(ctx: AppContext) -> dict[str, int]:
    if not ctx.clicks_source:
        return {"clicks": 0, "skipped": 1}
    row = ctx.db.fetchone("SELECT value FROM kv_state WHERE key = ?", (CLICK_WATERMARK_KEY,))
    watermark = int(row["value"]) if row else 0
    total = 0
    known_niches = {n.id for n in ctx.config.niches}
    for _ in range(20):
        rows = ctx.clicks_source.fetch(watermark)
        if not rows:
            break
        with ctx.db.transaction():
            ctx.db.executemany(
                "INSERT INTO click_event (id, ts, niche_id, channel, content_id, country) "
                "VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT (id) DO NOTHING",
                [
                    (
                        f"d1:{r['id']}",
                        r["ts"],
                        r["niche"],
                        CODE_CHANNEL.get(r["channel"], r["channel"]),
                        r.get("content_id"),
                        r.get("country"),
                    )
                    for r in rows
                    if r.get("niche") in known_niches
                ],
            )
            watermark = max(int(r["id"]) for r in rows)
            _set_state(ctx, CLICK_WATERMARK_KEY, str(watermark))
        total += len(rows)
    if watermark:
        ctx.clicks_source.purge(watermark, iso(ctx.now - timedelta(days=D1_RETENTION_DAYS)))
    return {"clicks": total}


def attribute(ctx: AppContext, sub_ids: list[str]) -> tuple[str | None, str | None, str | None]:
    """subIds = [<sub_id do nicho>, <canal>, <content_id>]."""
    niche = ctx.config.by_sub_id(sub_ids[0]) if sub_ids else None
    channel = CODE_CHANNEL.get(sub_ids[1]) if len(sub_ids) > 1 else None
    content_id = sub_ids[2] if len(sub_ids) > 2 else None
    if content_id and not ctx.db.fetchone("SELECT 1 AS x FROM content_item WHERE id = ?", (content_id,)):
        content_id = None
    return (niche.id if niche else None), channel, content_id


def store_conversions(ctx: AppContext, records: list[ConversionRecord]) -> int:
    rows = []
    for r in records:
        niche_id, channel, content_id = attribute(ctx, r.sub_ids)
        rows.append(
            (
                f"{r.platform}:{r.conversion_id}:{r.order_id}:{r.item_id}",
                r.platform,
                r.order_id,
                r.item_id,
                niche_id,
                channel,
                content_id,
                r.purchase_time,
                r.status,
                r.amount,
                r.commission,
                json.dumps(r.raw, ensure_ascii=False),
                iso(ctx.now),
            )
        )
    with ctx.db.transaction():
        ctx.db.executemany(
            "INSERT INTO conversion (id, platform, order_id, item_id, niche_id, channel, content_id, "
            "purchase_time, status, amount, commission, raw, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT (id) DO UPDATE SET "
            "status = excluded.status, amount = excluded.amount, commission = excluded.commission, "
            "raw = excluded.raw, updated_at = excluded.updated_at",
            rows,
        )
    return len(rows)


def sync_conversions(ctx: AppContext) -> dict[str, int]:
    if not ctx.conversions_source:
        return {"conversions": 0, "skipped": 1}
    end = int(ctx.now.timestamp())
    start = int((ctx.now - timedelta(days=CONVERSION_LOOKBACK_DAYS)).timestamp())
    return {"conversions": store_conversions(ctx, ctx.conversions_source.conversions(start, end))}


def import_conversions_csv(ctx: AppContext, path: Path) -> dict[str, int]:
    """CSV exportado do painel (ML/Amazon): platform,order_id,item_id,purchase_time,status,amount,commission,sub_id
    sub_id no formato <nicho>-<canal>-<content_id> (ex.: casa-tg-ab12cd34ef)."""
    records = []
    for row in csv.DictReader(io.StringIO(path.read_text(encoding="utf-8-sig"))):
        records.append(
            ConversionRecord(
                platform=(row.get("platform") or "manual").strip(),
                conversion_id="csv",
                order_id=(row.get("order_id") or "").strip(),
                item_id=(row.get("item_id") or "").strip(),
                purchase_time=(row.get("purchase_time") or iso(ctx.now)).strip(),
                status=(row.get("status") or "").strip(),
                amount=float(row.get("amount") or 0),
                commission=float(row.get("commission") or 0),
                sub_ids=[s for s in (row.get("sub_id") or "").split("-") if s],
            )
        )
    return {"conversions": store_conversions(ctx, records)}
