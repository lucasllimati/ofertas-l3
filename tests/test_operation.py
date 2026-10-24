"""Correções da revisão geral do projeto: healthcheck dos canais, alertas, CSV de vendas e cliente HTTP."""

import httpx
import pytest

from src.common.telegram import TelegramClient
from src.common.util import parse_money
from src.run import step_healthcheck
from src.tracking.sync import import_conversions_csv, parse_purchase_time


# ------------------------------------------------------------ healthcheck
def test_healthcheck_passes_when_bot_can_post_everywhere(make_ctx):
    ctx = make_ctx()
    result = step_healthcheck(ctx, notify=True)
    assert result["active"] == ["casa", "pet"]
    assert "canais ok: casa, pet" in ctx.telegram.sent[-1]["text"]


def test_healthcheck_fails_when_bot_is_not_admin_or_channel_missing(make_ctx):
    ctx = make_ctx()
    ctx.telegram.not_admin_chats.add("@chan_casa")
    ctx.telegram.fail_chats.add("@chan_pet")
    with pytest.raises(RuntimeError) as err:
        step_healthcheck(ctx, notify=True)
    message = str(err.value)
    assert "casa: o bot não é admin" in message and "pet: canal @chan_pet inacessível" in message
    assert not ctx.telegram.sent  # não manda "ok" quando há problema


# --------------------------------------------------------- alerta de falhas
def test_failure_alert_escapes_html(monkeypatch, tmp_path, capsys):
    """Erro com '<' não pode quebrar o alerta (o Telegram recusaria a mensagem inteira)."""
    from src import run

    sent = []
    monkeypatch.setenv("DEMO_DATABASE_URL", f"sqlite:///{(tmp_path / 'd.db').as_posix()}")
    monkeypatch.setattr(run, "ROOT", tmp_path)
    monkeypatch.setattr(
        "src.pipeline.ingest.ingest", lambda ctx, niche: (_ for _ in ()).throw(KeyError("<class 'x'> & y"))
    )
    monkeypatch.setattr("src.publishers.telegram.alert", lambda ctx, text: sent.append(text))
    assert run.main(["--demo", "--steps", "ingest", "--niche", "casa"]) == 1
    assert sent and "<class" not in sent[0] and "&lt;class" in sent[0] and "&amp;" in sent[0]


# ------------------------------------------------------ CSV de vendas (ML/Amazon)
def test_parse_money_brazilian_formats():
    assert parse_money("39,90") == 39.90
    assert parse_money("R$ 1.234,50") == 1234.50
    assert parse_money("1234.5") == 1234.5
    assert parse_money("") == 0.0
    with pytest.raises(ValueError):
        parse_money("trinta")


def test_parse_purchase_time_accepts_panel_formats():
    assert parse_purchase_time("20/10/2026 15:00", "America/Sao_Paulo") == "2026-10-20T18:00:00+00:00"
    assert parse_purchase_time("20/10/2026", "America/Sao_Paulo") == "2026-10-20T03:00:00+00:00"
    assert parse_purchase_time("2026-10-20T15:00:00+00:00", "America/Sao_Paulo") == "2026-10-20T15:00:00+00:00"
    with pytest.raises(ValueError):
        parse_purchase_time("ontem", "America/Sao_Paulo")


def test_csv_import_with_comma_decimals_and_br_dates(make_ctx, db, tmp_path):
    ctx = make_ctx()
    path = tmp_path / "ml.csv"
    path.write_text(
        "platform,order_id,item_id,purchase_time,status,amount,commission,sub_id\n"
        'mercadolivre,1,MLB1,20/10/2026 15:00,paid,"R$ 39,90","3,19",casa-tg\n',
        encoding="utf-8",
    )
    assert import_conversions_csv(ctx, path)["conversions"] == 1
    row = db.fetchone("SELECT amount, commission, purchase_time, niche_id FROM conversion")
    assert row == {
        "amount": 39.90,
        "commission": 3.19,
        "purchase_time": "2026-10-20T18:00:00+00:00",
        "niche_id": "casa",
    }


def test_csv_import_rejects_whole_file_on_bad_line(make_ctx, db, tmp_path):
    ctx = make_ctx()
    path = tmp_path / "ruim.csv"
    path.write_text(
        "platform,order_id,item_id,purchase_time,status,amount,commission,sub_id\n"
        "mercadolivre,1,MLB1,20/10/2026,paid,10,1,casa-tg\n"
        "mercadolivre,2,MLB2,20/10/2026,paid,dez,1,casa-tg\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="linha 3"):
        import_conversions_csv(ctx, path)
    assert db.scalar("SELECT count(*) FROM conversion") == 0


# ------------------------------------------------------------- publicador
def test_render_failure_before_send_keeps_post_in_queue(make_ctx, db, monkeypatch):
    from src.common.util import slot_to_utc
    from src.publishers.telegram import publish_niche
    from tests.conftest import DAY1
    from tests.test_approval_publish import approve_all, prepare

    ctx = make_ctx()
    prepare(ctx)
    approve_all(ctx, db)
    db.execute("UPDATE content_item SET media_file_id = NULL")  # força gerar a arte na publicação
    monkeypatch.setattr("src.publishers.telegram.render_for", lambda *a: (_ for _ in ()).throw(OSError("disco")))
    night = make_ctx(now=slot_to_utc(DAY1, "23:00", "America/Sao_Paulo"), telegram=ctx.telegram)
    assert publish_niche(night, night.config.niche("casa"))["published"] == 0
    statuses = {r["status"] for r in db.fetchall("SELECT status FROM content_item WHERE niche_id = 'casa'")}
    assert statuses == {"approved"}  # nada em publish_unknown: com certeza não foi enviado


# ------------------------------------------------------- cliente do Telegram
def test_telegram_non_json_response_is_ambiguous_not_crash():
    client = TelegramClient(
        "123:abc", http=httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(502, text="<html>")))
    )
    with pytest.raises(ConnectionError, match="HTTP 502"):
        client.send_message("1", "oi")
