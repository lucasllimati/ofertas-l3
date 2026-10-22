from src.sources.manual import parse_manual_csv

HEADER = (
    "platform,item_id,title,price,price_original,image_url,affiliate_url,"
    "rating,reviews,sales_total,commission_rate,category"
)


def test_parses_valid_rows_and_skips_comments():
    text = "\n".join(
        [
            HEADER,
            "# comentário",
            'mercadolivre,MLB1,Organizador,"39,90",59.90,https://img/x.jpg,https://meli.la/abc,4.8,1200,,0.08,casa',
            "amazon,,Luminária,R$ 25.00,,,https://amzn.to/xyz,,,,,",
        ]
    )
    offers, errors = parse_manual_csv(text)
    assert errors == []
    assert offers[0].price == 39.90 and offers[0].reviews == 1200
    assert offers[1].item_id  # gerado a partir do link
    assert offers[1].affiliate_url == "https://amzn.to/xyz"


def test_rejects_links_outside_allowlist_and_missing_fields():
    text = "\n".join(
        [
            HEADER,
            "shopee,1,Golpe,10,,,https://phishing.example.com/shopee.com.br,,,,,",
            "shopee,2,Http,10,,,http://shopee.com.br/x,,,,,",
            "shopee,3,,10,,,https://shopee.com.br/x,,,,,",
            "ebay,4,X,10,,,https://shopee.com.br/x,,,,,",
        ]
    )
    offers, errors = parse_manual_csv(text)
    assert offers == []
    assert len(errors) == 4
