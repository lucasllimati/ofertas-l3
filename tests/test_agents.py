"""Agentes da v0.4: Calendário, Vigia de preço, Classificador, Cupons, Sentinela/Reciclador,
Detector de links, Analista de mercado, Horários, A/B, Conciliador e Contador."""

import json
from datetime import date, timedelta
from types import SimpleNamespace

import pytest

from src.agents import price_guard
from src.agents.compliance import ComplianceClassifier
from src.agents.coupons import best_for, expiring, parse_coupons, still_valid
from src.agents.finance import (
    accountant_report,
    allocate,
    classify,
    irpf_monthly,
    load_finance,
    mei_das,
    reconcile,
    reconcile_csv,
    shift_month,
    simples_rate,
    tax_scenarios,
)
from src.agents.insights import ab_report, cron_for_slots, market_report, slots_report, variant_for
from src.agents.links import check_published_links
from src.agents.price_guard import PriceStatus, ShopeePriceChecker
from src.agents.seasonal import Calendar, scaled
from src.agents.sentinel import champions, sentinel
from src.approval import process_updates
from src.common.llm import LlmGateway
from src.common.util import dec, pct, slot_to_utc
from src.pipeline.content import create_content
from src.publishers.telegram import publish_niche
from src.sources.base import ConversionRecord
from src.sources.fake import FakeShopee
from src.tracking.sync import store_conversions
from tests.conftest import ADMIN_ID, DAY1
from tests.test_approval_publish import approve_all, prepare

TZ = "America/Sao_Paulo"


def items(db, niche="casa"):
    return db.fetchall("SELECT * FROM content_item WHERE niche_id = ? ORDER BY id", (niche,))


def sell(ctx, content_id, niche_id, commission=10.0, status="COMPLETED", when=None):
    store_conversions(
        ctx,
        [
            ConversionRecord(
                "shopee",
                f"c-{content_id}-{commission}-{status}-{when}",  # id único por venda simulada
                "o1",
                "i1",
                when or "2026-10-20T15:00:00+00:00",
                status,
                commission * 10,
                commission,
                [niche_id, "tg", content_id],
            )
        ],
    )


# ------------------------------------------------------------ Calendário sazonal
CAL = Calendar.model_validate(
    {
        "events": [
            {
                "id": "bf",
                "name": "Black Friday",
                "start": "2026-10-20",
                "end": "2026-10-21",
                "content_multiplier": 2.0,
                "badge": "Black Friday",
                "extra_keywords": {"casa": ["air fryer"]},
            },
            {"id": "natal", "name": "Natal", "start": "2026-10-25", "end": "2026-10-30", "heads_up_days": 7},
        ]
    }
)


def test_calendar_rules():
    assert CAL.multiplier(DAY1, "casa") == 2.0 and CAL.multiplier(DAY1 + timedelta(days=2), "casa") == 1.0
    assert CAL.badge(DAY1, "pet") == "Black Friday"
    assert CAL.extra_keywords(DAY1, "casa") == ["air fryer"] and CAL.extra_keywords(DAY1, "pet") == []
    assert [(e.id, d) for e, d in CAL.upcoming(DAY1)] == [("natal", 5)]
    assert scaled(5, 1.5) == 8
    with pytest.raises(ValueError):
        Calendar.model_validate({"events": [{"id": "x", "name": "x", "start": "2026-10-02", "end": "2026-10-01"}]})


def test_calendar_drives_keywords_volume_and_badge(make_ctx, db):
    ctx = make_ctx(calendar=CAL)
    prepare(ctx)
    keywords = {r["keyword"] for r in db.fetchall("SELECT keyword FROM raw_offer_niche WHERE niche_id = 'casa'")}
    assert "air fryer" in keywords
    assert len(items(db)) == 10  # 5 por dia x 2.0
    assert all("Black Friday" in i["caption"].split("\n")[1] for i in items(db))
    assert all("#publi" in i["caption"].split("\n")[0] for i in items(db))  # identificação continua no topo


