from __future__ import annotations

import os
from datetime import date, datetime

import pytest

from src.common.db import Database
from src.common.telegram import FakeTelegram
from src.config.loader import load_config
from src.content.copy import TemplateCopywriter
from src.context import AppContext
from src.sources.fake import FakeShopee

ADMIN_ID = 777

# Suíte de segurança padronizada (`pytest -m security`), rodada pelo security.yml em todo PR, push e semanalmente.
# Arquivos inteiros + testes de outros arquivos cujo nome indica uma garantia de segurança ou de regra de anúncio.
SECURITY_FILES = {"test_security.py", "test_hardening.py", "test_logging.py", "test_manual.py", "test_production.py"}
SECURITY_KEYWORDS = (
    "signature",
    "unauthorized",
    "forged",
    "escape",
    "compliance",
    "allowlist",
    "redact",
    "secret",
    "circuit_breaker",
    "ambiguous",
    "expire",
    "discount",
    "pause",
)


def pytest_collection_modifyitems(items):
    for item in items:
        if item.path.name in SECURITY_FILES or any(k in item.name for k in SECURITY_KEYWORDS):
            item.add_marker(pytest.mark.security)


DAY1 = date(2026, 10, 20)


def make_env(config) -> dict[str, str]:
    env = {
        "DATABASE_URL": "sqlite://:memory:",
        "TELEGRAM_BOT_TOKEN": "123456:TESTTOKENTESTTOKENTESTTOKENTESTTOKEN",
        "TELEGRAM_ADMIN_CHAT_ID": "admin-chat",
        "TELEGRAM_ADMIN_USER_IDS": str(ADMIN_ID),
        "APPROVAL_HMAC_SECRET": "test-secret",
    }
    for n in config.niches:
        if n.channels.telegram:
            env[f"{n.channels.telegram.channel_ref}_CHAT_ID"] = f"@chan_{n.id}"
    return env


@pytest.fixture
def config():
    return load_config()


@pytest.fixture
def db():
    url = os.environ.get("TEST_DATABASE_URL", "sqlite://:memory:")
    database = Database(url)
    if database.dialect == "postgres":
        database.executescript("DROP SCHEMA IF EXISTS garimpo CASCADE")
    database.migrate()
    yield database
    database.close()


@pytest.fixture
def make_ctx(config, db, tmp_path):
    def _make(run_date: date = DAY1, now: datetime | None = None, **overrides) -> AppContext:
        from src.common.util import slot_to_utc

        fake = overrides.pop("shopee", None) or FakeShopee(run_date)
        ctx = AppContext(
            config=overrides.pop("config", config),
            db=db,
            run_date=run_date,
            now=now or slot_to_utc(run_date, "06:00", "America/Sao_Paulo"),
            run_id="test",
            telegram=overrides.pop("telegram", None) or FakeTelegram(admin_user_id=ADMIN_ID),
            shopee=fake,
            linker=fake,
            conversions_source=fake,
            copywriter=overrides.pop("copywriter", None) or TemplateCopywriter(),
            image_fetcher=None,
            env=make_env(config),
            out_dir=tmp_path,
        )
        for key, value in overrides.items():
            setattr(ctx, key, value)
        return ctx

    return _make
