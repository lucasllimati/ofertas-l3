"""Prontidão para produção: trava de migration, modo ensaio, heartbeat, doctor, push_secrets e bootstrap_db."""

from __future__ import annotations

import json
import os
import shutil
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from scripts import bootstrap_db, push_secrets
from src.common.db import Database, PendingMigrationsError
from src.common.telegram import FakeTelegram, RehearsalTelegram
from src.common.util import slot_to_utc
from src.doctor import Doctor, summary
from src.publishers.telegram import publish_niche
from src.reports.daily import build_report
from src.run import build_context, build_steps, parse_args, ping_heartbeat, run_steps
from tests.conftest import ADMIN_ID, DAY1, make_env
from tests.test_approval_publish import approve_all, prepare

TZ = "America/Sao_Paulo"
ROOT = Path(__file__).resolve().parents[1]
TOKEN = "123456789:" + "A" * 35


# ----------------------------------------------------------- trava de migration
def test_pending_migrations_lists_without_applying(tmp_path):
    db = Database(f"sqlite:///{(tmp_path / 'x.db').as_posix()}")
    pending = db.pending_migrations()
    assert pending and all(not p.endswith(".pg.sql") for p in pending)
    assert db.migrate() == pending
    assert db.pending_migrations() == []


def test_migrate_without_ddl_explains_what_to_do(tmp_path, monkeypatch):
    db = Database(f"sqlite:///{(tmp_path / 'x.db').as_posix()}")
    monkeypatch.setattr(db, "can_change_schema", lambda: False)
    with pytest.raises(PendingMigrationsError, match=r"SETUP\.md §5\.3"):
        db.migrate()


def test_pipeline_role_on_postgres_gets_clear_error(db, tmp_path):
    if db.dialect != "postgres":
        pytest.skip("só em Postgres")
    (tmp_path / "9999_nova.sql").write_text("CREATE TABLE garimpo.nova (a int);", encoding="utf-8")
    db.execute("SET ROLE app_writer")
    try:
        assert not db.can_change_schema()
        with pytest.raises(PendingMigrationsError) as err:
            db.migrate(tmp_path)
        assert err.value.pending == ["9999_nova.sql"]
    finally:
        db.execute("RESET ROLE")


def test_run_stops_and_alerts_on_pending_migration(make_ctx, monkeypatch):
    ctx = make_ctx()
    monkeypatch.setattr(ctx.db, "pending_migrations", lambda *a: ["0099_x.sql"])
    monkeypatch.setattr(ctx.db, "can_change_schema", lambda: False)
    failures = run_steps(ctx, ["migrate", "sync-niches"], build_steps(parse_args(["--steps", "daily"])), None)
    assert len(failures) == 1 and "migration pendente: 0099_x.sql" in failures[0]


# ------------------------------------------------------------------ modo ensaio
def test_rehearsal_never_posts_to_channels(make_ctx, db):
    fake = FakeTelegram(admin_user_id=ADMIN_ID)
    ctx = make_ctx(telegram=RehearsalTelegram(fake, "admin-chat"), rehearsal=True)
    prepare(ctx)
    approve_all(ctx, db)
    night = make_ctx(now=slot_to_utc(DAY1, "23:00", TZ), telegram=ctx.telegram, rehearsal=True)
    result = publish_niche(night, night.config.niche("casa"))
    assert result["published"] > 0
    assert all(m["chat_id"] == "admin-chat" for m in fake.sent if m["kind"] != "edit")
    notices = [m for m in fake.sent if "Ensaio" in (m.get("text") or "")]
    assert len(notices) == result["published"] and "@chan_casa" in notices[0]["text"]
    assert "Modo ensaio ativo" in build_report(night)


def test_rehearsal_from_env_wraps_telegram(monkeypatch, config, tmp_path):
    env = make_env(config) | {"DATABASE_URL": f"sqlite:///{(tmp_path / 'r.db').as_posix()}"}
    env |= {"SHOPEE_APP_ID": "1", "SHOPEE_APP_SECRET": "s", "GARIMPO_REHEARSAL": "1"}
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    ctx = build_context(parse_args(["--steps", "publish"]), config)
    assert ctx.rehearsal and isinstance(ctx.telegram, RehearsalTelegram)
    monkeypatch.setenv("GARIMPO_REHEARSAL", "")
    assert not build_context(parse_args(["--steps", "publish"]), config).rehearsal