def test_repo_calendar_has_black_friday_2026():
    from src.agents.seasonal import load_calendar

    cal = load_calendar()
    assert cal.badge(date(2026, 11, 27), "casa") == "Black Friday"
    assert cal.multiplier(date(2026, 11, 27), "pet") == 2.0


# ------------------------------------------------------------ Vigia de preço
def test_price_guard_decisions():
    assert price_guard.decide(100, None, 2).action == "publish"
    assert price_guard.decide(100, PriceStatus(True, 101), 2).action == "publish"
    up = price_guard.decide(100, PriceStatus(True, 120), 2)
    assert up.action == "reapprove" and "subiu" in up.reason and up.new_price == 120
    assert price_guard.decide(100, PriceStatus(True, 80), 2).action == "reapprove"
    assert price_guard.decide(100, PriceStatus(False), 2).action == "unavailable"

    class Boom:
        def status(self, product):
            raise TimeoutError

    assert price_guard.check(Boom(), {}, 100, 2).action == "publish"  # API fora não para a produção


def guarded_setup(make_ctx, db):
    fake = FakeShopee(DAY1)
    ctx = make_ctx(shopee=fake)
    ctx.linker = fake
    ctx.price_checker = ShopeePriceChecker(fake)
    prepare(ctx)
    approve_all(ctx, db)
    night = make_ctx(now=slot_to_utc(DAY1, "23:00", TZ), telegram=ctx.telegram, shopee=fake)
    night.price_checker = ctx.price_checker
    return fake, ctx, night


def test_price_increase_sends_back_for_reapproval(make_ctx, db):
    fake, ctx, night = guarded_setup(make_ctx, db)
    first = items(db)[0]
    item_id = db.scalar("SELECT item_id FROM product WHERE id = ?", (first["product_id"],))
    fake.price_overrides[item_id] = round(first["price_at_creation"] * 1.3, 2)
    result = publish_niche(night, night.config.niche("casa"))
    assert result["price_guard"] == 1 and result["published"] == 4
    row = db.fetchone("SELECT * FROM content_item WHERE id = ?", (first["id"],))
    assert row["status"] == "ready" and "subiu" in row["status_reason"]
    assert row["price_at_creation"] == fake.price_overrides[item_id]
    assert row["media_file_id"] is None  # arte refeita com o preço novo
    assert any("Vigia de preço" in m.get("text", "") for m in ctx.telegram.sent)
    # A nova prévia mostra o motivo e volta a pedir aprovação
    from src.approval import send_previews

    send_previews(night, night.config.niche("casa"))
    assert "subiu" in ctx.telegram.sent[-1]["caption"]
    assert db.scalar("SELECT status FROM content_item WHERE id = ?", (first["id"],)) == "pending_approval"


def test_unavailable_product_is_not_published(make_ctx, db):
    fake, ctx, night = guarded_setup(make_ctx, db)
    first = items(db)[0]
    fake.unavailable.add(db.scalar("SELECT item_id FROM product WHERE id = ?", (first["product_id"],)))
    publish_niche(night, night.config.niche("casa"))
    assert db.scalar("SELECT status FROM content_item WHERE id = ?", (first["id"],)) == "unavailable"


# ------------------------------------------------------- Classificador de conformidade
class FakeMessages:
    def __init__(self, verdict):
        self.verdict = verdict
        self.calls = 0

    def create(self, **kwargs):
        self.calls += 1
        text = json.dumps({"verdict": self.verdict, "reason": "teste"})
        return SimpleNamespace(
            stop_reason="end_turn",
            content=[SimpleNamespace(type="text", text=text)],
            usage=SimpleNamespace(
                input_tokens=100, output_tokens=20, cache_read_input_tokens=0, cache_creation_input_tokens=0
            ),
        )


def test_compliance_blocks_and_caches(make_ctx, db):
    messages = FakeMessages("replica")
    gateway = LlmGateway(SimpleNamespace(messages=messages), db, "run", 1.0)
    ctx = make_ctx(compliance=ComplianceClassifier(gateway))
    prepare(ctx)
    assert items(db) == []  # tudo barrado
    calls = messages.calls
    create_content(ctx, ctx.config.niche("casa"))
    assert messages.calls == calls  # veredito em cache: o LLM não é pago de novo
    assert db.scalar("SELECT count(*) FROM compliance_check WHERE verdict = 'replica'") > 0
    assert db.scalar("SELECT count(*) FROM agent_run WHERE agent = 'conformidade'") == calls


