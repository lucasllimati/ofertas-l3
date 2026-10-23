import hashlib
import json

import httpx
import pytest

from src.sources.shopee import ShopeeClient, ShopeeError, parse_conversion, parse_product, sign

NODE = {
    "itemId": 123,
    "productName": "Organizador de Gaveta",
    "commissionRate": "0.08",
    "sales": 1500,
    "priceMin": "39.90",
    "priceDiscountRate": 20,
    "ratingStar": "4.8",
    "imageUrl": "https://cf.shopee.com.br/file/x",
    "productLink": "https://shopee.com.br/product/1/123",
    "offerLink": "https://s.shopee.com.br/abc",
    "shopName": "Loja",
    "productCatIds": [1, 2],
}


def test_signature_matches_spec():
    expected = hashlib.sha256(b'app1700000000{"query":"x"}secret').hexdigest()
    assert sign("app", "secret", 1700000000, '{"query":"x"}') == expected


def test_parse_product():
    offer = parse_product(NODE)
    assert offer.item_id == "123"
    assert offer.price == 39.90
    assert offer.price_original == pytest.approx(49.875, abs=0.01)
    assert offer.rating == 4.8 and offer.sales_total == 1500 and offer.commission_rate == 0.08
    assert parse_product({**NODE, "priceMin": "0"}) is None
    assert parse_product({**NODE, "productName": ""}) is None


def test_parse_conversion_splits_items_and_sub_ids():
    node = {
        "conversionId": 9,
        "purchaseTime": 1760000000,
        "utmContent": "casa-tg-abc123----",
        "orders": [
            {
                "orderId": "o1",
                "orderStatus": "PENDING",
                "items": [
                    {"itemId": 1, "itemPrice": "10", "qty": 2, "itemTotalCommission": "1.6"},
                    {"itemId": 2, "itemPrice": "5", "qty": 1, "itemTotalCommission": "0.4"},
                ],
            }
        ],
    }
    records = parse_conversion(node)
    assert [r.amount for r in records] == [20.0, 5.0]
    assert records[0].sub_ids == ["casa", "tg", "abc123"]


def make_client(handler):
    return ShopeeClient(
        "app", "secret", http=httpx.Client(transport=httpx.MockTransport(handler)), sleep=lambda s: None
    )


def test_client_signs_and_searches():
    seen = {}

    def handler(request: httpx.Request):
        seen["auth"] = request.headers["Authorization"]
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"data": {"productOfferV2": {"nodes": [NODE]}}})

    offers = make_client(handler).search('mop "giratório"', 10)
    assert len(offers) == 1
    assert seen["auth"].startswith("SHA256 Credential=app,Timestamp=")
    assert '"mop \\"giratório\\""' in seen["body"]["query"]  # aspas escapadas, sem injeção


def test_client_retries_rate_limit_then_succeeds():
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(200, json={"errors": [{"message": "rate", "extensions": {"code": 10030}}]})
        if calls["n"] == 2:
            return httpx.Response(429)
        return httpx.Response(200, json={"data": {"generateShortLink": {"shortLink": "https://s.shopee.com.br/x"}}})

    assert (
        make_client(handler).short_link("https://shopee.com.br/p", ["casa", "tg", "id"]) == "https://s.shopee.com.br/x"
    )
    assert calls["n"] == 3


def test_client_raises_on_api_error():
    def handler(request):
        return httpx.Response(200, json={"errors": [{"message": "invalid signature", "extensions": {"code": 10020}}]})

    with pytest.raises(ShopeeError, match="10020"):
        make_client(handler).search("x", 5)
