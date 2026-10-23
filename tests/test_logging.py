import json
import logging

from src.common.logging import JsonFormatter, redact


def test_redacts_known_patterns():
    text = (
        "bot 123456789:AAHdqTcvCH1vGWJxfSeofSAs0K5PALDsaw "
        "key sk-ant-api03-abcdefghijklmnop "
        "db postgresql://user:supersecret@host:5432/db "
        "Signature=0123456789abcdef0123456789abcdef"
    )
    out = redact(text)
    assert "AAHdqTcv" not in out
    assert "sk-ant-api03" not in out
    assert "supersecret" not in out
    assert "postgresql://user:***@host" in out
    assert "0123456789abcdef0123" not in out


def test_redacts_secret_env_values(monkeypatch):
    monkeypatch.setenv("SHOPEE_APP_SECRET", "meu-segredo-shopee")
    assert "meu-segredo-shopee" not in redact("erro com meu-segredo-shopee no meio")


def test_formatter_emits_json_with_context(monkeypatch):
    monkeypatch.setenv("CF_API_TOKEN", "cf-token-value-123")
    record = logging.LogRecord("x", logging.INFO, __file__, 1, "token cf-token-value-123", None, None)
    record.data = {"k": "v"}
    payload = json.loads(JsonFormatter().format(record))
    assert payload["msg"] == "token ***"
    assert payload["data"] == {"k": "v"}
    assert {"run_id", "correlation_id", "niche_id"} <= payload.keys()