def test_compliance_without_llm_or_budget_falls_back_to_rules(make_ctx, db):
    ctx = make_ctx(compliance=ComplianceClassifier(None))
    prepare(ctx)
    assert len(items(db)) == 5
    gateway = LlmGateway(SimpleNamespace(messages=FakeMessages("replica")), db, "run", 0.0)  # teto zero
    allowed, _ = ComplianceClassifier(gateway).allowed(ctx, ctx.config.niche("pet"), {"id": "shopee:x", "title": "x"})
    assert allowed is True


# ------------------------------------------------------------ Caçador de cupons
COUPONS_CSV = """platform,code,description,discount_pct,discount_brl,min_purchase,valid_until,niches
# comentário
shopee,ACHADO10,10%,10,,20,2026-10-22 23:59,casa
shopee,POUCO,2%,2,,0,2026-10-22 23:59,
shopee,FIM,15%,15,,0,20/10/2026 09:00,
shopee,DATA1,..,10,,0,amanhã,
ebay,X1,..,10,,0,2026-10-22 23:59,
shopee,ab,..,10,,0,2026-10-22 23:59,
"""


def test_coupon_parsing_and_rules(make_ctx):
    ctx = make_ctx()
    coupons, errors = parse_coupons(COUPONS_CSV, TZ)
    assert [c.code for c in coupons] == ["ACHADO10", "POUCO", "FIM"] and len(errors) == 3
    casa, pet = ctx.config.niche("casa"), ctx.config.niche("pet")
    assert best_for(coupons, casa, "shopee", 50, ctx.now).code == "ACHADO10"
    assert best_for(coupons, casa, "shopee", 10, ctx.now) is None  # abaixo da compra mínima; POUCO < 10%
    assert best_for(coupons, pet, "shopee", 50, ctx.now) is None  # ACHADO10 só vale para casa
    assert still_valid(coupons, "ACHADO10", ctx.now) and not still_valid(coupons, "FIM", ctx.now + timedelta(hours=10))
    assert [c.code for c in expiring(coupons, ctx.now)] == ["FIM"]


def test_coupon_goes_into_caption_and_leaves_when_expired(make_ctx, db):
    coupons, _ = parse_coupons(COUPONS_CSV, TZ)
    ctx = make_ctx(coupons=coupons)
    prepare(ctx)
    with_coupon = [i for i in items(db) if i["coupon_code"] == "ACHADO10"]
    assert with_coupon and "Cupom <b>ACHADO10</b>" in with_coupon[0]["caption"]
    approve_all(ctx, db)
    later = make_ctx(now=slot_to_utc(DAY1 + timedelta(days=1), "06:00", TZ), telegram=ctx.telegram, coupons=coupons)
    later.run_date = DAY1
    for c in coupons:
        c.valid_until = later.now - timedelta(hours=1)  # todos venceram
    publish_niche(later, later.config.niche("casa"))
    row = db.fetchone("SELECT * FROM content_item WHERE id = ?", (with_coupon[0]["id"],))
    assert row["status"] == "published" and row["coupon_code"] is None and "ACHADO10" not in row["caption"]


