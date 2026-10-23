"""Gold: score por nicho. O ranking é 100% determinístico (o LLM nunca decide ranking)."""

from __future__ import annotations

import json
import math
import statistics
from dataclasses import dataclass, field
from datetime import date, timedelta

from src.common.util import normalize_text
from src.config.models import Filters, Niche, ScoreWeights
from src.context import AppContext

MY_CHANNEL_MIN_CLICKS = 50
WINDOWS = (1, 7, 15, 30)


@dataclass
class Candidate:
    product_id: str
    title: str
    category: str | None
    price: float
    rating: float | None
    reviews: int | None
    commission_rate: float | None
    sales_total: int | None
    history: dict[str, tuple[float, int | None]] = field(default_factory=dict)  # dia -> (preço, vendas)
    clicks: int = 0
    commission_earned: float = 0.0


def percentile_ranks(values: list[float | None]) -> list[float | None]:
    """Rank percentual em [0, 1] com empates pela média; None continua None."""
    present = sorted((v, i) for i, v in enumerate(values) if v is not None)
    out: list[float | None] = [None] * len(values)
    n = len(present)
    if n == 0:
        return out
    if n == 1:
        out[present[0][1]] = 0.5
        return out
    i = 0
    while i < n:
        j = i
        while j + 1 < n and present[j + 1][0] == present[i][0]:
            j += 1
        rank = ((i + j) / 2) / (n - 1)
        for k in range(i, j + 1):
            out[present[k][1]] = rank
        i = j + 1
    return out


def sales_delta(c: Candidate, day: date, days: int) -> float | None:
    """Vendas na janela = sales_total de hoje - sales_total de N dias atrás (ou o mais próximo antes)."""
    if c.sales_total is None:
        return None
    target = (day - timedelta(days=days)).isoformat()
    past = [d for d in c.history if d <= target and c.history[d][1] is not None]
    if not past:
        return None
    before = c.history[max(past)][1]
    delta = c.sales_total - before
    return float(delta) if delta >= 0 else None  # contador que reinicia não vale como venda


def _blend(parts: list[tuple[float, float | None]], fallback: float | None) -> float:
    available = [(w, v) for w, v in parts if v is not None]
    if available:
        total = sum(w for w, _ in available)
        return sum(w * v for w, v in available) / total
    return fallback if fallback is not None else 0.5


def real_discount(c: Candidate, day: date) -> float:
    start = (day - timedelta(days=30)).isoformat()
    prices = [p for d, (p, _) in c.history.items() if start <= d < day.isoformat()]
    if len(prices) < 2:
        return 0.0
    median = statistics.median(prices)
    if median <= 0:
        return 0.0
    return max(0.0, min(0.5, (median - c.price) / median)) / 0.5


def quality(c: Candidate) -> float:
    if c.rating is None:
        return 0.5
    rating_part = max(0.0, min(1.0, (c.rating - 4.0) / 1.0))
    if c.reviews is None:
        return rating_part
    reviews_part = min(1.0, math.log10(c.reviews + 1) / 4)
    return 0.7 * rating_part + 0.3 * reviews_part


def reject_reason(c: Candidate, filters: Filters) -> str | None:
    text = normalize_text(f"{c.title} {c.category or ''}")
    for blocked in filters.blocked_categories:
        if normalize_text(blocked) in text:
            return f"categoria bloqueada: {blocked}"
    if c.rating is not None and c.rating < filters.min_rating:
        return f"nota {c.rating} < {filters.min_rating}"
    if c.reviews is not None and c.reviews < filters.min_reviews:
        return f"avaliações {c.reviews} < {filters.min_reviews}"
    if c.commission_rate is not None and c.commission_rate < filters.min_commission_rate:
        return f"comissão {c.commission_rate} < {filters.min_commission_rate}"
    if filters.price_min is not None and c.price < filters.price_min:
        return f"preço abaixo de {filters.price_min}"
    if filters.price_max is not None and c.price > filters.price_max:
        return f"preço acima de {filters.price_max}"
    return None


