"""Agente Caçador de cupons.

Cupons válidos ficam em config/coupons.csv (você cola os do painel de afiliados, newsletters ou
páginas oficiais das lojas; nada é raspado de sites). O agente:
- valida cada cupom pelas regras do nicho (`coupons`: desconto mínimo em % ou R$, horas restantes);
- escolhe o melhor cupom que vale para o produto (loja, nicho, compra mínima) e põe na legenda;
- tira o cupom da legenda na publicação se ele venceu no meio do caminho;
- lista no relatório os cupons ativos e os que vencem em 24 h.

Colunas: platform,code,description,discount_pct,discount_brl,min_purchase,valid_until,niches
`valid_until` em `AAAA-MM-DD HH:MM` ou `dd/mm/aaaa HH:MM` (horário de Brasília); `niches` separado por `;`
(vazio = todos).
"""

from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from src.common.logging import get_logger
from src.common.util import brl, parse_money
from src.config.models import Niche

log = get_logger(__name__)

ROOT = Path(__file__).resolve().parents[2]
COUPONS_PATH = ROOT / "config" / "coupons.csv"
CODE_RE = re.compile(r"^[A-Z0-9]{3,20}$")
PLATFORMS = {"shopee", "mercadolivre", "amazon"}
UNTIL_FORMATS = ("%Y-%m-%d %H:%M", "%d/%m/%Y %H:%M")


@dataclass
class Coupon:
    platform: str
    code: str
    description: str
    discount_pct: float
    discount_brl: float
    min_purchase: float
    valid_until: datetime
    niches: list[str]

    def applies(self, platform: str, niche_id: str, price: float) -> bool:
        return self.platform == platform and (not self.niches or niche_id in self.niches) and price >= self.min_purchase

    def savings(self, price: float) -> float:
        return max(price * self.discount_pct / 100, self.discount_brl)

    def caption_line(self, tz: str) -> str:
        until = self.valid_until.astimezone(ZoneInfo(tz)).strftime("%d/%m %H:%M")
        what = f"{self.discount_pct:.0f}% off" if self.discount_pct else f"{brl(self.discount_brl)} off"
        extra = f" em compras a partir de {brl(self.min_purchase)}" if self.min_purchase else ""
        return f"🎟 Cupom <b>{self.code}</b>: {what}{extra} (até {until})"


def parse_until(value: str) -> datetime:
    for fmt in UNTIL_FORMATS:
        try:
            return datetime.strptime(value.strip(), fmt)
        except ValueError:
            pass
    raise ValueError(f"valid_until inválido {value.strip()!r} (use AAAA-MM-DD HH:MM ou dd/mm/aaaa HH:MM)")


def parse_coupons(text: str, tz: str) -> tuple[list[Coupon], list[str]]:
    lines = [ln for ln in text.splitlines() if ln.strip() and not ln.lstrip().startswith("#")]
    coupons, errors = [], []
    for n, row in enumerate(csv.DictReader(io.StringIO("\n".join(lines))), start=2):
        try:
            platform = (row.get("platform") or "").strip().lower()
            code = (row.get("code") or "").strip().upper()
            if platform not in PLATFORMS:
                raise ValueError(f"platform inválida {platform!r}")
            if not CODE_RE.match(code):
                raise ValueError("código deve ter 3 a 20 letras/números")
            until = parse_until(row.get("valid_until") or "")
            coupons.append(
                Coupon(
                    platform=platform,
                    code=code,
                    description=(row.get("description") or "").strip()[:80],
                    discount_pct=parse_money(row.get("discount_pct")),
                    discount_brl=parse_money(row.get("discount_brl")),
                    min_purchase=parse_money(row.get("min_purchase")),
                    valid_until=until.replace(tzinfo=ZoneInfo(tz)),
                    niches=[x.strip() for x in (row.get("niches") or "").split(";") if x.strip()],
                )
            )
        except ValueError as exc:
            errors.append(f"linha {n}: {exc}")
    return coupons, errors


def load_coupons(tz: str, path: Path | None = None) -> list[Coupon]:
    file = path or COUPONS_PATH
    if not file.exists():
        return []
    coupons, errors = parse_coupons(file.read_text(encoding="utf-8-sig"), tz)
    for err in errors:
        log.warning("cupom ignorado", extra={"data": {"error": err}})
    return coupons


def valid_for_niche(coupons: list[Coupon], niche: Niche, now: datetime) -> list[Coupon]:
    rules = niche.settings.coupons
    out = []
    for c in coupons:
        hours_left = (c.valid_until - now).total_seconds() / 3600
        big_enough = c.discount_pct >= rules.min_discount_pct or c.discount_brl >= rules.min_discount_brl
        if hours_left >= rules.min_hours_valid and big_enough and (not c.niches or niche.id in c.niches):
            out.append(c)
    return out


def best_for(coupons: list[Coupon], niche: Niche, platform: str, price: float, now: datetime) -> Coupon | None:
    options = [c for c in valid_for_niche(coupons, niche, now) if c.applies(platform, niche.id, price)]
    return max(options, key=lambda c: c.savings(price), default=None)


def still_valid(coupons: list[Coupon], code: str | None, now: datetime) -> bool:
    return any(c.code == code and c.valid_until > now for c in coupons)


def expiring(coupons: list[Coupon], now: datetime, within: timedelta = timedelta(hours=24)) -> list[Coupon]:
    return [c for c in coupons if now < c.valid_until <= now + within]
