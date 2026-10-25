"""Agentes Conciliador e Contador (trabalham com o Financeiro).

Conciliador: fecha o mês com comissão estimada x confirmada x cancelada, por loja e por nicho, e
manda um CSV para a contabilidade.

Contador: a partir da comissão confirmada do mês e dos últimos 12 meses, estima o imposto no seu
regime e compara com as alternativas (Simples Anexo III/V com Fator R, MEI se permitido, pessoa
física), sugere como dividir o dinheiro (reserva de impostos, reinvestimento, caixa, retirada),
aponta riscos e otimizações legais.

⚠️ Estimativas para planejamento, com as regras de config/finance.yaml (com data e fonte).
Não substitui contador: regime, CNAE e cálculo final precisam ser validados por um profissional.
Ponto importante: no MEI e no Simples o imposto incide sobre a RECEITA BRUTA; reinvestir não
reduz o imposto. O que reduz legalmente é o regime certo e, no Simples, o Fator R (pró-labore).
"""

from __future__ import annotations

import csv
import html
import io
import statistics
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal
from zoneinfo import ZoneInfo

import yaml
from pydantic import BaseModel, ConfigDict, Field

from src.common.util import brl, iso, pct
from src.context import AppContext

ROOT = Path(__file__).resolve().parents[2]
FINANCE_PATH = ROOT / "config" / "finance.yaml"
CANCELLED = ("cancelled", "canceled", "cancelado", "invalid")
MIN_SAVING = 50.0  # economia mensal mínima (R$) para recomendar uma mudança
DISCLAIMER = (
    "<i>Estimativa para planejamento com as regras de config/finance.yaml. Não é consultoria contábil: "
    "valide regime, CNAE e valores com um contador.</i>"
)


# ------------------------------------------------------------------ configuração
class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Band(_Strict):
    ate: float | None
    aliquota: float = Field(ge=0, le=1)
    deducao: float = Field(0, ge=0)


class Planning(_Strict):
    margem_reserva_impostos: float = Field(0.10, ge=0, le=1)
    reinvestimento_pct: float = Field(0.20, ge=0, le=1)
    reserva_emergencia_pct: float = Field(0.10, ge=0, le=1)
    retirada_alvo_mensal: float = Field(0, ge=0)


class MeiRules(_Strict):
    limite_anual: float
    tolerancia_excesso: float
    salario_minimo: float
    inss_pct_salario_minimo: float
    iss_fixo: float


class SimplesRules(_Strict):
    anexo: Literal["iii", "v", "fator_r"] = "fator_r"
    folha_12m: float = Field(0, ge=0)
    fator_r_minimo: float = 0.28
    anexo_iii: list[Band]
    anexo_v: list[Band]


class ProLabore(_Strict):
    minimo_mensal: float = 0.0
    inss_pct: float
    teto_inss: float


class Dividends(_Strict):
    limite_mensal_sem_retencao: float
    retencao_pct: float


class Redutor(_Strict):
    isento_ate: float
    valor_maximo: float
    parcial_ate: float
    a: float
    b: float


class Irpf(_Strict):
    desconto_simplificado: float
    tabela_mensal: list[Band]
    redutor: Redutor


class FinanceConfig(_Strict):
    version: int = 1
    atualizado_em: date
    regime: Literal["pf", "mei", "simples"] = "simples"
    mei_permitido: bool = False
    dia_fechamento: int = Field(5, ge=1, le=28)
    cambio_usd: float = Field(5.4, gt=0)
    custos_fixos_mensais: float = Field(0, ge=0)
    status_confirmados: list[str]
    planejamento: Planning = Planning()
    mei: MeiRules
    simples: SimplesRules
    pro_labore: ProLabore
    dividendos: Dividends
    irpf: Irpf
    fontes: list[str] = []


@lru_cache(maxsize=4)
def load_finance(path: str | None = None) -> FinanceConfig:
    file = Path(path) if path else FINANCE_PATH
    return FinanceConfig.model_validate(yaml.safe_load(file.read_text(encoding="utf-8")))


