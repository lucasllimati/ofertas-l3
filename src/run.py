"""Ponto de entrada.

    python -m src.run --steps daily                  # coleta, score, conteúdo e prévias
    python -m src.run --steps publish                # aprovações + publicação do horário
    python -m src.run --steps report                 # cliques, conversões e relatório
    python -m src.run --steps healthcheck            # testa config, segredos, banco e bot
    python -m src.run --demo --steps all             # tudo local, sem credenciais

Opções: --run-date AAAA-MM-DD, --niche <id>, --now <ISO UTC>, --import-conversions <csv>.
"""

from __future__ import annotations

import argparse
import html
import os
import sys
import traceback
from collections.abc import Callable
from datetime import date
from pathlib import Path
from typing import Any

from src.common import secrets
from src.common.db import Database
from src.common.envfile import load_env_file
from src.common.logging import get_logger, niche_id_var, redact, run_id_var, setup_logging
from src.common.util import iso, local_today, parse_iso, random_id, slot_to_utc, utcnow
from src.config.loader import load_config
from src.config.models import AppConfig, Niche
from src.context import ROOT, AppContext

log = get_logger("garimpo")

ALIASES = {
    "daily": [
        "migrate",
        "sync-niches",
        "approvals",
        "ingest",
        "purge",
        "transform",
        "score",
        "content",
        "preview",
        "clicks",
    ],
    # preview no fim: posts que o Vigia de preço devolveu para reaprovação saem na mesma execução
    "publish": ["approvals", "publish", "preview"],
    "report": ["approvals", "clicks", "conversions", "report"],
}
ALIASES["all"] = ALIASES["daily"] + ALIASES["publish"] + ALIASES["report"]  # o dia inteiro (demo)
MONITORED = ("active", "candidate")  # candidate: coleta e score, sem conteúdo
ACTIVE = ("active",)


# --------------------------------------------------------------------- passos
def step_migrate(ctx: AppContext) -> dict[str, Any]:
    return {"applied": ctx.db.migrate()}


def step_sync_niches(ctx: AppContext) -> dict[str, Any]:
    for n in ctx.config.niches:
        ctx.db.execute(
            "INSERT INTO niche (id, name, status, config_json, updated_at) VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT (id) DO UPDATE SET name = excluded.name, status = excluded.status, "
            "config_json = excluded.config_json, updated_at = excluded.updated_at",
            (n.id, n.name, n.status, n.model_dump_json(), iso(ctx.now)),
        )
    return {"niches": len(ctx.config.niches)}


def step_healthcheck(ctx: AppContext, notify: bool = False) -> dict[str, Any]:
    """Confere banco, bot e, para cada nicho ativo, se o bot pode publicar no canal.

    Bot fora do canal (ou sem "Publicar mensagens") é o erro de configuração mais comum; sem esta
    checagem ele só apareceria na primeira publicação, pausando o canal pelo circuit breaker.
    """
    ctx.db.scalar("SELECT 1")
    me = ctx.telegram.get_me()
    active = [n for n in ctx.config.niches if n.is_active]
    problems = []
    for niche in active:
        chat_id = ctx.channel_chat_id(niche)
        try:
            member = ctx.telegram.get_chat_member(chat_id, me["id"])
        except Exception as exc:
            problems.append(f"{niche.id}: canal {chat_id or '(sem chat id)'} inacessível ({type(exc).__name__})")
            continue
        can_post = member.get("status") == "creator" or (
            member.get("status") == "administrator" and member.get("can_post_messages", False)
        )
        if not can_post:
            problems.append(f"{niche.id}: o bot não é admin com 'Publicar mensagens' em {chat_id}")
    if problems:
        raise RuntimeError("; ".join(problems))
    if notify:
        ctx.telegram.send_message(
            ctx.admin_chat_id,
            f"✅ Garimpo healthcheck ok · bot @{html.escape(str(me.get('username')))} · "
            f"canais ok: {', '.join(n.id for n in active)}",
        )
    return {"bot": me.get("username"), "active": [n.id for n in active]}


def per_niche(fn: Callable[[AppContext, Niche], dict], statuses: tuple[str, ...]):
    fn.statuses = statuses  # type: ignore[attr-defined]
    return fn


def build_steps(args: argparse.Namespace) -> dict[str, Any]:
    from src.approval import process_updates, send_previews
    from src.backup import export_backup
    from src.pipeline.content import create_content
    from src.pipeline.ingest import ingest, purge_old_snapshots
    from src.pipeline.score import score_niche
    from src.pipeline.transform import transform
    from src.publishers.telegram import publish_niche
    from src.reports.daily import send_monthly_close, send_report
    from src.tracking.sync import import_conversions_csv, sync_clicks, sync_conversions

    def conversions(ctx: AppContext) -> dict:
        result = sync_conversions(ctx)
        if args.import_conversions:
            result["csv"] = import_conversions_csv(ctx, Path(args.import_conversions))["conversions"]
        return result

    return {
        "migrate": step_migrate,
        "sync-niches": step_sync_niches,
        "healthcheck": lambda ctx: step_healthcheck(ctx, args.notify),
        "approvals": process_updates,
        "ingest": per_niche(ingest, MONITORED),
        "purge": purge_old_snapshots,
        "transform": per_niche(transform, MONITORED),
        "score": per_niche(score_niche, MONITORED),
        "content": per_niche(create_content, ACTIVE),
        "preview": per_niche(send_previews, ACTIVE),
        "publish": per_niche(publish_niche, ACTIVE),
        "clicks": sync_clicks,
        "conversions": conversions,
        "report": send_report,
        "backup": export_backup,
        "close": lambda ctx: send_monthly_close(ctx, args.month),
    }


