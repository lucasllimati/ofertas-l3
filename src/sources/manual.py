"""Ofertas coladas à mão em CSV (Mercado Livre, Amazon, ou Shopee antes da API ser liberada).

Colunas: platform,item_id,title,price,price_original,image_url,affiliate_url,
         rating,reviews,sales_total,commission_rate,category
Obrigatórias: platform, title, price, affiliate_url. Linhas iniciadas por '#' são ignoradas.
"""

from __future__ import annotations

import csv
import io
from pathlib import Path

from src.common.logging import get_logger
from src.common.util import host_allowed, short_id
from src.sources.base import ROOT, Offer, allowed_domains

log = get_logger(__name__)

PLATFORMS = {"shopee", "mercadolivre", "amazon"}


def _num(value: str | None, cast=float):
    value = (value or "").strip().replace("R$", "").strip()
    if not value:
        return None
    if cast is float and "," in value:
        value = value.replace(".", "").replace(",", ".")
    try:
        return cast(float(value))
    except ValueError:
        return None


def parse_manual_csv(text: str, domains: list[str] | None = None) -> tuple[list[Offer], list[str]]:
    domains = domains or allowed_domains()
    lines = [ln for ln in text.splitlines() if ln.strip() and not ln.lstrip().startswith("#")]
    offers: list[Offer] = []
    errors: list[str] = []
    for i, row in enumerate(csv.DictReader(io.StringIO("\n".join(lines))), start=2):
        platform = (row.get("platform") or "").strip().lower()
        title = (row.get("title") or "").strip()
        url = (row.get("affiliate_url") or "").strip()
        price = _num(row.get("price"))
        if platform not in PLATFORMS:
            errors.append(f"linha {i}: platform inválida {platform!r}")
            continue
        if not title or not price or price <= 0:
            errors.append(f"linha {i}: title e price são obrigatórios")
            continue
        if not host_allowed(url, domains):
            errors.append(f"linha {i}: affiliate_url fora da allowlist de domínios")
            continue
        image = (row.get("image_url") or "").strip() or None
        if image and not image.startswith("https://"):
            image = None
        offers.append(
            Offer(
                platform=platform,
                item_id=(row.get("item_id") or "").strip() or short_id(url),
                title=title[:200],
                price=price,
                price_original=_num(row.get("price_original")),
                product_url=url,
                affiliate_url=url,
                image_url=image,
                rating=_num(row.get("rating")),
                reviews=_num(row.get("reviews"), int),
                sales_total=_num(row.get("sales_total"), int),
                commission_rate=_num(row.get("commission_rate")),
                category=(row.get("category") or "").strip() or None,
                extra={"manual": True},
            )
        )
    return offers, errors


def load_manual_offers(path: str) -> list[Offer]:
    file = Path(path) if Path(path).is_absolute() else ROOT / path
    if not file.exists():
        return []
    offers, errors = parse_manual_csv(file.read_text(encoding="utf-8-sig"))
    for err in errors:
        log.warning("oferta manual ignorada", extra={"data": {"file": file.name, "error": err}})
    return offers