# ------------------------------------------------------ Sentinela e Reciclador
def test_sentinel_and_recycler(make_ctx, db):
    ctx = make_ctx()
    prepare(ctx)
    approve_all(ctx, db)
    night = make_ctx(now=slot_to_utc(DAY1, "23:00", TZ), telegram=ctx.telegram)
    publish_niche(night, night.config.niche("casa"))
    star = items(db)[0]
    sell(night, star["id"], "casa", commission=50)
    later = make_ctx(run_date=DAY1 + timedelta(days=4), now=night.now + timedelta(days=4), telegram=ctx.telegram)
    result = sentinel(later, later.config.niche("casa"))
    assert [w["id"] for w in result["winners"]] == [star["id"]]
    assert len(result["quiet"]) == 4  # os outros 4 sem nenhum pedido em 3+ dias
    assert champions(later, later.config.niche("casa")) == [star["product_id"]]

    # Depois do cooldown (7 dias), o campeão volta à pauta como "recycled".
    day9 = make_ctx(run_date=DAY1 + timedelta(days=9), now=night.now + timedelta(days=9), telegram=ctx.telegram)
    for n in day9.niches(("active", "candidate")):
        from src.pipeline.ingest import ingest
        from src.pipeline.score import score_niche
        from src.pipeline.transform import transform

        ingest(day9, n), transform(day9, n), score_niche(day9, n)
    create_content(day9, day9.config.niche("casa"))
    recycled = db.fetchall(
        "SELECT product_id FROM content_item WHERE run_date = ? AND pick_reason = 'recycled'",
        ((DAY1 + timedelta(days=9)).isoformat(),),
    )
    assert [r["product_id"] for r in recycled] == [star["product_id"]]


# ------------------------------------------------------ Detector de link quebrado
def test_broken_link_reported_once(make_ctx, db):
    fake, ctx, night = guarded_setup(make_ctx, db)
    publish_niche(night, night.config.niche("casa"))
    first = db.fetchone("SELECT * FROM content_item WHERE status = 'published' AND niche_id = 'casa' LIMIT 1")
    fake.unavailable.add(db.scalar("SELECT item_id FROM product WHERE id = ?", (first["product_id"],)))
    broken = check_published_links(night)
    assert [b["content_id"] for b in broken] == [first["id"]]
    assert check_published_links(night) == []  # já avisado


# ------------------------------------------------------ Mercado, horários e A/B
def test_market_report_suggests_candidate(make_ctx, db):
    ctx = make_ctx()
    prepare(ctx)
    for n in ctx.niches(("candidate",)):
        from src.pipeline.ingest import ingest
        from src.pipeline.score import score_niche
        from src.pipeline.transform import transform

        ingest(ctx, n), transform(ctx, n), score_niche(ctx, n)
    text = "\n".join(market_report(ctx))
    assert "Analista de mercado" in text and "Garimpo Tech (candidato)" in text


def test_slots_and_ab(make_ctx, db):
    ctx = make_ctx()
    assert variant_for("abc12345zz", False) == "A"
    split = [variant_for(f"post{i:02d}xx", True) for i in range(40)]
    assert 10 < split.count("A") < 30
    assert cron_for_slots(["09:07", "18:07"], TZ) == '"7 12,21 * * *"'
    assert "Poucos posts" in "\n".join(slots_report(ctx, ctx.config.niche("casa")))
    prepare(ctx)
    approve_all(ctx, db)
    night = make_ctx(now=slot_to_utc(DAY1, "23:00", TZ), telegram=ctx.telegram)
    publish_niche(night, night.config.niche("casa"))
    assert "Laboratório A/B" in "\n".join(ab_report(night))


def test_slots_needs_enough_tested_hours(make_ctx, monkeypatch):
    ctx = make_ctx()
    one_hour = [{"hour": 23, "posts": 10, "clicks": 0, "commission": 35.0, "per_post": 3.5, "clicks_per_post": 0.0}]
    monkeypatch.setattr("src.agents.insights.slot_stats", lambda c, n: one_hour)
    text = "\n".join(slots_report(ctx, ctx.config.niche("casa")))
    assert "dados insuficientes" in text and "Sugestão" not in text  # não troca 4 slots por 1
    assert pct(0.155) == "15,5%" and dec(2.5) == "2,5"


# ------------------------------------------------------ Contador: cálculos puros
CFG = load_finance()


def test_tax_math_matches_official_examples():
    assert irpf_monthly(6000, CFG.irpf) == 394.54  # exemplo oficial da Receita (redução de 2026)
    assert irpf_monthly(5000, CFG.irpf) == 0.0
    assert irpf_monthly(10000, CFG.irpf) > 0
    assert mei_das(CFG.mei) == 86.05  # serviços, salário mínimo de R$ 1.621
    assert round(simples_rate(600_000, CFG.simples.anexo_iii), 4) == 0.1056
    assert round(simples_rate(600_000, CFG.simples.anexo_v), 4) == 0.1785
    with pytest.raises(ValueError):
        simples_rate(5_000_000, CFG.simples.anexo_iii)