# --------------------------------------------------------------- cálculos puros
def simples_rate(rbt12: float, bands: list[Band]) -> float:
    """Alíquota efetiva = (RBT12 x nominal - parcela a deduzir) / RBT12."""
    if rbt12 <= 0:
        return bands[0].aliquota
    for band in bands:
        if band.ate is None or rbt12 <= band.ate:
            return max(0.0, (rbt12 * band.aliquota - band.deducao) / rbt12)
    raise ValueError("faturamento acima do teto do Simples Nacional (R$ 4,8 milhões em 12 meses)")


def irpf_monthly(income: float, rules: Irpf, deductions: float = 0.0) -> float:
    """IR mensal: tabela progressiva sobre (renda - max(deduções, desconto simplificado)) e a redução de 2026."""
    if income <= 0:
        return 0.0
    base = income - max(deductions, rules.desconto_simplificado)
    tax = 0.0
    for band in rules.tabela_mensal:
        if band.ate is None or base <= band.ate:
            tax = max(0.0, base * band.aliquota - band.deducao)
            break
    r = rules.redutor
    if income <= r.isento_ate:
        reduction = min(tax, r.valor_maximo)
    elif income <= r.parcial_ate:
        reduction = max(0.0, r.a - r.b * income)
    else:
        reduction = 0.0
    return round(max(0.0, tax - reduction), 2)


def inss_pro_labore(pro_labore: float, rules: ProLabore) -> float:
    return round(min(pro_labore, rules.teto_inss) * rules.inss_pct, 2)


def mei_das(rules: MeiRules) -> float:
    return round(rules.salario_minimo * rules.inss_pct_salario_minimo + rules.iss_fixo, 2)


@dataclass
class Scenario:
    key: str
    name: str
    tax: float  # total do mês (imposto + encargos do pró-labore quando houver)
    rate: float
    allowed: bool = True
    notes: list[str] = field(default_factory=list)
    applies_now: bool = True  # Fator R: a folha atual já garante o Anexo III?


def tax_scenarios(revenue: float, rbt12: float, cfg: FinanceConfig, ytd: float) -> list[Scenario]:
    """Imposto estimado do mês em cada regime. `rbt12` = receita dos 12 meses anteriores ao mês."""
    rbt = rbt12 if rbt12 > 0 else revenue * 12  # início de atividade: anualiza o mês
    rate_iii = simples_rate(rbt, cfg.simples.anexo_iii)
    rate_v = simples_rate(rbt, cfg.simples.anexo_v)
    out = [
        Scenario("simples_iii", "Simples Anexo III", round(revenue * rate_iii, 2), rate_iii),
        Scenario("simples_v", "Simples Anexo V", round(revenue * rate_v, 2), rate_v),
    ]

    # Fator R: folha de 12 meses >= 28% da receita de 12 meses leva ao Anexo III.
    needed_year = cfg.simples.fator_r_minimo * rbt
    monthly_pl = max(needed_year / 12, cfg.pro_labore.minimo_mensal)  # pró-labore >= 1 salário mínimo
    pl_inss = inss_pro_labore(monthly_pl, cfg.pro_labore)
    pl_irpf = irpf_monthly(monthly_pl, cfg.irpf, deductions=pl_inss)
    already = cfg.simples.folha_12m >= needed_year
    fator_r = Scenario(
        "fator_r",
        "Simples III com Fator R (pró-labore)",
        round(revenue * rate_iii + (0 if already else pl_inss + pl_irpf), 2),
        rate_iii,
        notes=[
            "folha atual já atinge 28%: Anexo III"
            if already
            else f"pró-labore de {brl(monthly_pl)}/mês (INSS {brl(pl_inss)} + IR {brl(pl_irpf)} entram no custo)"
        ],
        applies_now=already,
    )
    out.append(fator_r)

    das = mei_das(cfg.mei)
    mei_cap = cfg.mei.limite_anual
    mei_notes = [] if cfg.mei_permitido else ["só se o contador confirmar que sua ocupação cabe no MEI"]
    if ytd + revenue > mei_cap:
        mei_notes.append("faturamento do ano acima do limite do MEI")
    out.append(
        Scenario(
            "mei",
            "MEI",
            das,
            das / revenue if revenue else 0.0,
            allowed=cfg.mei_permitido and ytd + revenue <= mei_cap * (1 + cfg.mei.tolerancia_excesso),
            notes=mei_notes,
        )
    )
    pf_tax = irpf_monthly(revenue, cfg.irpf)
    out.append(Scenario("pf", "Pessoa física (IR mensal)", pf_tax, pf_tax / revenue if revenue else 0.0))
    return out


