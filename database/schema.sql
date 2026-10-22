PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS stores (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    domain TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS products (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    niche TEXT NOT NULL,
    platform TEXT,
    release_date TEXT
);

CREATE TABLE IF NOT EXISTS offers (
    id INTEGER PRIMARY KEY,
    product_id INTEGER NOT NULL REFERENCES products(id),
    store_id INTEGER NOT NULL REFERENCES stores(id),
    original_price REAL,
    promotional_price REAL NOT NULL CHECK (promotional_price >= 0),
    discount_threshold_pct REAL NOT NULL DEFAULT 15 CHECK (discount_threshold_pct >= 0),
    original_price_basis TEXT,
    source_url TEXT NOT NULL,
    captured_at TEXT NOT NULL,
    market_value_assessment TEXT CHECK (
        market_value_assessment IS NULL OR
        market_value_assessment IN ('BELOW_MARKET_VALUE', 'NOT_BELOW_MARKET_VALUE', 'UNVERIFIED')
    ),
    assessment_basis TEXT,
    poc_approved INTEGER NOT NULL DEFAULT 0 CHECK (poc_approved IN (0, 1)),
    notes TEXT
);

CREATE TABLE IF NOT EXISTS offer_benefits (
    id INTEGER PRIMARY KEY,
    offer_id INTEGER NOT NULL REFERENCES offers(id) ON DELETE CASCADE,
    benefit_type TEXT NOT NULL CHECK (benefit_type IN ('COUPON', 'PAYMENT_DISCOUNT', 'SHIPPING')),
    code TEXT,
    description TEXT NOT NULL,
    conditions TEXT,
    stacking_status TEXT NOT NULL DEFAULT 'UNKNOWN'
        CHECK (stacking_status IN ('UNKNOWN', 'STACKABLE', 'NOT_STACKABLE'))
);

CREATE VIEW IF NOT EXISTS offer_validation AS
SELECT
    o.id AS offer_id,
    p.name AS product_name,
    s.name AS store_name,
    o.original_price,
    o.promotional_price,
    CASE
        WHEN o.original_price IS NULL OR o.original_price <= 0 THEN NULL
        ELSE ROUND((o.original_price - o.promotional_price) * 100.0 / o.original_price, 2)
    END AS discount_pct,
    o.discount_threshold_pct,
    CASE
        WHEN o.original_price IS NULL OR o.original_price <= 0 THEN 'PENDING_VALIDATION'
        WHEN (o.original_price - o.promotional_price) * 100.0 / o.original_price
             < o.discount_threshold_pct THEN 'REJECTED_LOW_DISCOUNT'
        ELSE 'APPROVED'
    END AS rule_status,
    o.market_value_assessment,
    o.poc_approved,
    o.assessment_basis,
    o.source_url,
    o.captured_at
FROM offers o
JOIN products p ON p.id = o.product_id
JOIN stores s ON s.id = o.store_id;