# -------------------------------------------------------------------- heartbeat
def test_heartbeat_pings_success_and_failure():
    seen = []
    http = httpx.Client(transport=httpx.MockTransport(lambda r: seen.append(str(r.url)) or httpx.Response(200)))
    url = "https://hc-ping.com/1b2c3d4e-0000-4000-8000-123456789abc"
    assert ping_heartbeat({"HEARTBEAT_URL": url}, ok=True, http=http)
    assert ping_heartbeat({"HEARTBEAT_URL": url}, ok=False, http=http)
    assert seen == [url, url + "/fail"]
    assert not ping_heartbeat({}, ok=True, http=http)
    assert not ping_heartbeat({"HEARTBEAT_URL": "http://inseguro.com/x"}, ok=True, http=http)

    def down(request):
        raise httpx.ConnectError("fora")

    assert not ping_heartbeat({"HEARTBEAT_URL": url}, ok=True, http=httpx.Client(transport=httpx.MockTransport(down)))


# ----------------------------------------------------------------------- doctor
def full_env(config, db_url):
    env = make_env(config) | {
        "DATABASE_URL": db_url,
        "TELEGRAM_BOT_TOKEN": TOKEN,
        "TELEGRAM_ADMIN_USER_IDS": str(ADMIN_ID),
        "APPROVAL_HMAC_SECRET": "h" * 40,
        "SHOPEE_APP_ID": "123",
        "SHOPEE_APP_SECRET": "shopee-secret-value",
        "ANTHROPIC_API_KEY": "sk-ant-test-key-value",
        "BACKUP_PASSPHRASE": "p" * 40,
        "HEARTBEAT_URL": "https://hc-ping.com/abc-123",
        "CF_API_TOKEN": "cf-token-value",
        "CF_ACCOUNT_ID": "acc",
        "CF_KV_NAMESPACE_ID": "kv",
        "CF_D1_DATABASE_ID": "d1",
        "REDIRECT_BASE_URL": "https://go.example.com",
    }
    return env


def api_ok(request):
    if "anthropic" in request.url.host:
        return httpx.Response(200, json={"data": []})
    if "cloudflare" in request.url.host:
        return httpx.Response(200, json={"result": {"status": "active"}})
    return httpx.Response(200, text="ok")


def gh_runner(names, variables=None):
    def run(cmd, **kw):
        if cmd[:3] == ["gh", "secret", "list"]:
            return SimpleNamespace(returncode=0, stdout=json.dumps([{"name": n} for n in names]))
        return SimpleNamespace(returncode=0, stdout=json.dumps(variables or []))

    return run


def make_doctor(config, env, telegram=None, names=None, **kw):
    shopee = SimpleNamespace(search=lambda keyword, limit: [object()])
    return Doctor(
        env,
        config,
        telegram=telegram or FakeTelegram(admin_user_id=ADMIN_ID),
        shopee_factory=lambda a, s: shopee,
        http=httpx.Client(transport=httpx.MockTransport(api_ok)),
        runner=gh_runner(names if names is not None else list(env)),
        which=lambda name: "/usr/bin/gh",
        root=kw.pop("root", ROOT),
        **kw,
    )


def test_doctor_all_green_never_shows_values(config, tmp_path):
    url = f"sqlite:///{(tmp_path / 'd.db').as_posix()}"
    Database(url).migrate()
    env = full_env(config, url)
    checks = make_doctor(config, env).run()
    failed = [c.line() for c in checks if c.status == "fail"]
    assert failed == []
    text = "\n".join(c.line() for c in checks) + summary(checks)
    for name in ("TELEGRAM_BOT_TOKEN", "SHOPEE_APP_SECRET", "ANTHROPIC_API_KEY", "CF_API_TOKEN", "BACKUP_PASSPHRASE"):
        assert env[name] not in text
    assert "0 falhas" in summary(checks)
    agenda = next(c for c in checks if c.name == "agendamento")
    assert agenda.status == "warn" and "GARIMPO_ENABLED" in agenda.detail  # produção ainda desligada