def current_scenario(scenarios: list[Scenario], cfg: FinanceConfig) -> Scenario:
    by_key = {s.key: s for s in scenarios}
    if cfg.regime == "mei":
        return by_key["mei"]
    if cfg.regime == "pf":
        return by_key["pf"]
    if cfg.simples.anexo == "iii":
        return by_key["simples_iii"]
    if cfg.simples.anexo == "v":
        return by_key["simples_v"]
    # Fator R: sem a folha necessária hoje, a empresa está no Anexo V.
    return by_key["fator_r"] if by_key["fator_r"].applies_now else by_key["simples_v"]


@dataclass
class Allocation:
    tax_reserve: float
    costs: float
    reinvest: float
    emergency: float
    withdraw: float
    leftover: float


def allocate(revenue: float, tax: float, costs: float, plan: Planning) -> Allocation:
    reserve = round(tax * (1 + plan.margem_reserva_impostos), 2)
    available = max(0.0, revenue - reserve - costs)
    reinvest = round(available * plan.reinvestimento_pct, 2)
    emergency = round(available * plan.reserva_emergencia_pct, 2)
    free = max(0.0, available - reinvest - emergency)
    withdraw = round(min(plan.retirada_alvo_mensal, free) if plan.retirada_alvo_mensal else free, 2)
    return Allocation(reserve, round(costs, 2), reinvest, emergency, withdraw, round(free - withdraw, 2))


# ------------------------------------------------------------ dados do banco
def month_bounds(ym: str, tz: str) -> tuple[str, str]:
    year, month = (int(x) for x in ym.split("-"))
    start = datetime.combine(date(year, month, 1), time(0), tzinfo=ZoneInfo(tz))
    nxt = date(year + (month == 12), month % 12 + 1, 1)
    return iso(start), iso(datetime.combine(nxt, time(0), tzinfo=ZoneInfo(tz)))


def shift_month(ym: str, months: int) -> str:
    year, month = (int(x) for x in ym.split("-"))
    total = year * 12 + (month - 1) + months
    return f"{total // 12:04d}-{total % 12 + 1:02d}"


def month_rows(ctx: AppContext, ym: str) -> list[dict[str, Any]]:
    start, end = month_bounds(ym, ctx.config.defaults.timezone)
    return ctx.db.fetchall(
        "SELECT * FROM conversion WHERE purchase_time >= ? AND purchase_time < ? ORDER BY purchase_time", (start, end)
    )


def classify(status: str | None, cfg: FinanceConfig) -> str:
    s = (status or "").strip().lower()
    if s in CANCELLED:
        return "cancelled"
    if s in {x.lower() for x in cfg.status_confirmados}:
        return "confirmed"
    return "pending"


def confirmed_revenue(ctx: AppContext, ym: str, cfg: FinanceConfig) -> float:
    return round(
        sum(float(r["commission"] or 0) for r in month_rows(ctx, ym) if classify(r["status"], cfg) == "confirmed"), 2
    )


def reconcile(ctx: AppContext, ym: str, cfg: FinanceConfig) -> dict[str, Any]:
    rows = month_rows(ctx, ym)
    totals = {"confirmed": 0.0, "pending": 0.0, "cancelled": 0.0, "orders": 0, "gmv": 0.0, "cancelled_orders": 0}
    by_platform: dict[str, float] = {}
    by_niche: dict[str, float] = {}
    for r in rows:
        kind = classify(r["status"], cfg)
        value = float(r["commission"] or 0)
        totals[kind] += value
        totals["orders"] += 1
        if kind == "cancelled":
            totals["cancelled_orders"] += 1
            continue
        totals["gmv"] += float(r["amount"] or 0)
        by_platform[r["platform"]] = by_platform.get(r["platform"], 0) + value
        key = r["niche_id"] or "sem atribuição"
        by_niche[key] = by_niche.get(key, 0) + value
    totals["cancel_rate"] = totals["cancelled_orders"] / totals["orders"] if totals["orders"] else 0.0
    return {
        "totals": {k: round(v, 4) if isinstance(v, float) else v for k, v in totals.items()},
        "by_platform": by_platform,
        "by_niche": by_niche,
        "rows": rows,
    }


