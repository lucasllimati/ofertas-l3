from datetime import date

from src.config.models import Filters, ScoreWeights
from src.pipeline.content import pick_products
from src.pipeline.score import Candidate, compute_scores, percentile_ranks, real_discount, reject_reason, sales_delta

DAY = date(2026, 10, 20)


def cand(pid="p", **kw):
    base = dict(
        product_id=pid,
        title="Produto",
        category=None,
        price=50.0,
        rating=4.8,
        reviews=None,
        commission_rate=0.1,
        sales_total=1000,
    )
    base.update(kw)
    return Candidate(**base)


def test_percentile_ranks_ties_and_none():
    assert percentile_ranks([10, None, 30, 10]) == [0.25, None, 1.0, 0.25]
    assert percentile_ranks([5]) == [0.5]
    assert percentile_ranks([None]) == [None]


def test_sales_delta_uses_closest_previous_day():
    c = cand(sales_total=150, history={"2026-10-18": (50.0, 100), "2026-10-19": (50.0, 130)})
    assert sales_delta(c, DAY, 1) == 20
    assert sales_delta(c, DAY, 7) is None  # sem histórico tão antigo
    reset = cand(sales_total=10, history={"2026-10-19": (50.0, 500)})
    assert sales_delta(reset, DAY, 1) is None  # contador reiniciou: não é venda negativa


def test_accelerating_product_beats_stagnant():
    hot = cand("hot", sales_total=300, history={"2026-10-19": (50.0, 100), "2026-10-13": (50.0, 50)})
    cold = cand("cold", sales_total=5000, history={"2026-10-19": (50.0, 4999), "2026-10-13": (50.0, 4990)})
    (s_hot, c_hot), (s_cold, _) = compute_scores([hot, cold], DAY, ScoreWeights())
    assert s_hot > s_cold
    assert c_hot["sales_1d"] == 200


def test_real_discount_against_median():
    c = cand(price=40.0, history={f"2026-10-{d:02d}": (80.0, None) for d in range(10, 19)})
    assert real_discount(c, DAY) == 1.0  # 50% abaixo da mediana = máximo
    inflated = cand(price=80.0, history={f"2026-10-{d:02d}": (60.0, None) for d in range(10, 19)})
    assert real_discount(inflated, DAY) == 0.0


def test_reject_reasons():
    f = Filters(min_rating=4.5, min_commission_rate=0.05, blocked_categories=["remédio"], price_max=100)
    assert reject_reason(cand(title="Remedio para gato"), f).startswith("categoria bloqueada")  # sem acento
    assert "nota" in reject_reason(cand(rating=4.0), f)
    assert "comissão" in reject_reason(cand(commission_rate=0.01), f)
    assert "preço acima" in reject_reason(cand(price=150), f)
    assert reject_reason(cand(rating=None, commission_rate=None), f) is None  # desconhecido não reprova


def test_pick_products_exploration_is_deterministic():
    ranked = [{"id": i} for i in range(30)]
    a = pick_products(ranked, 5, 0.2, "casa|2026-10-20")
    b = pick_products(ranked, 5, 0.2, "casa|2026-10-20")
    assert a == b
    assert [r for _, r in a].count("exploration") == 1
    assert [p["id"] for p, r in a if r == "top"] == [0, 1, 2, 3]
    explored = [p["id"] for p, r in a if r == "exploration"][0]
    assert 4 <= explored < 24


def test_pick_products_small_pool_uses_only_top():
    picks = pick_products([{"id": 1}, {"id": 2}], 5, 0.2, "s")
    assert [r for _, r in picks] == ["top", "top"]
