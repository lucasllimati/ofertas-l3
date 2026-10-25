-- Agentes da v0.4 (docs/agentes.md).

-- Copy em JSON (título/bullets/hashtags): permite refazer a legenda quando o preço muda (Vigia de preço)
-- sem chamar o LLM de novo.
ALTER TABLE content_item ADD COLUMN copy_json TEXT;
-- Laboratório A/B: variante de estilo da copy (A ou B).
ALTER TABLE content_item ADD COLUMN copy_variant TEXT;
-- Caçador de cupons: cupom anunciado no post (NULL = sem cupom).
ALTER TABLE content_item ADD COLUMN coupon_code TEXT;
-- Motivo da última mudança de status feita por um agente (ex.: "preço mudou de R$ 39,90 para R$ 49,90").
ALTER TABLE content_item ADD COLUMN status_reason TEXT;

-- Classificador de conformidade: veredito por produto (evita pagar o LLM de novo para o mesmo produto).
CREATE TABLE IF NOT EXISTS compliance_check (
    product_id TEXT PRIMARY KEY REFERENCES product(id),
    verdict    TEXT NOT NULL,  -- ok | medicamento | replica | adulto | arma | tabaco_alcool | outro_proibido
    reason     TEXT,
    model      TEXT,
    checked_at TEXT NOT NULL
);
