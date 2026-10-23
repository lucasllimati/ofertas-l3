"""Testes das correções da revisão de segurança (docs/security-review.md)."""

import gzip
import json
import os
from datetime import date, timedelta

import pytest

from src.approval import process_updates
from src.backup import BACKUP_TABLES, export_backup, restore_backup
from src.common.db import Database, tls_options
from src.content.caption import build_caption, compliance_issues
from src.content.copy import CopyResult, TemplateCopywriter, clean_text, sales_claim
from src.pipeline.content import verified_original
from src.reports.daily import build_report
from tests.conftest import ADMIN_ID, DAY1
from tests.test_approval_publish import prepare

MALICIOUS_TITLE = (
    "【PROMOÇÃO】 Organizador Gaveta FRETE GRÁTIS chama no zap (11) 98765-4321 @lojagolpe "
    "acesse bit.ly/xyz ou https://evil.example.com R$ 9,90 cupom GANHE10"
)


# ------------------------------------------------- texto do vendedor e do LLM
def test_clean_text_removes_traffic_diversion_and_unverified_claims():
    cleaned = clean_text(MALICIOUS_TITLE)
    for bad in ("bit.ly", "https://", "evil", "@lojagolpe", "98765", "R$", "cupom", "FRETE", "PROMO", "【"):
        assert bad.lower() not in cleaned.lower(), bad
    assert "Organizador Gaveta" in cleaned


def test_template_copy_from_malicious_title_passes_compliance(config):
    product = {"title": MALICIOUS_TITLE, "rating": 4.8, "sales_total": 2500}
    copy, _ = TemplateCopywriter().write(product, config.niche("casa"), {"name": "Garimpo Casa", "emoji": "🏠"})
    caption = build_caption(copy, 39.9, None, "https://s.shopee.com.br/ok", DAY1, [])
    assert compliance_issues(caption, link_allowed=True) == []
    assert "Mais de 2.000 vendidos na loja" in caption


def test_llm_output_is_cleaned_too():
    copy = CopyResult(headline="Oferta! fale com @golpista", bullets=["Veja em loja.xyz/promo", "Ótimo"], hashtags=[])
    assert "@golpista" not in copy.headline
    assert copy.bullets == ["Veja em", "Ótimo"]


def test_compliance_blocks_links_handles_phones_and_extra_anchors():
    base = "#publi 20/10/2026 sujeito a alteração "
    anchor = '<a href="https://s.shopee.com.br/x">Ver oferta</a>'
    assert compliance_issues(base + anchor, True) == []
    for bad in ("veja t.me/canal", "fale com @fulano", "zap 11987654321", "site.com.br"):
        assert any("golpe" in i for i in compliance_issues(base + anchor + " " + bad, True)), bad
    two_links = base + anchor + ' <a href="https://s.shopee.com.br/y">outro</a>'
    assert any("exatamente um link" in i for i in compliance_issues(two_links, True))


def test_sales_claim_never_rounds_up():
    assert sales_claim(None) is None and sales_claim(99) is None
    assert sales_claim(150) == "Mais de 100 vendidos na loja"
    assert sales_claim(1999) == "Mais de 1.000 vendidos na loja"
    assert sales_claim(12_345) == "Mais de 12.000 vendidos na loja"


# ------------------------------------------------------------ "de/por" verificado
def seed_history(db, product_id, prices):
    db.execute(
        "INSERT INTO product (id, platform, item_id, title, price, first_seen, last_seen) "
        "VALUES (?, 'shopee', ?, 'x', 50, '2026-10-01', '2026-10-20') ON CONFLICT DO NOTHING",
        (product_id, product_id),
    )
    for day, price in prices.items():
        db.execute("INSERT INTO product_daily (product_id, run_date, price) VALUES (?, ?, ?)", (product_id, day, price))


def test_discount_shown_only_when_full_price_was_observed(make_ctx, db):
    ctx = make_ctx(DAY1)
    product = {"id": "shopee:1", "price": 50.0, "price_original": 80.0}
    assert verified_original(ctx, product) is None  # sem histórico: não mostra "de"
    seed_history(db, "shopee:1", {"2026-10-10": 60.0, "2026-10-15": 55.0})
    assert verified_original(ctx, product) is None  # "de" inflado: nunca custou 80
    seed_history(db, "shopee:2", {"2026-10-12": 79.0})
    assert verified_original(ctx, {**product, "id": "shopee:2"}) == 80.0
    seed_history(db, "shopee:3", {"2026-08-01": 80.0})
    assert verified_original(ctx, {**product, "id": "shopee:3"}) is None  # preço cheio antigo demais


def test_published_art_and_caption_use_verified_original(make_ctx, db):
    ctx = make_ctx(DAY1)
    prepare(ctx)
    rows = db.fetchall("SELECT caption, price_original_shown FROM content_item")
    assert rows and all(r["price_original_shown"] is None for r in rows)  # primeiro dia: sem histórico
    assert not any("<s>" in r["caption"] for r in rows)