def reconcile_csv(ctx: AppContext, ym: str, cfg: FinanceConfig) -> bytes:
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(
        [
            "data_compra",
            "loja",
            "pedido",
            "item",
            "nicho",
            "canal",
            "post",
            "status",
            "situacao",
            "valor_venda",
            "comissao",
        ]
    )
    for r in reconcile(ctx, ym, cfg)["rows"]:
        writer.writerow(
            [
                r["purchase_time"],
                r["platform"],
                r["order_id"],
                r["item_id"],
                r["niche_id"] or "",
                r["channel"] or "",
                r["content_id"] or "",
                r["status"] or "",
                classify(r["status"], cfg),
                f"{float(r['amount'] or 0):.2f}",
                f"{float(r['commission'] or 0):.2f}",
            ]
        )
    return buf.getvalue().encode("utf-8-sig")  # BOM: abre com acento certo no Excel


def llm_cost_brl(ctx: AppContext, ym: str, cfg: FinanceConfig) -> float:
    start, end = month_bounds(ym, ctx.config.defaults.timezone)
    usd = ctx.db.scalar(
        "SELECT coalesce(sum(cost_usd), 0) FROM agent_run WHERE created_at >= ? AND created_at < ?", (start, end)
    )
    return round(float(usd or 0) * cfg.cambio_usd, 2)


def niche_epc(ctx: AppContext, days: int = 30) -> list[tuple[str, float, int]]:
    since = iso(ctx.now - timedelta(days=days))
    out = []
    for niche in ctx.niches():
        clicks = int(
            ctx.db.scalar("SELECT count(*) FROM click_event WHERE niche_id = ? AND ts >= ?", (niche.id, since)) or 0
        )
        placeholders = ", ".join("?" for _ in CANCELLED)
        comm = float(
            ctx.db.scalar(
                "SELECT coalesce(sum(commission), 0) FROM conversion WHERE niche_id = ? AND purchase_time >= ? "
                f"AND lower(coalesce(status, '')) NOT IN ({placeholders})",
                (niche.id, since, *CANCELLED),
            )
            or 0
        )
        out.append((niche.name, comm / clicks if clicks else 0.0, clicks))
    return sorted(out, key=lambda x: -x[1])