# ------------------------------------------------------------------- execução
def record(ctx: AppContext, step: str, niche_id: str, status: str, detail: str | None = None) -> None:
    ctx.db.execute(
        "INSERT INTO pipeline_run (run_id, step, niche_id, run_date, status, detail, started_at, finished_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT (run_id, step, niche_id) DO UPDATE SET "
        "status = excluded.status, detail = excluded.detail, finished_at = excluded.finished_at",
        (
            ctx.run_id,
            step,
            niche_id,
            ctx.run_date.isoformat(),
            status,
            detail,
            iso(utcnow()),
            iso(utcnow()) if status != "running" else None,
        ),
    )


def run_steps(ctx: AppContext, steps: list[str], registry: dict[str, Any], only_niche: str | None) -> list[str]:
    """Executa os passos em ordem. Falha num nicho não interrompe os outros nem os passos seguintes."""
    failures: list[str] = []
    for step in steps:
        fn = registry[step]
        statuses = getattr(fn, "statuses", None)
        targets = ctx.niches(statuses, only_niche) if statuses else [None]
        for niche in targets:
            nid = niche.id if niche else "*"
            niche_id_var.set(nid)
            can_record = step != "migrate"
            try:
                if can_record:
                    record(ctx, step, nid, "running")
                result = fn(ctx, niche) if niche else fn(ctx)
                log.info(f"{step} ok", extra={"data": result})
                if can_record:
                    record(ctx, step, nid, "ok", str(result)[:500])
            except Exception as exc:
                detail = redact(f"{type(exc).__name__}: {exc}")[:500]
                failures.append(f"{step}[{nid}]: {detail}")
                log.error(
                    f"{step} falhou", extra={"data": {"error": detail, "trace": redact(traceback.format_exc())[-2000:]}}
                )
                if can_record:
                    try:
                        record(ctx, step, nid, "failed", detail)
                    except Exception:
                        log.exception("não foi possível registrar a falha em pipeline_run")
                if step == "migrate":
                    return failures  # sem schema não adianta seguir
        niche_id_var.set("-")
    return failures


def agent_wiring(config: AppConfig, price_source: Any, llm: Any, link_checker: Any) -> dict[str, Any]:
    """Liga os agentes que dependem de configuração ou de clientes externos (docs/agentes.md)."""
    from src.agents.compliance import ComplianceClassifier
    from src.agents.coupons import load_coupons
    from src.agents.price_guard import ShopeePriceChecker
    from src.agents.seasonal import load_calendar

    return {
        "calendar": load_calendar(),
        "price_checker": ShopeePriceChecker(price_source) if price_source is not None else None,
        "link_checker": link_checker,
        "compliance": ComplianceClassifier(llm),
        "coupons": load_coupons(config.defaults.timezone),
    }