# --------------------------------------------------- fila do Telegram não trava
def test_failing_update_does_not_block_the_queue(make_ctx, db, monkeypatch):
    ctx = make_ctx()
    calls = []

    def flaky(ctx_, message):
        calls.append(message["text"])
        if message["text"] == "/quebra":
            raise RuntimeError("falha simulada")
        return True

    monkeypatch.setattr("src.commands.handle_command", flaky)
    ctx.telegram.push_command("/quebra", "admin-chat")
    ctx.telegram.push_command("/status", "admin-chat")
    result = process_updates(ctx)
    assert calls == ["/quebra", "/status"] and result["failed"] == 1
    assert process_updates(ctx)["commands"] == 0  # offset avançou: não reprocessa nem trava
    assert db.scalar("SELECT count(*) FROM audit_log WHERE action = 'update_failed'") == 1
    assert any("toque de novo" in m.get("text", "") for m in ctx.telegram.sent)


def test_report_shows_security_events(make_ctx, db):
    ctx = make_ctx()
    ctx.telegram.push_callback("a:qualquer:0000000000000000", 1, "admin-chat", user_id=999)
    ctx.telegram.push_command("/pausar casa telegram", "admin-chat", user_id=999)
    process_updates(ctx)
    report = build_report(ctx)
    assert "Segurança (24 h)" in report
    assert "Botão tocado por quem não é admin: 1" in report
    assert "Comando de quem não é admin: 1" in report
    assert ADMIN_ID  # o admin legítimo não gera evento


# --------------------------------------------------------------- TLS no banco
def test_tls_required_outside_localhost():
    assert tls_options("postgresql://u:p@aws-0-sa-east-1.pooler.supabase.com:5432/postgres") == {"sslmode": "require"}
    assert tls_options("postgresql://u:p@localhost:5432/db") == {}
    assert tls_options("postgresql://u:p@db.example.com/db?sslmode=verify-full") == {}


# ------------------------------------------------------------------- backup
def test_backup_roundtrip(make_ctx, db, tmp_path):
    ctx = make_ctx(DAY1)
    prepare(ctx)
    result = export_backup(ctx)
    path = tmp_path / "backup" / result["file"]
    assert result["rows"] > 0 and path.exists()
    fresh = Database("sqlite://:memory:")
    fresh.migrate()
    restored = restore_backup(fresh, path)
    for table in ("product", "content_item", "audit_log"):
        assert fresh.scalar(f"SELECT count(*) FROM {table}") == db.scalar(f"SELECT count(*) FROM {table}")
    assert restored["content_item"] == 5
    assert restore_backup(fresh, path).get("content_item", 0) == 0  # idempotente: não duplica


@pytest.mark.parametrize(
    "line",
    [
        {"t": "sqlite_master", "r": {"name": "x"}},
        {"t": "product", "r": {"id) VALUES ('x'); DROP TABLE product; --": 1}},
    ],
)
def test_tampered_backup_is_rejected(tmp_path, line):
    path = tmp_path / "evil.jsonl.gz"
    with gzip.open(path, "wt", encoding="utf-8") as fh:
        fh.write(json.dumps({"format": 1, "tables": BACKUP_TABLES}) + "\n" + json.dumps(line) + "\n")
    fresh = Database("sqlite://:memory:")
    fresh.migrate()
    with pytest.raises(ValueError):
        restore_backup(fresh, path)
    assert fresh.scalar("SELECT count(*) FROM product") == 0


# ---------------------------------------------------- Postgres: RLS e permissões
def require_postgres(db):
    if db.dialect != "postgres":
        if os.environ.get("REQUIRE_POSTGRES") == "1":  # no CI, pular estes testes é falha, não sucesso
            pytest.fail("REQUIRE_POSTGRES=1 mas o banco de teste não é Postgres (defina TEST_DATABASE_URL)")
        pytest.skip("só em Postgres (CI com TEST_DATABASE_URL)")


def test_every_table_has_rls(db):
    require_postgres(db)
    missing = db.fetchall(
        "SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
        "WHERE n.nspname = 'garimpo' AND c.relkind = 'r' AND NOT c.relrowsecurity"
    )
    assert missing == []  # migration nova sem RLS reprova o CI


def test_pipeline_role_cannot_erase_sales_or_audit(db):
    require_postgres(db)
    import psycopg

    db.execute("SET ROLE app_writer")
    try:
        db.execute("SELECT count(*) FROM conversion")  # leitura continua ok
        for sql in (
            "DELETE FROM conversion",
            "DELETE FROM click_event",
            "DELETE FROM content_item",
            "DELETE FROM audit_log",
            "UPDATE audit_log SET actor = 'x'",
            "DROP TABLE conversion",
        ):
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                db.execute(sql)
    finally:
        db.execute("RESET ROLE")


def test_old_day_is_still_reprocessable_after_hardening(make_ctx, db):
    # O pipeline continua podendo apagar staging e score do dia (necessário para reprocessar).
    ctx = make_ctx(DAY1)
    prepare(ctx)
    later = make_ctx(DAY1 + timedelta(days=1))
    prepare(later)
    assert db.scalar("SELECT count(DISTINCT run_date) FROM product_score") == 2
    assert date.fromisoformat(db.scalar("SELECT max(run_date) FROM product_score")) == DAY1 + timedelta(days=1)
