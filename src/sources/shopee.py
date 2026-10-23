"""Cliente da Shopee Affiliate Open API (GraphQL).

Autenticação: header `Authorization: SHA256 Credential=<AppId>,Timestamp=<ts>,Signature=<sig>`,
com sig = sha256(AppId + Timestamp + Payload + Secret), onde Payload é o corpo JSON enviado.

IMPORTANTE: confirme nomes de campos e argumentos no explorador GraphQL do painel de
afiliados antes de confiar nos números. As queries ficam isoladas nas constantes abaixo
e o parse é defensivo (campo ausente vira None).
"""

from __future__ import annotations

import hashlib
import json
import time
from datetime import UTC, datetime
from typing import Any

import httpx

from src.common.logging import get_logger
from src.sources.base import ConversionRecord, Offer

log = get_logger(__name__)

ENDPOINT = "https://open-api.affiliate.shopee.com.br/graphql"
SORT_ITEM_SOLD_DESC = 2
RATE_LIMIT_CODES = {10030}

PRODUCT_FIELDS = """
  itemId productName commissionRate sales priceMin priceMax priceDiscountRate
  ratingStar imageUrl productLink offerLink shopName productCatIds
"""

CONVERSION_FIELDS = """
  conversionId purchaseTime utmContent totalCommission
  orders { orderId orderStatus items { itemId itemName itemPrice qty itemTotalCommission } }
"""


class ShopeeError(RuntimeError):
    def __init__(self, message: str, code: int | None = None):
        super().__init__(message)
        self.code = code


def gql_str(value: str) -> str:
    """Literal de string GraphQL (o escape de JSON é compatível)."""
    return json.dumps(value, ensure_ascii=False)


def sign(app_id: str, secret: str, timestamp: int, payload: str) -> str:
    return hashlib.sha256(f"{app_id}{timestamp}{payload}{secret}".encode()).hexdigest()


class ShopeeClient:
    def __init__(
        self,
        app_id: str,
        secret: str,
        http: httpx.Client | None = None,
        endpoint: str = ENDPOINT,
        min_interval_s: float = 0.5,
        max_retries: int = 3,
        sleep=time.sleep,
    ):
        self.app_id = app_id
        self._secret = secret
        self.http = http or httpx.Client(timeout=30)
        self.endpoint = endpoint
        self.min_interval_s = min_interval_s
        self.max_retries = max_retries
        self._sleep = sleep
        self._last_call = 0.0

    # ----------------------------------------------------------------- transport
    def query(self, query: str) -> dict[str, Any]:
        payload = json.dumps({"query": query}, ensure_ascii=False, separators=(",", ":"))
        for attempt in range(self.max_retries + 1):
            wait = self.min_interval_s - (time.monotonic() - self._last_call)
            if wait > 0:
                self._sleep(wait)
            self._last_call = time.monotonic()
            ts = int(time.time())
            headers = {
                "Content-Type": "application/json",
                "Authorization": (
                    f"SHA256 Credential={self.app_id},Timestamp={ts},"
                    f"Signature={sign(self.app_id, self._secret, ts, payload)}"
                ),
            }
            try:
                resp = self.http.post(self.endpoint, content=payload.encode(), headers=headers)
            except httpx.TransportError as exc:
                if attempt == self.max_retries:
                    raise ShopeeError(f"falha de rede na Shopee: {type(exc).__name__}") from exc
                self._sleep(2**attempt)
                continue
            if resp.status_code == 429 or resp.status_code >= 500:
                if attempt == self.max_retries:
                    raise ShopeeError(f"Shopee HTTP {resp.status_code}")
                self._sleep(2**attempt)
                continue
            body = resp.json()
            errors = body.get("errors") or []
            if errors:
                ext = errors[0].get("extensions") or {}
                code = ext.get("code")
                if code in RATE_LIMIT_CODES and attempt < self.max_retries:
                    self._sleep(2 ** (attempt + 2))
                    continue
                raise ShopeeError(f"Shopee erro {code}: {errors[0].get('message')}", code)
            return body.get("data") or {}
        raise ShopeeError("Shopee: tentativas esgotadas")

    # ------------------------------------------------------------------- ofertas
    def search(self, keyword: str, limit: int) -> list[Offer]:
        q = (
            f"{{ productOfferV2(keyword: {gql_str(keyword)}, sortType: {SORT_ITEM_SOLD_DESC}, "
            f"page: 1, limit: {int(limit)}) {{ nodes {{ {PRODUCT_FIELDS} }} }} }}"
        )
        nodes = (self.query(q).get("productOfferV2") or {}).get("nodes") or []
        offers = []
        for node in nodes:
            offer = parse_product(node)
            if offer:
                offers.append(offer)
        return offers

    def short_link(self, url: str, sub_ids: list[str]) -> str:
        subs = ", ".join(gql_str(s) for s in sub_ids[:5])
        q = (
            f"mutation {{ generateShortLink(input: {{ originUrl: {gql_str(url)}, "
            f"subIds: [{subs}] }}) {{ shortLink }} }}"
        )
        link = (self.query(q).get("generateShortLink") or {}).get("shortLink")
        if not link:
            raise ShopeeError("generateShortLink sem shortLink")
        return link

    # --------------------------------------------------------------- conversões
    def conversions(self, start_ts: int, end_ts: int) -> list[ConversionRecord]:
        records: list[ConversionRecord] = []
        scroll_id: str | None = None
        for _ in range(100):  # limite de páginas por execução
            scroll = f", scrollId: {gql_str(scroll_id)}" if scroll_id else ""
            q = (
                f"{{ conversionReport(purchaseTimeStart: {int(start_ts)}, "
                f"purchaseTimeEnd: {int(end_ts)}, limit: 500{scroll}) "
                f"{{ nodes {{ {CONVERSION_FIELDS} }} pageInfo {{ hasNextPage scrollId }} }} }}"
            )
            report = self.query(q).get("conversionReport") or {}
            for node in report.get("nodes") or []:
                records.extend(parse_conversion(node))
            page = report.get("pageInfo") or {}
            scroll_id = page.get("scrollId")
            if not page.get("hasNextPage") or not scroll_id:
                break
        return records


