from datetime import timedelta

from src.pipeline.content import create_content
from src.pipeline.ingest import ingest
from src.pipeline.score import score_niche
from src.pipeline.transform import transform
from src.run import run_steps
from src.sources.fake import FakeShopee
from tests.conftest import DAY1


def run_day(ctx):
    for niche in ctx.niches(("active", "candidate")):
        ingest(ctx, niche)
        transform(ctx, niche)
        score_niche(ctx, niche)
    for niche in ctx.niches():
        create_content(ctx, niche)


def counts(db):
    tables = [
        "raw_offer_snapshot",
        "raw_offer_niche",
        "product",
        "product_daily",
        "price_history",
        "product_score",
        "content_item",
    ]
    return {t: db.scalar(f"SELECT count(*) FROM {t}") for t in tables}


def test_two_days_produce_scores_with_sales_windows(make_ctx, db):
    run_day(make_ctx(DAY1))
    day2 = DAY1 + timedelta(days=1)
    run_day(make_ctx(day2))
    rows = db.fetchall(
        "SELECT components FROM product_score WHERE niche_id = 'casa' AND run_date = ?", (day2.isoformat(),)
    )
    assert rows
    assert any('"sales_1d": ' in r["components"] and '"sales_1d": null' not in r["components"] for r in rows)
    assert db.scalar("SELECT count(*) FROM content_item WHERE run_date = ?", (day2.isoformat(),)) == 10


def test_reprocessing_same_day_is_idempotent(make_ctx, db):
    run_day(make_ctx(DAY1))
    first = counts(db)
    run_day(make_ctx(DAY1))
    assert counts(db) == first


def test_candidate_niches_are_scored_but_get_no_content(make_ctx, db):
    run_day(make_ctx(DAY1))
    assert db.scalar("SELECT count(*) FROM product_score WHERE niche_id = 'beauty'") > 0
    assert db.scalar("SELECT count(*) FROM content_item WHERE niche_id = 'beauty'") == 0


def test_failure_in_one_niche_does_not_affect_others(make_ctx, db, config):
    casa_keywords = set(config.niche("casa").platforms.shopee.keywords)
    ctx = make_ctx(DAY1, shopee=FakeShopee(DAY1, fail_keywords=casa_keywords))
    from src.run import build_steps, parse_args

    registry = build_steps(parse_args(["--steps", "daily"]))
    failures = run_steps(ctx, ["sync-niches", "ingest", "transform", "score", "content"], registry, None)
    assert any(f.startswith("ingest[casa]") for f in failures)
    assert db.scalar("SELECT count(*) FROM content_item WHERE niche_id = 'pet'") == 5
    assert db.scalar("SELECT count(*) FROM content_item WHERE niche_id = 'casa'") == 0
    status = db.fetchone("SELECT status FROM pipeline_run WHERE step = 'ingest' AND niche_id = 'casa'")
    assert status["status"] == "failed"


def test_price_history_is_scd2(make_ctx, db):
    from src.pipeline.transform import update_price_history

    ctx = make_ctx(DAY1)
    db.execute(
        "INSERT INTO product (id, platform, item_id, title, price, first_seen, last_seen) "
        "VALUES ('shopee:1', 'shopee', '1', 't', 10, '2026-10-01', '2026-10-01')"
    )
    update_price_history(ctx, "shopee:1", "2026-10-01", 10.0)
    update_price_history(ctx, "shopee:1", "2026-10-02", 10.0)  # sem mudança
    update_price_history(ctx, "shopee:1", "2026-10-03", 8.0)
    update_price_history(ctx, "shopee:1", "2026-10-03", 9.0)  # reprocessamento do mesmo dia
    rows = db.fetchall("SELECT valid_from, valid_to, price FROM price_history ORDER BY valid_from")
    assert rows == [
        {"valid_from": "2026-10-01", "valid_to": "2026-10-03", "price": 10.0},
        {"valid_from": "2026-10-03", "valid_to": None, "price": 9.0},
    ]


def test_content_has_tracked_link_with_sub_ids(make_ctx, db):
    fake = FakeShopee(DAY1)
    ctx = make_ctx(DAY1, shopee=fake)
    ctx.linker = fake
    run_day(ctx)
    item = db.fetchone("SELECT * FROM content_item WHERE niche_id = 'casa' LIMIT 1")
    assert any(subs == ["casa", "tg", item["id"]] for _, subs in fake.links)
    assert "#publi" in item["caption"] and "sujeito a alteração" in item["caption"]
    assert item["status"] == "ready"


def test_cooldown_prevents_reposting_same_product(make_ctx, db):
    run_day(make_ctx(DAY1))
    run_day(make_ctx(DAY1 + timedelta(days=1)))
    dupes = db.fetchall(
        "SELECT product_id FROM content_item WHERE niche_id = 'casa' GROUP BY product_id HAVING count(*) > 1"
    )
    assert dupes == []