def test_doctor_reports_schedule_switch(config):
    env = {"TELEGRAM_BOT_TOKEN": TOKEN}
    on = [{"name": "GARIMPO_ENABLED", "value": "1"}, {"name": "GARIMPO_REHEARSAL", "value": "1"}]
    doctor = Doctor(env, config, runner=gh_runner([], on), which=lambda n: "gh")
    by_name = {c.name: c for c in doctor.run({"github"})}
    assert by_name["agendamento"].status == "ok" and by_name["modo ensaio"].status == "warn"


def test_doctor_points_to_the_setup_section(config, tmp_path):
    url = f"sqlite:///{(tmp_path / 'd.db').as_posix()}"  # banco sem migrations
    env = full_env(config, url)
    del env["TELEGRAM_ADMIN_CHAT_ID"]
    env["APPROVAL_HMAC_SECRET"] = "curto"
    tg = FakeTelegram(admin_user_id=ADMIN_ID)
    tg.not_admin_chats.add("@chan_pet")
    checks = make_doctor(config, env, telegram=tg, names=["DATABASE_URL"]).run()
    by_name = {(c.group, c.name): c for c in checks}
    assert by_name[("telegram", "canal pet")].status == "fail" and by_name[("telegram", "canal pet")].section == "4.3"
    assert by_name[("telegram", "canal casa")].status == "ok"
    assert by_name[("telegram", "chat de admin")].section == "4.2"
    assert by_name[("segredos", "APPROVAL_HMAC_SECRET")].status == "fail"
    assert by_name[("banco", "migrations")].status == "warn"  # SQLite pode migrar; avisa
    github = by_name[("github", "secrets")]
    assert github.status == "fail" and "TELEGRAM_BOT_TOKEN" in github.detail
    assert "Comece por" in summary(checks)


def test_doctor_offline_and_invalid_token(config):
    env = {"TELEGRAM_BOT_TOKEN": "nao-e-token", "DATABASE_URL": "postgresql://u:SENHA@h/db"}
    checks = Doctor(env, config, offline=True).run({"telegram", "banco", "claude", "github"})
    statuses = {(c.group, c.status) for c in checks}
    assert ("telegram", "fail") in statuses and ("banco", "fail") in statuses
    assert ("claude", "skip") in statuses and ("github", "skip") in statuses


def test_doctor_detects_owner_url_on_postgres(db, config):
    if db.dialect != "postgres":
        pytest.skip("só em Postgres")
    env = {"DATABASE_URL": os.environ["TEST_DATABASE_URL"]}
    checks = Doctor(env, config, db_factory=lambda url: db_proxy(db)).run({"banco"})
    by_name = {c.name: c for c in checks}
    assert by_name["usuário"].status == "warn" and "DONO" in by_name["usuário"].detail
    assert by_name["migrations"].status == "ok"


def db_proxy(db):
    return SimpleNamespace(
        dialect=db.dialect,
        can_change_schema=db.can_change_schema,
        pending_migrations=db.pending_migrations,
        scalar=db.scalar,
        close=lambda: None,  # o fixture fecha
    )


# ----------------------------------------------------------------- push_secrets
def test_push_plan_refuses_owner_url_and_examples(config):
    env = {
        "DATABASE_URL": "postgresql://postgres.abc:x@aws-0-sa-east-1.pooler.supabase.com:5432/postgres",
        "TELEGRAM_BOT_TOKEN": TOKEN,
        "APPROVAL_HMAC_SECRET": "curto",
        "TG_CASA_CHAT_ID": "@garimpocasa",
        "SHOPEE_APP_SECRET": "SENHA",
        "DEMO_DATABASE_URL": "sqlite:///x",
        "GARIMPO_REHEARSAL": "1",
    }
    send, variables, refused, ignored = push_secrets.plan(env, None)
    assert send == ["TELEGRAM_BOT_TOKEN", "TG_CASA_CHAT_ID"]
    assert variables == ["GARIMPO_REHEARSAL"] and ignored == ["DEMO_DATABASE_URL"]
    assert set(refused) == {"DATABASE_URL", "APPROVAL_HMAC_SECRET", "SHOPEE_APP_SECRET"}
    assert "DONO" in refused["DATABASE_URL"]
    pipeline = "postgresql://garimpo_pipeline.abc:x@aws-0-sa-east-1.pooler.supabase.com:5432/postgres"
    assert push_secrets.problem("DATABASE_URL", pipeline) is None