# ------------------------------------------------------------------ relatórios
def accountant_report(ctx: AppContext, ym: str, cfg: FinanceConfig | None = None) -> list[str]:
    cfg = cfg or load_finance()
    rec = reconcile(ctx, ym, cfg)
    t = rec["totals"]
    revenue = round(t["confirmed"], 2)
    rbt12 = sum(confirmed_revenue(ctx, shift_month(ym, -i), cfg) for i in range(1, 13))
    year = ym[:4]
    ytd = sum(confirmed_revenue(ctx, f"{year}-{m:02d}", cfg) for m in range(1, int(ym[5:])))
    scen = tax_scenarios(revenue, rbt12, cfg, ytd)
    mine = current_scenario(scen, cfg)
    costs = cfg.custos_fixos_mensais + llm_cost_brl(ctx, ym, cfg)
    alloc = allocate(revenue, mine.tax, costs, cfg.planejamento)

    lines = [f"<b>🧮 Contador · {ym}</b>", ""]
    lines += [
        f"Comissão confirmada: <b>{brl(revenue)}</b> · pendente {brl(t['pending'])} · cancelada {brl(t['cancelled'])}",
        f"Últimos 12 meses (RBT12): {brl(rbt12)} · ano até o mês anterior: {brl(ytd)}",
        "",
        f"<b>Seu regime ({html.escape(mine.name)})</b>: imposto estimado {brl(mine.tax)} ({pct(mine.rate)} da receita)",
        "",
        "<b>Comparação</b>",
    ]
    for s in scen:
        flag = "" if s.allowed else " (não aplicável)"
        notes = f" · {html.escape('; '.join(s.notes))}" if s.notes else ""
        lines.append(f"{html.escape(s.name)}: {brl(s.tax)} ({pct(s.rate)}){flag}{notes}")

    lines += [
        "",
        "<b>Como dividir o dinheiro do mês</b>",
        f"• Reserva para impostos: {brl(alloc.tax_reserve)} "
        f"(imposto + {cfg.planejamento.margem_reserva_impostos:.0%} de margem)",
        f"• Custos (fixos + IA): {brl(alloc.costs)}",
        f"• Reinvestir no crescimento: {brl(alloc.reinvest)}",
        f"• Caixa de emergência: {brl(alloc.emergency)}",
        f"• Retirada sugerida: <b>{brl(alloc.withdraw)}</b>"
        + (f" (sobra {brl(alloc.leftover)} no caixa)" if alloc.leftover > 0 else ""),
    ]
    lines += ["", "<b>Otimizações legais</b>", *optimizations(scen, mine, cfg, alloc, ctx)]
    lines += ["", "<b>Riscos</b>", *risks(ctx, ym, cfg, rec, revenue, ytd, costs, alloc)]
    lines += ["", DISCLAIMER]
    return lines


def optimizations(scen, mine: Scenario, cfg: FinanceConfig, alloc: Allocation, ctx: AppContext) -> list[str]:
    tips = []
    allowed = [s for s in scen if s.allowed and s.key != "pf"]
    best = min(allowed, key=lambda s: s.tax, default=None)
    if best and best.key != mine.key and mine.tax - best.tax >= MIN_SAVING:
        tips.append(
            f"• {html.escape(best.name)} sairia {brl(mine.tax - best.tax)}/mês mais barato que o seu regime atual. "
            "Leve essa comparação ao contador."
        )
    by_key = {s.key: s for s in scen}
    if cfg.regime == "simples" and mine.key == "simples_v" and mine.tax - by_key["fator_r"].tax >= MIN_SAVING:
        tips.append(
            f"• Fator R: com o pró-labore indicado, o imposto cairia de {brl(mine.tax)} para "
            f"{brl(by_key['fator_r'].tax)} (economia {brl(mine.tax - by_key['fator_r'].tax)}/mês)."
        )
    if cfg.regime in ("mei", "simples"):
        tips.append(
            "• Reinvestir NÃO reduz o imposto no MEI nem no Simples: ele é calculado sobre a receita bruta. "
            "Reinvista porque traz retorno (ex.: impulsionar os posts 🔥 da Sentinela), não para abater imposto."
        )
    epc = niche_epc(ctx)
    if len(epc) >= 2 and epc[0][2] >= 50:
        tips.append(
            f"• Direcione o reinvestimento para {html.escape(epc[0][0])} "
            f"(EPC {brl(epc[0][1])}/clique, o maior em 30 dias)."
        )
    if alloc.withdraw > cfg.dividendos.limite_mensal_sem_retencao:
        tips.append(
            f"• Lucros acima de {brl(cfg.dividendos.limite_mensal_sem_retencao)}/mês da mesma empresa têm retenção de "
            f"{cfg.dividendos.retencao_pct:.0%} sobre o total: avalie com o contador como distribuir."
        )
    return tips or ["• Nenhuma otimização relevante neste mês."]