def build_context(args: argparse.Namespace, config: AppConfig) -> AppContext:
    from src.content.copy import LlmCopywriter, TemplateCopywriter

    env = dict(os.environ)
    now = parse_iso(args.now) if args.now else utcnow()
    run_date = date.fromisoformat(args.run_date) if args.run_date else local_today(config.defaults.timezone, now)
    run_id = random_id(12)

    if args.demo:
        from src.common.telegram import FakeTelegram

        if not args.now:  # na demo o "agora" é o fim do dia: todos os horários já passaram
            now = slot_to_utc(run_date, "23:30", config.defaults.timezone)
        from src.sources.fake import FakeShopee

        out = ROOT / "out" / "demo"
        # Nunca herda DATABASE_URL: dados falsos da demo não podem cair no banco de produção.
        env["DATABASE_URL"] = env.get("DEMO_DATABASE_URL") or f"sqlite:///{(out / 'garimpo.db').as_posix()}"
        env.update({"TELEGRAM_ADMIN_CHAT_ID": "admin", "TELEGRAM_ADMIN_USER_IDS": "1", "APPROVAL_HMAC_SECRET": "demo"})
        for n in config.niches:
            if n.channels.telegram:
                env[f"{n.channels.telegram.channel_ref}_CHAT_ID"] = f"@demo_{n.id}"
        fake = FakeShopee(run_date)
        db = Database(env["DATABASE_URL"])
        return AppContext(
            **agent_wiring(config, price_source=fake, llm=None, link_checker=None),
            config=config,
            db=db,
            run_date=run_date,
            now=now,
            run_id=run_id,
            telegram=FakeTelegram(outbox=out, admin_user_id=1, auto_approve=True),
            shopee=fake,
            linker=fake,
            conversions_source=fake,
            copywriter=TemplateCopywriter(),
            image_fetcher=None,
            env=env,
            out_dir=out,
            demo=True,
        )

    required = ["DATABASE_URL"] if args.steps == "migrate" else secrets.required_secrets(config)
    secrets.require(required, env)  # falha listando só os NOMES ausentes

    from src.common.telegram import TelegramClient
    from src.content.render import fetch_image

    db = Database(env["DATABASE_URL"])
    shopee = None
    if not secrets.missing(list(secrets.SHOPEE_SECRETS), env):
        from src.sources.shopee import ShopeeClient

        shopee = ShopeeClient(env["SHOPEE_APP_ID"], env["SHOPEE_APP_SECRET"])
    copywriter: Any = TemplateCopywriter()
    if env.get("ANTHROPIC_API_KEY") and any(n.settings.llm.enabled for n in config.niches if n.is_active):
        import anthropic

        copywriter = LlmCopywriter(
            anthropic.Anthropic(api_key=env["ANTHROPIC_API_KEY"], max_retries=2, timeout=60),
            db,
            run_id,
            config.global_.llm_budget_usd_per_day,
        )
    redirect = clicks = None
    if secrets.cloudflare_configured(env):
        from src.tracking.cloudflare import CloudflareApi, D1ClickSource, RedirectRegistry

        api = CloudflareApi(env["CF_API_TOKEN"], env["CF_ACCOUNT_ID"])
        clicks = D1ClickSource(api, env["CF_D1_DATABASE_ID"])
        base = env.get("REDIRECT_BASE_URL", "").strip()
        if base.startswith("https://"):
            redirect = RedirectRegistry(api, env["CF_KV_NAMESPACE_ID"], base)
    from src.agents.links import http_link_ok

    return AppContext(
        **agent_wiring(config, price_source=shopee, llm=getattr(copywriter, "llm", None), link_checker=http_link_ok),
        config=config,
        db=db,
        run_date=run_date,
        now=now,
        run_id=run_id,
        telegram=TelegramClient(env["TELEGRAM_BOT_TOKEN"]),
        shopee=shopee,
        linker=shopee,
        conversions_source=shopee,
        copywriter=copywriter,
        image_fetcher=fetch_image,
        redirect=redirect,
        clicks_source=clicks,
        env=env,
    )


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--steps", required=True, help="lista separada por vírgula ou alias: daily, publish, report, all")
    p.add_argument("--run-date")
    p.add_argument("--niche")
    p.add_argument("--now", help="instante UTC ISO (testes e reprocessamento)")
    p.add_argument("--config")
    p.add_argument("--demo", action="store_true", help="SQLite + Shopee e Telegram falsos")
    p.add_argument("--no-notify", dest="notify", action="store_false", help="healthcheck sem mensagem de teste")
    p.add_argument("--import-conversions", help="CSV de conversões (ML/Amazon) para o passo conversions")
    p.add_argument("--month", help="AAAA-MM para o passo close (padrão: mês anterior)")
    return p.parse_args(argv)


def expand_steps(spec: str, registry: dict[str, Any]) -> list[str]:
    steps: list[str] = []
    for token in (s.strip() for s in spec.split(",") if s.strip()):
        for step in ALIASES.get(token, [token]):
            if step not in registry:
                raise SystemExit(f"passo desconhecido: {step}. Opções: {', '.join(registry)} ou {', '.join(ALIASES)}")
            steps.append(step)
    if any(s != "migrate" for s in steps) and "migrate" not in steps:
        steps.insert(0, "migrate")  # garante o schema; migrate é idempotente
    # remove só repetições seguidas: no alias `all`, approvals roda de novo depois das prévias
    return [s for i, s in enumerate(steps) if i == 0 or steps[i - 1] != s]


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if not args.demo:
        load_env_file(ROOT / ".env")
    setup_logging()
    try:
        config = load_config(args.config)
    except Exception as exc:
        print(f"config inválida: {exc}", file=sys.stderr)
        return 2
    if args.niche:
        config.niche(args.niche)  # valida o id
    try:
        ctx = build_context(args, config)
    except secrets.MissingSecretsError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    run_id_var.set(ctx.run_id)
    registry = build_steps(args)
    steps = expand_steps(args.steps, registry)
    log.info("início", extra={"data": {"steps": steps, "run_date": ctx.run_date.isoformat(), "demo": ctx.demo}})
    failures = run_steps(ctx, steps, registry, args.niche)
    if failures:
        from src.publishers.telegram import alert

        # O alerta vai em HTML: sem escape, um erro com "<" faria o Telegram recusar a mensagem inteira.
        alert(ctx, f"Falhas na execução {ctx.run_id}:\n" + html.escape("\n".join(failures)[:3500]))
        ctx.db.close()
        return 1
    if ctx.demo:
        print(f"\nDemo concluída. Veja {ctx.out_dir / 'telegram_outbox.jsonl'} e {ctx.out_dir / 'media'}")
    ctx.db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