def test_push_sends_values_by_stdin_and_dates_inventory(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text(f"TELEGRAM_BOT_TOKEN={TOKEN}\nTG_PET_CHAT_ID=@garimpopet\nLOG_LEVEL=DEBUG\n", encoding="utf-8")
    inventory = tmp_path / "secrets.md"
    shutil.copy(ROOT / "docs" / "secrets.md", inventory)
    calls = []

    def runner(cmd, **kw):
        calls.append((cmd, kw.get("input")))
        return SimpleNamespace(returncode=0, stdout="")

    args = ["--env-file", str(env_file), "--inventory", str(inventory), "--repo", "dono/repo"]
    assert push_secrets.main([*args, "--dry-run"], runner=runner) == 0 and calls == []
    assert push_secrets.main(args, runner=runner, ask=lambda q: "n") == 1 and calls == []
    assert push_secrets.main([*args, "--yes"], runner=runner) == 0
    assert [c[0][3] for c in calls] == ["TELEGRAM_BOT_TOKEN", "TG_PET_CHAT_ID"]
    assert all(c[0][:3] == ["gh", "secret", "set"] for c in calls)
    assert all(TOKEN not in " ".join(cmd) for cmd, _ in calls) and calls[0][1] == TOKEN
    text = inventory.read_text(encoding="utf-8")
    today = date.today().isoformat()
    token_row = next(line for line in text.splitlines() if line.startswith("| `TELEGRAM_BOT_TOKEN`"))
    pet_row = next(line for line in text.splitlines() if line.startswith("| `TG_PET_CHAT_ID`"))
    assert today in token_row and token_row.count("20") >= 2  # criado + expira (rotação de 90 dias)
    assert today in pet_row
    import scripts.check_secrets_inventory as inv

    assert len(inv.inventory()) >= 18  # o formato da tabela continua legível


# ----------------------------------------------------------------- bootstrap_db
def test_pipeline_url_keeps_pooler_suffix_and_quotes_password():
    owner = "postgresql://postgres.abcxyz:dono@aws-0-sa-east-1.pooler.supabase.com:5432/postgres"
    url = bootstrap_db.pipeline_url(owner, "garimpo_pipeline", "a/b@c")
    assert url == "postgresql://garimpo_pipeline.abcxyz:a%2Fb%40c@aws-0-sa-east-1.pooler.supabase.com:5432/postgres"
    assert (
        bootstrap_db.pipeline_url("postgresql://postgres@localhost/db", "r_x", "p") == "postgresql://r_x:p@localhost/db"
    )


def test_bootstrap_creates_least_privilege_user(db, tmp_path):
    if db.dialect != "postgres":
        pytest.skip("só em Postgres")
    owner = os.environ["TEST_DATABASE_URL"]
    role = "garimpo_pipeline_t"
    env_file = tmp_path / ".env"
    env_file.write_text("TELEGRAM_BOT_TOKEN=x\nDATABASE_URL=antiga\n", encoding="utf-8")
    try:
        assert bootstrap_db.bootstrap(owner, env_file, role, verify_attempts=1) == "created"
        lines = env_file.read_text(encoding="utf-8").splitlines()
        assert lines[0] == "TELEGRAM_BOT_TOKEN=x" and lines[1].startswith(f"DATABASE_URL=postgresql://{role}:")
        assert bootstrap_db.bootstrap(owner, env_file, role, verify_attempts=1) == "exists"
        assert bootstrap_db.bootstrap(owner, env_file, role, rotate=True, verify_attempts=1) == "rotated"
        assert env_file.read_text(encoding="utf-8").splitlines()[1] != lines[1]
    finally:
        db.execute(f"DROP ROLE IF EXISTS {role}")


def test_bootstrap_refuses_non_postgres_url(tmp_path):
    with pytest.raises(SystemExit):
        bootstrap_db.bootstrap("sqlite:///x.db", tmp_path / ".env")
