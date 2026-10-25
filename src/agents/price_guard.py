"""Agente Vigia de preço e estoque: reconsulta o produto logo antes de publicar.

O post é aprovado de manhã e sai horas depois; se o preço mudou, a legenda anunciaria um preço
errado (risco de propaganda enganosa e de clique sem venda). Decisões:
- produto indisponível            -> não publica (status `unavailable`) e avisa;
- preço mudou além da tolerância  -> refaz legenda e arte com o preço novo e volta para a sua
                                     aprovação (status `ready`, com o motivo na prévia);
- não foi possível consultar      -> publica normalmente e registra no log (a API fora do ar não
                                     pode parar todos os posts; o preço é do mesmo dia).
Ofertas coladas à mão (CSV) não têm API para consultar e seguem sem checagem.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from src.common.logging import get_logger
from src.common.util import brl

log = get_logger(__name__)


@dataclass
class PriceStatus:
    available: bool
    price: float | None = None


class PriceChecker(Protocol):
    def status(self, product: dict[str, Any]) -> PriceStatus | None:
        """None = não dá para consultar este produto (ex.: oferta manual)."""


class ShopeePriceChecker:
    def __init__(self, client: Any):
        self.client = client

    def status(self, product: dict[str, Any]) -> PriceStatus | None:
        is_manual = product.get("affiliate_url") == product.get("product_url")
        if product.get("platform") != "shopee" or is_manual:
            return None
        return self.client.item_status(product["item_id"])


@dataclass
class GuardDecision:
    action: str  # publish | reapprove | unavailable
    reason: str | None = None
    new_price: float | None = None


def decide(price_at_creation: float, status: PriceStatus | None, tolerance_pct: float) -> GuardDecision:
    if status is None:
        return GuardDecision("publish")
    if not status.available or status.price is None:
        return GuardDecision("unavailable", "produto indisponível na loja")
    change = (status.price - price_at_creation) / price_at_creation * 100
    if abs(change) > tolerance_pct:
        direction = "subiu" if change > 0 else "caiu"
        reason = f"preço {direction} de {brl(price_at_creation)} para {brl(status.price)} ({change:+.0f}%)"
        return GuardDecision("reapprove", reason, status.price)
    return GuardDecision("publish")


def check(checker: PriceChecker | None, product: dict[str, Any], price_at_creation: float, tolerance_pct: float):
    """Consulta e decide. Falha na consulta = publicar (ver docstring do módulo)."""
    if checker is None:
        return GuardDecision("publish")
    try:
        status = checker.status(product)
    except Exception as exc:
        log.warning("vigia de preço não conseguiu consultar; publicando", extra={"data": {"error": type(exc).__name__}})
        return GuardDecision("publish")
    return decide(price_at_creation, status, tolerance_pct)
