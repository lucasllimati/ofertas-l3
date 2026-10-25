"""Acesso ao Claude compartilhado pelos agentes: chamada com JSON validado por schema, teto de custo
diário (por nicho e global) e registro de cada chamada em agent_run.

Regras para quem usa: dados externos sempre delimitados em tags, nunca segredo no prompt e sempre
um caminho sem LLM quando o teto for atingido ou a chamada falhar.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any

from src.common.db import Database
from src.common.util import iso, random_id, utcnow

# US$ por milhão de tokens: entrada, saída, leitura de cache, escrita de cache.
PRICES: dict[str, tuple[float, float, float, float]] = {
    "claude-haiku-5-5": (0.10, 0.50, 0.01, 0.125),
    "claude-sonnet-5-5": (2.00, 10.00, 0.20, 2.50),
    "claude-opus-5-5": (4.00, 20.00, 0.20, 5.00),
}
EST_INPUT_TOKENS = 1500
MAX_TOKENS = 2000


class BudgetExceeded(RuntimeError):
    pass


@dataclass
class LlmUsage:
    model: str
    input_tokens: int
    output_tokens: int
    cost_usd: float
    latency_ms: int


class LlmGateway:
    def __init__(self, client: Any, db: Database, run_id: str, global_budget_usd: float):
        self.client = client
        self.db = db
        self.run_id = run_id
        self.global_budget = global_budget_usd

    def spent_today(self, niche_id: str | None = None) -> float:
        start = utcnow().strftime("%Y-%m-%dT00:00:00")
        if niche_id:
            value = self.db.scalar(
                "SELECT coalesce(sum(cost_usd), 0) FROM agent_run WHERE created_at >= ? AND niche_id = ?",
                (start, niche_id),
            )
        else:
            value = self.db.scalar("SELECT coalesce(sum(cost_usd), 0) FROM agent_run WHERE created_at >= ?", (start,))
        return float(value or 0)

    def check_budget(self, niche_id: str, niche_budget_usd: float, model: str, max_tokens: int = MAX_TOKENS) -> None:
        """Bloqueia a chamada se o pior caso estourar o teto do nicho ou o global."""
        price_in, price_out, *_ = PRICES.get(model, PRICES["claude-opus-5-5"])
        worst = (EST_INPUT_TOKENS * price_in + max_tokens * price_out) / 1e6
        if self.spent_today(niche_id) + worst > niche_budget_usd:
            raise BudgetExceeded(f"orçamento diário de LLM do nicho {niche_id} atingido")
        if self.spent_today() + worst > self.global_budget:
            raise BudgetExceeded("orçamento diário global de LLM atingido")

    def record(self, niche_id: str, agent: str, usage: LlmUsage | None, status: str) -> None:
        self.db.execute(
            "INSERT INTO agent_run (id, run_id, niche_id, agent, model, input_tokens, output_tokens, "
            "cost_usd, latency_ms, status, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                random_id(),
                self.run_id,
                niche_id,
                agent,
                usage.model if usage else None,
                usage.input_tokens if usage else 0,
                usage.output_tokens if usage else 0,
                usage.cost_usd if usage else 0.0,
                usage.latency_ms if usage else 0,
                status,
                iso(utcnow()),
            ),
        )

    def call_json(
        self, model: str, system: str, user: str, schema: dict, max_tokens: int = MAX_TOKENS
    ) -> tuple[dict, LlmUsage]:
        """Uma chamada com saída em JSON garantida pelo schema. Levanta RuntimeError se não terminar
        normalmente (recusa, limite de tokens): quem chama cai no caminho sem LLM."""
        started = time.monotonic()
        resp = self.client.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": user}],
            output_config={"effort": "low", "format": {"type": "json_schema", "schema": schema}},
        )
        u = resp.usage
        cache_read = getattr(u, "cache_read_input_tokens", 0) or 0
        cache_write = getattr(u, "cache_creation_input_tokens", 0) or 0
        p_in, p_out, p_read, p_write = PRICES.get(model, PRICES["claude-opus-5-5"])
        cost = (u.input_tokens * p_in + u.output_tokens * p_out + cache_read * p_read + cache_write * p_write) / 1e6
        usage = LlmUsage(
            model,
            u.input_tokens + cache_read + cache_write,
            u.output_tokens,
            round(cost, 6),
            int((time.monotonic() - started) * 1000),
        )
        if resp.stop_reason != "end_turn":
            raise RuntimeError(f"stop_reason={resp.stop_reason}")
        text = next((b.text for b in resp.content if b.type == "text"), "")
        return json.loads(text), usage
