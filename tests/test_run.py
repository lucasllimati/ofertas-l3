import json
import sqlite3

import pytest

from src.run import ALIASES, build_steps, expand_steps, main, parse_args


def test_expand_steps_aliases():
    registry = build_steps(parse_args(["--steps", "daily"]))
    assert expand_steps("publish", registry) == ["migrate", "approvals", "publish"]
    full = expand_steps("all", registry)
    assert full.count("approvals") == 3  # roda de novo depois das prévias
    assert full[0] == "migrate"
    with pytest.raises(SystemExit):
        expand_steps("nao-existe", registry)
    assert set(ALIASES) == {"daily", "publish", "report", "all"}


def test_missing_secrets_fail_fast_with_names_only(monkeypatch, capsys):
    for name in ("DATABASE_URL", "TELEGRAM_BOT_TOKEN", "SHOPEE_APP_SECRET"):
        monkeypatch.delenv(name, raising=False)
    assert main(["--steps", "daily"]) == 2
    err = capsys.readouterr().err
    assert "TELEGRAM_BOT_TOKEN" in err and "DATABASE_URL" in err


def test_demo_end_to_end_two_days(monkeypatch, tmp_path):
    db_path = tmp_path / "demo.db"
    monkeypatch.setenv("DEMO_DATABASE_URL", f"sqlite:///{db_path.as_posix()}")
    monkeypatch.setenv("DATABASE_URL", "postgresql://producao:nao-usar@example.invalid/db")  # a demo deve ignorar
    monkeypatch.setattr("src.run.ROOT", tmp_path)
    assert main(["--demo", "--steps", "all", "--run-date", "2026-10-20"]) == 0
    assert main(["--demo", "--steps", "all", "--run-date", "2026-10-21"]) == 0
    assert main(["--demo", "--steps", "all", "--run-date", "2026-10-21"]) == 0  # reexecução

    conn = sqlite3.connect(db_path)
    statuses = dict(conn.execute("SELECT status, count(*) FROM content_item GROUP BY status").fetchall())
    assert statuses == {"published": 20}  # 2 nichos x 5 posts x 2 dias, sem duplicar
    failed = conn.execute("SELECT count(*) FROM pipeline_run WHERE status = 'failed'").fetchone()[0]
    assert failed == 0
    posts = [
        json.loads(line)
        for line in (tmp_path / "out" / "demo" / "telegram_outbox.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    channel_posts = [p for p in posts if p["chat_id"].startswith("@demo_")]
    assert len(channel_posts) == 20
