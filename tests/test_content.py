import io
import json
from datetime import date
from types import SimpleNamespace

from PIL import Image

from src.content.caption import build_caption, compliance_issues, discount_pct
from src.content.copy import CopyResult, LlmCopywriter
from src.content.render import HEIGHT, WIDTH, render_post

PRODUCT = {
    "id": "shopee:1",
    "title": "Organizador de Gaveta 6 Divisórias",
    "price": 39.9,
    "price_original": 59.9,
    "rating": 4.8,
    "reviews": None,
    "category": "casa",
    "shop_name": "Loja",
    "sales_total": 100,
}
COPY = CopyResult(headline="Gaveta arrumada em 2 minutos", bullets=["Seis divisórias", "Encaixa fácil"], hashtags=[])


# ---------------------------------------------------------------------- legenda
def test_caption_has_all_compliance_items():
    caption = build_caption(COPY, 39.9, 59.9, "https://s.shopee.com.br/x", date(2026, 10, 20), ["#casa"])
    assert "R$ 39,90" in caption and "<s>R$ 59,90</s>" in caption and "(-33%)" in caption
    assert "20/10/2026" in caption and "#publi" in caption
    assert compliance_issues(caption, link_allowed=True) == []


def test_caption_escapes_html_from_external_data():
    copy = CopyResult(headline='<script>x</script> & "aspas"', bullets=["a & b"], hashtags=[])
    caption = build_caption(copy, 10, None, "https://s.shopee.com.br/x?a=1&b=2", date(2026, 10, 20), [])
    assert "<script>" not in caption and "script" in caption  # sinais < > removidos na limpeza
    assert "&amp; &quot;aspas&quot;" in caption  # e o resto escapado para o HTML do Telegram
    assert "a=1&amp;b=2" in caption


def test_compliance_catches_problems():
    assert "primeira linha" in compliance_issues("oi 20/10/2026 sujeito a alteração", True)[0]
    # #publi escondido no fim não vale
    hidden = "oferta\n20/10/2026 sujeito a alteração #publi"
    assert any("primeira linha" in i for i in compliance_issues(hidden, True))
    assert any("data" in i for i in compliance_issues("#publi", True))
    assert any("link" in i for i in compliance_issues("#publi 20/10/2026 sujeito a alteração", False))
    assert any("proibido" in i for i in compliance_issues("#publi 20/10/2026 sujeito a alteração cura gripe", True))


def test_discount_ignores_fake_or_tiny_discounts():
    assert discount_pct(100, 90) is None
    assert discount_pct(100, 102) is None
    assert discount_pct(50, 100) == 50


# -------------------------------------------------------------------------- LLM
class FakeMessages:
    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        reply = self.replies.pop(0)
        stop = reply.pop("_stop", "end_turn") if isinstance(reply, dict) else "end_turn"
        return SimpleNamespace(
            stop_reason=stop,
            content=[SimpleNamespace(type="text", text=json.dumps(reply))],
            usage=SimpleNamespace(
                input_tokens=500, output_tokens=200, cache_read_input_tokens=0, cache_creation_input_tokens=0
            ),
        )


def llm(db, replies, budget=1.0):
    client = SimpleNamespace(messages=FakeMessages(replies))
    return LlmCopywriter(client, db, "run", budget), client.messages


GOOD = {"headline": "Gaveta arrumada", "bullets": ["Seis divisórias"], "hashtags": ["organizacao"]}


def test_llm_copy_reviewed_and_costed(config, db):
    writer, messages = llm(db, [dict(GOOD), {"approved": True, "issues": []}])
    result, source = writer.write(PRODUCT, config.niche("casa"), {"name": "Garimpo Casa"})
    assert source == "llm" and result.hashtags == ["#organizacao"]
    first = messages.calls[0]
    assert first["model"] == "claude-sonnet-5-5" and messages.calls[1]["model"] == "claude-haiku-5-5"
    assert first["output_config"]["format"]["type"] == "json_schema"
    assert "<dados_produto>" in first["messages"][0]["content"]
    assert "39.9" not in first["messages"][0]["content"]  # preço nunca vai para o modelo
    assert db.scalar("SELECT count(*) FROM agent_run WHERE status = 'ok'") == 2
    assert db.scalar("SELECT sum(cost_usd) FROM agent_run") > 0


def test_llm_review_rejection_retries_then_falls_back(config, db):
    replies = [dict(GOOD), {"approved": False, "issues": ["inventou medida"]}] * 2
    writer, messages = llm(db, replies)
    _, source = writer.write(PRODUCT, config.niche("casa"), {"name": "Garimpo"})
    assert source == "template"
    assert "inventou medida" in messages.calls[2]["messages"][0]["content"]


def test_llm_refusal_or_bad_json_falls_back(config, db):
    writer, _ = llm(db, [{"_stop": "refusal"}])
    assert writer.write(PRODUCT, config.niche("casa"), {})[1] == "template"
    writer, _ = llm(db, [{"headline": "", "bullets": [], "hashtags": []}])
    assert writer.write(PRODUCT, config.niche("casa"), {})[1] == "template"


def test_llm_budget_blocks_calls(config, db):
    writer, messages = llm(db, [], budget=0.0)
    assert writer.write(PRODUCT, config.niche("casa"), {})[1] == "template"
    assert messages.calls == []


# ------------------------------------------------------------------------- arte
def test_render_post_dimensions_with_and_without_photo():
    brand = {"name": "Garimpo Casa", "colors": {"accent": "#D9622B"}}
    png = render_post(PRODUCT, brand, date(2026, 10, 20), None)
    assert Image.open(io.BytesIO(png)).size == (WIDTH, HEIGHT)
    photo = io.BytesIO()
    Image.new("RGB", (300, 500), "red").save(photo, format="JPEG")
    png2 = render_post(PRODUCT, brand, date(2026, 10, 20), photo.getvalue())
    assert png2 != png
    assert render_post(PRODUCT, brand, date(2026, 10, 20), b"lixo")  # imagem inválida não quebra