def test_fator_r_respects_minimum_pro_labore():
    tiny = {s.key: s for s in tax_scenarios(30, 0, CFG, 0)}
    assert tiny["fator_r"].tax > tiny["simples_v"].tax  # 1 salário mínimo de pró-labore não compensa
    mid = {s.key: s for s in tax_scenarios(5000, 60000, CFG, 0)}
    assert mid["simples_v"].tax - mid["fator_r"].tax > 250
    assert not mid["mei"].allowed  # mei_permitido: false


def test_allocation_and_reinvest_does_not_reduce_tax():
    a = allocate(10_000, 1_000, 200, CFG.planejamento)
    assert a.tax_reserve == 1_100.0
    assert a.reinvest == round((10_000 - 1_100 - 200) * 0.2, 2)
    total = a.tax_reserve + a.costs + a.reinvest + a.emergency + a.withdraw + a.leftover
    assert round(total, 2) == 10_000
    assert shift_month("2026-01", -1) == "2025-12" and shift_month("2026-11", 2) == "2027-01"


# ------------------------------------------------------ Conciliador + Contador
def test_reconcile_and_accountant_report(make_ctx, db):
    ctx = make_ctx()
    prepare(ctx)
    content_id = items(db)[0]["id"]
    sell(ctx, content_id, "casa", 30, "COMPLETED")
    sell(ctx, content_id, "casa", 20, "PENDING")
    sell(ctx, content_id, "casa", 5, "CANCELLED")
    assert classify("Concluído", CFG) == "confirmed"
    rec = reconcile(ctx, "2026-10", CFG)["totals"]
    assert (rec["confirmed"], rec["pending"], rec["cancelled"], rec["orders"]) == (30, 20, 5, 3)
    csv_text = reconcile_csv(ctx, "2026-10", CFG).decode("utf-8-sig")
    assert csv_text.count("\n") == 4 and "situacao" in csv_text
    report = "\n".join(accountant_report(ctx, "2026-10", CFG))
    for expected in (
        "Contador · 2026-10",
        "Seu regime",
        "Comparação",
        "Reserva para impostos",
        "Reinvestir NÃO reduz o imposto",
        "Não é consultoria contábil",
    ):
        assert expected in report, expected


def test_mei_limit_risk(make_ctx, db):
    ctx = make_ctx()
    prepare(ctx)
    content_id = items(db)[0]["id"]
    for month in range(1, 10):  # R$ 9 mil/mês confirmados de jan a set
        sell(ctx, content_id, "casa", 9000, "COMPLETED", f"2026-{month:02d}-10T15:00:00+00:00")
    cfg = CFG.model_copy(update={"regime": "mei", "mei_permitido": True})
    report = "\n".join(accountant_report(ctx, "2026-10", cfg))
    assert "Passou do limite do MEI" in report  # 9 x R$ 9 mil = R$ 81 mil no ano até setembro


def test_commands_for_new_agents(make_ctx, db):
    ctx = make_ctx()
    prepare(ctx)
    for cmd in ("/imposto 2026-10", "/mercado", "/horarios casa", "/cupons", "/fechamento 2026-10"):
        ctx.telegram.push_command(cmd, "admin-chat", user_id=ADMIN_ID)
    process_updates(ctx)
    texts = [m.get("text", "") for m in ctx.telegram.sent if m["kind"] == "message"]
    joined = "\n".join(texts)
    for expected in (
        "Contador · 2026-10",
        "Analista de mercado",
        "Horários: Garimpo Casa",
        "Cupons válidos",
        "Conciliador · 2026-10",
    ):
        assert expected in joined, expected
    assert any(m["kind"] == "document" and m["filename"] == "fechamento-2026-10.csv" for m in ctx.telegram.sent)


def test_repo_finance_config_is_valid_and_dated():
    assert CFG.regime == "simples" and CFG.mei_permitido is False
    assert CFG.fontes and CFG.atualizado_em.year >= 2026