def risks(ctx: AppContext, ym: str, cfg: FinanceConfig, rec, revenue, ytd, costs, alloc) -> list[str]:
    out = []
    t = rec["totals"]
    if cfg.regime == "mei":
        used = (ytd + revenue) / cfg.mei.limite_anual
        if used >= 1 + cfg.mei.tolerancia_excesso:
            out.append(
                "🚨 Faturamento do ano passou de 120% do limite do MEI: desenquadramento retroativo a janeiro, "
                "com multa e juros. Fale com o contador já."
            )
        elif used >= 1:
            out.append(
                "⚠️ Passou do limite do MEI (até 20%): DAS complementar sobre o excesso e saída do MEI em janeiro."
            )
        elif used >= 0.8:
            out.append(f"⚠️ {used:.0%} do limite anual do MEI usado: planeje a migração para ME.")
        if not cfg.mei_permitido:
            out.append("⚠️ Regime MEI sem confirmação de que a sua ocupação é permitida: risco de desenquadramento.")
    recent = [confirmed_revenue(ctx, shift_month(ym, -i), cfg) for i in range(0, 3)]
    projection = statistics.mean(recent) * 12
    if cfg.regime == "mei" and projection > cfg.mei.limite_anual:
        out.append(f"📈 No ritmo dos últimos 3 meses, o ano fecha em {brl(projection)}: acima do limite do MEI.")
    if cfg.regime == "simples" and projection > 4_800_000:
        out.append("📈 Projeção acima do teto do Simples (R$ 4,8 mi): planeje a mudança de regime.")
    total_platform = sum(rec["by_platform"].values())
    for platform, value in rec["by_platform"].items():
        if total_platform > 0 and value / total_platform > 0.8:
            out.append(
                f"⚠️ {value / total_platform:.0%} da comissão vem de {platform}: mudança de regra lá derruba a "
                "receita. Diversifique (ML/Amazon)."
            )
    if t["cancel_rate"] > 0.2:
        out.append(f"⚠️ {t['cancel_rate']:.0%} dos pedidos cancelados: revise produtos e vendedores.")
    if t["pending"] > revenue and t["pending"] > 0:
        out.append(f"ℹ️ {brl(t['pending'])} ainda pendentes: não conte como dinheiro até confirmar.")
    previous = confirmed_revenue(ctx, shift_month(ym, -1), cfg)
    if previous > 0 and revenue < previous * 0.7:
        out.append(f"📉 Receita {1 - revenue / previous:.0%} menor que no mês anterior.")
    if revenue > 0 and costs / revenue > 0.10:
        out.append(f"⚠️ Custos ({brl(costs)}) passam de 10% da receita.")
    if (date.today() - cfg.atualizado_em).days > 365:
        out.append("⚠️ config/finance.yaml tem mais de 1 ano: atualize alíquotas e tetos.")
    return out or ["• Nenhum risco relevante neste mês."]


def reconcile_report(ctx: AppContext, ym: str, cfg: FinanceConfig | None = None) -> list[str]:
    cfg = cfg or load_finance()
    rec = reconcile(ctx, ym, cfg)
    t = rec["totals"]
    lines = [
        f"<b>📒 Conciliador · {ym}</b>",
        f"Pedidos: {t['orders']} · vendas {brl(t['gmv'])}",
        f"Comissão confirmada {brl(t['confirmed'])} · pendente {brl(t['pending'])} · cancelada {brl(t['cancelled'])} "
        f"({t['cancel_rate']:.0%} dos pedidos)",
    ]
    if rec["by_platform"]:
        lines.append("Por loja: " + " · ".join(f"{p} {brl(v)}" for p, v in sorted(rec["by_platform"].items())))
    if rec["by_niche"]:
        lines.append(
            "Por nicho: " + " · ".join(f"{html.escape(n)} {brl(v)}" for n, v in sorted(rec["by_niche"].items()))
        )
    return lines


def previous_month(ctx: AppContext) -> str:
    today = ctx.now.astimezone(ZoneInfo(ctx.config.defaults.timezone)).date()
    return shift_month(f"{today.year:04d}-{today.month:02d}", -1)


def current_month(ctx: AppContext) -> str:
    today = ctx.now.astimezone(ZoneInfo(ctx.config.defaults.timezone)).date()
    return f"{today.year:04d}-{today.month:02d}"


def is_closing_day(ctx: AppContext, cfg: FinanceConfig | None = None) -> bool:
    cfg = cfg or load_finance()
    return ctx.now.astimezone(ZoneInfo(ctx.config.defaults.timezone)).day == cfg.dia_fechamento