def _float(value: Any) -> float | None:
    try:
        return float(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _int(value: Any) -> int | None:
    f = _float(value)
    return int(f) if f is not None else None


def parse_product(node: dict[str, Any]) -> Offer | None:
    item_id = node.get("itemId")
    title = (node.get("productName") or "").strip()
    price = _float(node.get("priceMin"))
    url = node.get("productLink") or ""
    if not item_id or not title or not price or price <= 0 or not url:
        return None
    discount = _float(node.get("priceDiscountRate")) or 0.0
    original = round(price / (1 - discount / 100), 2) if 0 < discount < 95 else None
    cats = node.get("productCatIds") or []
    return Offer(
        platform="shopee",
        item_id=str(item_id),
        title=title,
        price=price,
        price_original=original,
        product_url=url,
        affiliate_url=node.get("offerLink"),
        image_url=node.get("imageUrl"),
        rating=_float(node.get("ratingStar")),
        sales_total=_int(node.get("sales")),
        commission_rate=_float(node.get("commissionRate")),
        category=",".join(str(c) for c in cats) or None,
        shop_name=node.get("shopName"),
    )


def parse_conversion(node: dict[str, Any]) -> list[ConversionRecord]:
    conv_id = str(node.get("conversionId") or "")
    ts = _int(node.get("purchaseTime")) or 0
    purchase = datetime.fromtimestamp(ts, UTC).isoformat(timespec="seconds")
    sub_ids = [s for s in str(node.get("utmContent") or "").split("-") if s]
    out = []
    for order in node.get("orders") or []:
        for item in order.get("items") or []:
            qty = _int(item.get("qty")) or 1
            out.append(
                ConversionRecord(
                    platform="shopee",
                    conversion_id=conv_id,
                    order_id=str(order.get("orderId") or ""),
                    item_id=str(item.get("itemId") or ""),
                    purchase_time=purchase,
                    status=str(order.get("orderStatus") or ""),
                    amount=(_float(item.get("itemPrice")) or 0.0) * qty,
                    commission=_float(item.get("itemTotalCommission")) or 0.0,
                    sub_ids=sub_ids,
                    raw={"conversion": conv_id, "order": order.get("orderId")},
                )
            )
    return out
