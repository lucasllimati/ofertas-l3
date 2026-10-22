PRAGMA foreign_keys = ON;

INSERT OR IGNORE INTO stores (id, name, domain)
VALUES (1, 'Amazon Brasil', 'amazon.com.br');

INSERT OR IGNORE INTO products (id, name, niche, platform, release_date)
VALUES (
    1,
    'Grand Theft Auto VI',
    'PS5 & Games / Eletrônicos',
    'PlayStation 5',
    '2026-11-19'
);

INSERT OR IGNORE INTO offers (
    id,
    product_id,
    store_id,
    original_price,
    promotional_price,
    discount_threshold_pct,
    original_price_basis,
    source_url,
    captured_at,
    market_value_assessment,
    assessment_basis,
    poc_approved,
    notes
)
VALUES (
    1,
    1,
    1,
    449.90,
    418.40,
    15,
    'Estimado a partir dos 7% OFF exibidos na captura; não confirmado como preço anterior pela loja.',
    'https://www.amazon.com.br/gp/product/B0H6KT2RWH?smid=A1ZZFT5FULY4LN&psc=1&btn_type=ss&btn_ref=srctok-3a5bec9b62828733',
    '2026-10-10T20:43:00-03:00',
    'BELOW_MARKET_VALUE',
    'Assunção solicitada pelo usuário para a POC; comparação de mercado não verificada.',
    1,
    'Pré-venda. A página exibia 7% OFF à vista via Pix ou NuPay. Não presumir acúmulo de benefícios.'
);

INSERT OR IGNORE INTO offer_benefits (
    id, offer_id, benefit_type, code, description, conditions, stacking_status
)
VALUES
(
    1,
    1,
    'COUPON',
    'COMANOAP',
    'R$ 20 de desconto conforme captura da página.',
    'A captura informa primeira compra na Amazon pelo aplicativo; confirmar elegibilidade no checkout.',
    'UNKNOWN'
),
(
    2,
    1,
    'PAYMENT_DISCOUNT',
    'PRIMEGAME5',
    'Desconto adicional de 5% conforme captura da página.',
    'A captura indica Prime e pagamento via Pix ou NuPay; confirmar elegibilidade e aplicação no checkout.',
    'UNKNOWN'
);
