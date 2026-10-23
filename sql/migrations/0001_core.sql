-- Schema central. Roda em Postgres e SQLite: só TEXT/INTEGER/REAL.
-- Datas: TEXT 'YYYY-MM-DD'; instantes: TEXT ISO-8601 em UTC (ordenam corretamente como texto).

CREATE TABLE IF NOT EXISTS niche (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    status      TEXT NOT NULL,
    config_json TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);

-- Bronze: payload bruto por dia. Retenção de 60 dias.
CREATE TABLE IF NOT EXISTS raw_offer_snapshot (
    run_date   TEXT NOT NULL,
    platform   TEXT NOT NULL,
    item_id    TEXT NOT NULL,
    payload    TEXT NOT NULL,
    fetched_at TEXT NOT NULL,
    PRIMARY KEY (run_date, platform, item_id)
);

-- De qual nicho/palavra-chave cada oferta do dia veio.
CREATE TABLE IF NOT EXISTS raw_offer_niche (
    run_date TEXT NOT NULL,
    platform TEXT NOT NULL,
    item_id  TEXT NOT NULL,
    niche_id TEXT NOT NULL,
    keyword  TEXT NOT NULL,
    PRIMARY KEY (run_date, platform, item_id, niche_id)
);

-- Silver
CREATE TABLE IF NOT EXISTS product (
    id              TEXT PRIMARY KEY,           -- '<platform>:<item_id>'
    platform        TEXT NOT NULL,
    item_id         TEXT NOT NULL,
    title           TEXT NOT NULL,
    image_url       TEXT,
    product_url     TEXT,
    affiliate_url   TEXT,
    shop_name       TEXT,
    category        TEXT,
    rating          REAL,
    reviews         INTEGER,
    commission_rate REAL,
    price           REAL NOT NULL,
    price_original  REAL,
    sales_total     INTEGER,
    first_seen      TEXT NOT NULL,
    last_seen       TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS product_niche (
    product_id TEXT NOT NULL REFERENCES product(id),
    niche_id   TEXT NOT NULL,
    keyword    TEXT,
    first_seen TEXT NOT NULL,
    last_seen  TEXT NOT NULL,
    PRIMARY KEY (product_id, niche_id)
);

CREATE TABLE IF NOT EXISTS product_daily (
    product_id      TEXT NOT NULL REFERENCES product(id),
    run_date        TEXT NOT NULL,
    price           REAL NOT NULL,
    sales_total     INTEGER,
    rating          REAL,
    commission_rate REAL,
    PRIMARY KEY (product_id, run_date)
);

-- SCD2 de preço: valid_to NULL = preço vigente.
CREATE TABLE IF NOT EXISTS price_history (
    product_id TEXT NOT NULL REFERENCES product(id),
    valid_from TEXT NOT NULL,
    valid_to   TEXT,
    price      REAL NOT NULL,
    PRIMARY KEY (product_id, valid_from)
);

-- Gold
CREATE TABLE IF NOT EXISTS product_score (
    niche_id      TEXT NOT NULL,
    product_id    TEXT NOT NULL REFERENCES product(id),
    run_date      TEXT NOT NULL,
    score         REAL NOT NULL,
    components    TEXT NOT NULL,
    eligible      INTEGER NOT NULL,
    reject_reason TEXT,
    rank          INTEGER,
    PRIMARY KEY (niche_id, product_id, run_date)
);
CREATE INDEX IF NOT EXISTS ix_product_score_rank ON product_score (niche_id, run_date, rank);

-- Conteúdo e publicação
CREATE TABLE IF NOT EXISTS content_item (
    id                 TEXT PRIMARY KEY,         -- curto, vai no subId e no /go
    niche_id           TEXT NOT NULL,
    product_id         TEXT NOT NULL REFERENCES product(id),
    channel            TEXT NOT NULL,            -- telegram | instagram | tiktok
    run_date           TEXT NOT NULL,
    status             TEXT NOT NULL,            -- ready | pending_approval | approved | publishing
                                                 -- | published | rejected | expired | publish_unknown
    score              REAL NOT NULL,
    pick_reason        TEXT NOT NULL,            -- top | exploration
    caption            TEXT NOT NULL,
    copy_source        TEXT NOT NULL,            -- template | llm
    affiliate_url      TEXT NOT NULL,
    tracked_url        TEXT NOT NULL,
    price_at_creation  REAL NOT NULL,
    scheduled_for      TEXT NOT NULL,            -- UTC ISO
    media_file_id      TEXT,                     -- file_id do Telegram (reaproveitado ao publicar)
    preview_message_id TEXT,
    external_id        TEXT,
    created_at         TEXT NOT NULL,
    updated_at         TEXT NOT NULL,
    published_at       TEXT,
    UNIQUE (niche_id, product_id, channel, run_date)
);
CREATE INDEX IF NOT EXISTS ix_content_status ON content_item (niche_id, channel, status, scheduled_for);

-- Medição (sem IP, sem dado pessoal)
CREATE TABLE IF NOT EXISTS click_event (
    id         TEXT PRIMARY KEY,
    ts         TEXT NOT NULL,
    niche_id   TEXT NOT NULL,
    channel    TEXT NOT NULL,
    content_id TEXT,
    country    TEXT
);
CREATE INDEX IF NOT EXISTS ix_click_content ON click_event (content_id);

CREATE TABLE IF NOT EXISTS conversion (
    id            TEXT PRIMARY KEY,              -- '<platform>:<conversion>:<order>:<item>'
    platform      TEXT NOT NULL,
    order_id      TEXT,
    item_id       TEXT,
    niche_id      TEXT,
    channel       TEXT,
    content_id    TEXT,
    purchase_time TEXT NOT NULL,
    status        TEXT,
    amount        REAL,
    commission    REAL,
    raw           TEXT,
    updated_at    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_conversion_content ON conversion (content_id);

-- Operação
CREATE TABLE IF NOT EXISTS agent_run (
    id            TEXT PRIMARY KEY,
    run_id        TEXT NOT NULL,
    niche_id      TEXT NOT NULL,
    agent         TEXT NOT NULL,
    model         TEXT,
    input_tokens  INTEGER NOT NULL DEFAULT 0,
    output_tokens INTEGER NOT NULL DEFAULT 0,
    cost_usd      REAL NOT NULL DEFAULT 0,
    latency_ms    INTEGER NOT NULL DEFAULT 0,
    status        TEXT NOT NULL,
    created_at    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_agent_run_day ON agent_run (created_at);

CREATE TABLE IF NOT EXISTS pipeline_run (
    run_id      TEXT NOT NULL,
    step        TEXT NOT NULL,
    niche_id    TEXT NOT NULL,                   -- '*' para passos globais
    run_date    TEXT NOT NULL,
    status      TEXT NOT NULL,                   -- running | ok | failed
    detail      TEXT,
    started_at  TEXT NOT NULL,
    finished_at TEXT,
    PRIMARY KEY (run_id, step, niche_id)
);

CREATE TABLE IF NOT EXISTS audit_log (
    id     TEXT PRIMARY KEY,
    ts     TEXT NOT NULL,
    actor  TEXT NOT NULL,
    action TEXT NOT NULL,
    target TEXT,
    detail TEXT
);

CREATE TABLE IF NOT EXISTS channel_state (
    niche_id             TEXT NOT NULL,
    channel              TEXT NOT NULL,
    paused               INTEGER NOT NULL DEFAULT 0,
    consecutive_failures INTEGER NOT NULL DEFAULT 0,
    updated_at           TEXT NOT NULL,
    PRIMARY KEY (niche_id, channel)
);

CREATE TABLE IF NOT EXISTS kv_state (
    key        TEXT PRIMARY KEY,
    value      TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