def compute_scores(
    candidates: list[Candidate], day: date, weights: ScoreWeights
) -> list[tuple[float, dict[str, float]]]:
    deltas = {w: [sales_delta(c, day, w) for c in candidates] for w in WINDOWS}
    ranks = {w: percentile_ranks(deltas[w]) for w in WINDOWS}
    level = percentile_ranks([float(c.sales_total) if c.sales_total is not None else None for c in candidates])
    commission = percentile_ranks(
        [c.price * c.commission_rate if c.commission_rate is not None else None for c in candidates]
    )
    epc = percentile_ranks(
        [c.commission_earned / c.clicks if c.clicks >= MY_CHANNEL_MIN_CLICKS else None for c in candidates]
    )
    w = weights.model_dump()
    total_w = sum(w.values())
    results = []
    for i, c in enumerate(candidates):
        comp = {
            "acceleration": _blend([(0.6, ranks[1][i]), (0.4, ranks[7][i])], level[i]),
            "consistency": _blend([(0.5, ranks[15][i]), (0.5, ranks[30][i])], level[i]),
            "commission": commission[i] if commission[i] is not None else 0.5,
            "quality": quality(c),
            "my_channel": epc[i] if epc[i] is not None else 0.5,
            "real_discount": real_discount(c, day),
        }
        score = sum(w[k] * comp[k] for k in comp) / total_w
        comp = {k: round(v, 4) for k, v in comp.items()}
        for win in WINDOWS:
            comp[f"sales_{win}d"] = deltas[win][i]
        results.append((round(score, 4), comp))
    return results


def load_candidates(ctx: AppContext, niche: Niche) -> list[Candidate]:
    day = ctx.run_date.isoformat()
    rows = ctx.db.fetchall(
        "SELECT p.id, p.title, p.category, p.reviews, d.price, d.rating, d.commission_rate, "
        "d.sales_total FROM raw_offer_niche m "
        "JOIN product p ON p.id = m.platform || ':' || m.item_id "
        "JOIN product_daily d ON d.product_id = p.id AND d.run_date = m.run_date "
        "WHERE m.run_date = ? AND m.niche_id = ?",
        (day, niche.id),
    )
    cands = {
        r["id"]: Candidate(
            product_id=r["id"],
            title=r["title"],
            category=r["category"],
            price=r["price"],
            rating=r["rating"],
            reviews=r["reviews"],
            commission_rate=r["commission_rate"],
            sales_total=r["sales_total"],
        )
        for r in rows
    }
    if not cands:
        return []
    start = (ctx.run_date - timedelta(days=31)).isoformat()
    for r in ctx.db.fetchall(
        "SELECT d.product_id, d.run_date, d.price, d.sales_total FROM product_daily d "
        "JOIN raw_offer_niche m ON d.product_id = m.platform || ':' || m.item_id "
        "WHERE m.run_date = ? AND m.niche_id = ? AND d.run_date >= ? AND d.run_date < ?",
        (day, niche.id, start, day),
    ):
        if r["product_id"] in cands:
            cands[r["product_id"]].history[r["run_date"]] = (r["price"], r["sales_total"])
    perf_start = (ctx.run_date - timedelta(days=30)).isoformat()
    for r in ctx.db.fetchall(
        "SELECT c.product_id, "
        "(SELECT count(*) FROM click_event e WHERE e.content_id = c.id) AS clicks, "
        "(SELECT coalesce(sum(v.commission), 0) FROM conversion v WHERE v.content_id = c.id) AS comm "
        "FROM content_item c WHERE c.niche_id = ? AND c.run_date >= ?",
        (niche.id, perf_start),
    ):
        if r["product_id"] in cands:
            cands[r["product_id"]].clicks += int(r["clicks"])
            cands[r["product_id"]].commission_earned += float(r["comm"])
    return list(cands.values())


def score_niche(ctx: AppContext, niche: Niche) -> dict[str, int]:
    day = ctx.run_date.isoformat()
    settings = niche.settings
    candidates = load_candidates(ctx, niche)
    scored = compute_scores(candidates, ctx.run_date, settings.score_weights)
    rows = []
    for c, (score, comp) in zip(candidates, scored, strict=True):
        rows.append([c.product_id, score, comp, reject_reason(c, settings.filters)])
    eligible = sorted((r for r in rows if r[3] is None), key=lambda r: (-r[1], r[0]))
    rank = {r[0]: i + 1 for i, r in enumerate(eligible)}
    with ctx.db.transaction():
        ctx.db.execute("DELETE FROM product_score WHERE niche_id = ? AND run_date = ?", (niche.id, day))
        ctx.db.executemany(
            "INSERT INTO product_score (niche_id, product_id, run_date, score, components, "
            "eligible, reject_reason, rank) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (niche.id, pid, day, score, json.dumps(comp), int(reason is None), reason, rank.get(pid))
                for pid, score, comp, reason in rows
            ],
        )
    return {"scored": len(rows), "eligible": len(eligible)}
