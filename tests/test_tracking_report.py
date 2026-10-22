import httpx

from src.reports.daily import build_report
from src.sources.base import ConversionRecord
from src.tracking.cloudflare import CloudflareApi, RedirectRegistry
from src.tracking.sync import import_conversions_csv, store_conversions, sync_clicks, sync_conversions
from tests.test_approval_publish import prepare


class FakeClicks:
    def __init__(self, rows):
        self.rows = rows
        self.purged = None

    def fetch(self, after_id, limit=5000):
        return [r for r in self.rows if r["id"] > after_id][:limit]

    def purge(self, up_to_id, before_ts):
        self.purged = (up_to_id, before_ts)


class FakeConversions:
    def __init__(self, records):
        self.records = records

    def conversions(self, start_ts, end_ts):
        return self.records


def test_clicks_sync_is_incremental_and_idempotent(make_ctx, db):
    ctx = make_ctx()
    rows = [
        {
            "id": 1,
            "ts": "2026-10-20T12:00:00+00:00",
            "niche": "casa",
            "channel": "tg",
            "content_id": "x",
            "country": "BR",
        },
        {
            "id": 2,
            "ts": "2026-10-20T12:01:00+00:00",
            "niche": "pet",
            "channel": "tg",
            "content_id": "y",
            "country": "BR",
        },
        {
            "id": 3,
            "ts": "2026-10-20T12:02:00+00:00",
            "niche": "hacker",
            "channel": "tg",
            "content_id": "z",
            "country": None,
        },
    ]
    ctx.clicks_source = FakeClicks(rows)
    assert sync_clicks(ctx)["clicks"] == 3
    assert sync_clicks(ctx)["clicks"] == 0
    assert db.scalar("SELECT count(*) FROM click_event") == 2  # nicho desconhecido descartado
    assert db.scalar("SELECT channel FROM click_event WHERE id = 'd1:1'") == "telegram"
    assert ctx.clicks_source.purged[0] == 3


def test_conversions_are_attributed_to_content(make_ctx, db):
    ctx = make_ctx()
    prepare(ctx)
    content_id = db.scalar("SELECT id FROM content_item WHERE niche_id = 'casa' LIMIT 1")
    rec = ConversionRecord(
        "shopee", "c1", "o1", "i1", "2026-10-20T15:00:00+00:00", "PENDING", 50.0, 4.0, ["casa", "tg", content_id]
    )
    ctx.conversions_source = FakeConversions([rec])
    sync_conversions(ctx)
    rec.status, rec.commission = "COMPLETED", 4.5
    sync_conversions(ctx)  # atualiza em vez de duplicar
    row = db.fetchone("SELECT * FROM conversion")
    assert db.scalar("SELECT count(*) FROM conversion") == 1
    assert (row["niche_id"], row["channel"], row["content_id"], row["status"], row["commission"]) == (
        "casa",
        "telegram",
        content_id,
        "COMPLETED",
        4.5,
    )


def test_unknown_sub_ids_are_kept_without_attribution(make_ctx, db):
    ctx = make_ctx()
    store_conversions(
        ctx,
        [
            ConversionRecord(
                "shopee",
                "c2",
                "o2",
                "i2",
                "2026-10-20T15:00:00+00:00",
                "PENDING",
                10.0,
                1.0,
                ["outro", "xx", "naoexiste"],
            )
        ],
    )
    row = db.fetchone("SELECT niche_id, content_id FROM conversion")
    assert row == {"niche_id": None, "content_id": None}


def test_csv_conversion_import(make_ctx, db, tmp_path):
    ctx = make_ctx()
    path = tmp_path / "ml.csv"
    path.write_text(
        "platform,order_id,item_id,purchase_time,status,amount,commission,sub_id\n"
        "mercadolivre,9,MLB1,2026-10-20T10:00:00+00:00,paid,100,8,pet-tg-zzz\n",
        encoding="utf-8",
    )
    assert import_conversions_csv(ctx, path)["conversions"] == 1
    assert db.scalar("SELECT niche_id FROM conversion") == "pet"


def test_report_contains_niches_and_totals(make_ctx, db):
    ctx = make_ctx()
    prepare(ctx)
    store_conversions(
        ctx,
        [
            ConversionRecord(
                "shopee", "c1", "o1", "i1", "2026-10-20T15:00:00+00:00", "PENDING", 50.0, 4.0, ["casa", "tg", "x"]
            )
        ],
    )
    text = build_report(ctx)
    assert "Garimpo Casa" in text and "Garimpo Pet" in text
    assert "R$ 4,00" in text
    assert "aguardando você" in text


def test_redirect_registry_writes_kv_and_returns_go_url():
    seen = {}

    def handler(request: httpx.Request):
        seen["url"] = str(request.url)
        seen["body"] = request.content.decode()
        seen["auth"] = request.headers["Authorization"]
        return httpx.Response(200, json={"success": True})

    api = CloudflareApi("tok", "acc", http=httpx.Client(transport=httpx.MockTransport(handler)))
    url = RedirectRegistry(api, "ns", "https://go.garimpo.com.br/").register(
        "abc123", "https://s.shopee.com.br/x", "casa", "tg"
    )
    assert url == "https://go.garimpo.com.br/go/casa/tg/abc123"
    assert "/storage/kv/namespaces/ns/values/go:abc123" in seen["url"]
    assert '"url": "https://s.shopee.com.br/x"' in seen["body"]
    assert seen["auth"] == "Bearer tok"
