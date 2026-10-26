"""Assistente de verificação do setup: testa cada credencial e configuração separadamente.

    uv run python -m src.doctor                     # tudo
    uv run python -m src.doctor --only telegram,banco
    uv run python -m src.doctor --offline           # só o que não usa rede

Mostra ✅ ok, ⚠️ aviso, ❌ falha ou ⏭ pulado, com a seção do docs/SETUP.md que resolve cada falha.
Pode rodar a qualquer momento do setup: o que ainda não foi configurado aparece como falha ou pulado,
sem quebrar o resto. Nunca mostra valores de segredo, só nomes. Não publica nada nem altera o banco.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from src.common import secrets
from src.common.envfile import load_env_file
from src.common.logging import redact
from src.config.models import AppConfig

ROOT = Path(__file__).resolve().parents[1]
GROUPS = ("config", "segredos", "telegram", "banco", "shopee", "claude", "cloudflare", "monitor", "github")
BOT_TOKEN_RE = re.compile(r"^\d{6,12}:[A-Za-z0-9_-]{30,}$")
ICONS = {"ok": "✅", "warn": "⚠️ ", "fail": "❌", "skip": "⏭ "}


@dataclass
class Check:
    group: str
    name: str
    status: str  # ok | warn | fail | skip
    detail: str
    section: str = ""  # seção do SETUP que resolve

    def line(self) -> str:
        where = f" → SETUP §{self.section}" if self.section and self.status in ("fail", "warn") else ""
        return f"{ICONS[self.status]} {self.group} · {self.name}: {self.detail}{where}"


class Doctor:
    def __init__(
        self,
        env: dict[str, str],
        config: AppConfig | None,
        *,
        telegram: Any = None,
        db_factory: Callable[[str], Any] | None = None,
        shopee_factory: Callable[[str, str], Any] | None = None,
        http: httpx.Client | None = None,
        runner: Callable[..., Any] = subprocess.run,
        which: Callable[[str], str | None] = shutil.which,
        repo: str | None = None,
        offline: bool = False,
        root: Path = ROOT,
    ):
        self.env = env
        self.config = config
        self._telegram = telegram
        self._db_factory = db_factory
        self._shopee_factory = shopee_factory
        self.http = http or httpx.Client(timeout=15)
        self.runner = runner
        self.which = which
        self.repo = repo
        self.offline = offline
        self.root = root
        self.checks: list[Check] = []
        self._secret_values = [v for v in env.values() if v and len(v) >= 6]

    # ------------------------------------------------------------------ helpers
    def add(self, group: str, name: str, status: str, detail: str, section: str = "") -> None:
        self.checks.append(Check(group, name, status, redact(detail, self._secret_values), section))

    def value(self, name: str) -> str:
        return self.env.get(name, "").strip()

    def error(self, exc: Exception) -> str:
        return redact(f"{type(exc).__name__}: {exc}", self._secret_values)[:200]

    def active_niches(self) -> list:
        return [n for n in self.config.niches if n.is_active] if self.config else []

    def run(self, only: set[str] | None = None) -> list[Check]:
        for group in GROUPS:
            if only and group not in only:
                continue
            try:
                getattr(self, f"check_{group}")()
            except Exception as exc:  # um grupo com erro inesperado não esconde os outros
                self.add(group, "erro inesperado", "fail", self.error(exc))
        return self.checks

    # ------------------------------------------------------------------- grupos
    def check_config(self) -> None:
        if self.config is None:
            self.add("config", "niches.yaml", "fail", "inválido: rode `uv run python -m src.config.validate`", "15")
            return
        from src.config.validate import agent_config_problems

        active = ", ".join(n.id for n in self.active_niches()) or "nenhum"
        self.add("config", "niches.yaml", "ok", f"{len(self.config.niches)} nichos, ativos: {active}")
        problems = agent_config_problems(self.config)
        if problems:
            self.add("config", "agentes", "fail", "; ".join(problems)[:300], "15")
        else:
            self.add("config", "agentes", "ok", "calendar.yaml, coupons.csv e finance.yaml válidos")
        manual = [n.id for n in self.active_niches() if not n.uses_shopee_api]
        if manual:
            self.add(
                "config", "ofertas", "warn", f"sem Shopee API em {', '.join(manual)}: só o CSV manual alimenta", "6.4"
            )

    def check_segredos(self) -> None:
        if self.config is None:
            return
        required = secrets.required_secrets(self.config)
        absent = secrets.missing(required, self.env)
        if absent:
            self.add("segredos", "obrigatórios", "fail", "faltam " + ", ".join(absent), "12.1")
        else:
            self.add("segredos", "obrigatórios", "ok", f"{len(required)} presentes")
        hmac = self.value("APPROVAL_HMAC_SECRET")
        if hmac and len(hmac) < 32:
            self.add("segredos", "APPROVAL_HMAC_SECRET", "fail", f"curto ({len(hmac)} caracteres; use 32+)", "4.4")
        ids = self.value("TELEGRAM_ADMIN_USER_IDS")
        if ids and not all(x.strip().isdigit() for x in ids.replace(";", ",").split(",") if x.strip()):
            self.add("segredos", "TELEGRAM_ADMIN_USER_IDS", "fail", "use só números separados por vírgula", "4.2")
        passphrase = self.value("BACKUP_PASSPHRASE")
        if not passphrase:
            self.add("segredos", "BACKUP_PASSPHRASE", "warn", "ausente: o backup semanal não roda", "12.5")
        elif len(passphrase) < 20:
            self.add("segredos", "BACKUP_PASSPHRASE", "warn", "curta (use 32+ caracteres aleatórios)", "12.5")
        self._check_inventory()

    def _check_inventory(self) -> None:
        path = self.root / "docs" / "secrets.md"
        if not path.exists() or self.config is None:
            return
        undated = []
        for line in path.read_text(encoding="utf-8").splitlines():
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if len(cells) >= 6 and cells[0].strip("`") in secrets.required_secrets(self.config) and cells[4] == "-":
                undated.append(cells[0].strip("`"))
        if undated:
            self.add(
                "segredos",
                "inventário",
                "warn",
                f"sem data de criação em docs/secrets.md: {', '.join(undated)} (o push_secrets preenche)",
                "12.4",
            )

    def check_telegram(self) -> None:
        token = self.value("TELEGRAM_BOT_TOKEN")
        if not token:
            self.add("telegram", "bot", "fail", "TELEGRAM_BOT_TOKEN ausente", "4.1")
            return
        if not BOT_TOKEN_RE.match(token):
            self.add("telegram", "bot", "fail", "TELEGRAM_BOT_TOKEN fora do formato 123456789:AA...", "4.1")
            return
        if self.offline:
            self.add("telegram", "bot", "skip", "modo offline")
            return
        from src.common.telegram import TelegramClient
        from src.run import channel_problem

        tg = self._telegram or TelegramClient(token)
        try:
            me = tg.get_me()
        except Exception as exc:
            self.add("telegram", "bot", "fail", f"token recusado ({self.error(exc)}): confira ou gere outro", "4.1")
            return
        self.add("telegram", "bot", "ok", f"@{me.get('username')}")
        admin = self.value("TELEGRAM_ADMIN_CHAT_ID")
        if not admin:
            self.add("telegram", "chat de admin", "fail", "TELEGRAM_ADMIN_CHAT_ID ausente", "4.2")
        else:
            try:
                tg.get_chat(admin)
                self.add("telegram", "chat de admin", "ok", "o bot consegue falar com você")
            except Exception:
                self.add("telegram", "chat de admin", "fail", "inacessível: envie /start ao bot e confira o id", "4.2")
        for niche in self.active_niches():
            var = secrets.telegram_chat_var(niche)
            if not var:
                continue
            problem = channel_problem(tg, me["id"], self.value(var))
            if problem:
                self.add("telegram", f"canal {niche.id}", "fail", f"{var}: {problem}", "4.3")
            else:
                self.add("telegram", f"canal {niche.id}", "ok", "bot pode publicar")

    def check_banco(self) -> None:
        url = self.value("DATABASE_URL")
        if not url:
            self.add("banco", "conexão", "fail", "DATABASE_URL ausente", "5.4")
            return
        if url.startswith("sqlite:"):
            self.add("banco", "conexão", "warn", "SQLite: serve só para teste local; produção usa o Supabase", "5")
        elif not url.startswith(("postgres://", "postgresql://")):
            self.add("banco", "conexão", "fail", "DATABASE_URL precisa começar com postgresql://", "5.2")
            return
        if "SENHA" in url:
            self.add("banco", "conexão", "fail", "DATABASE_URL ainda é o exemplo do .env.example", "5.4")
            return
        if self.offline and not url.startswith("sqlite:"):
            self.add("banco", "conexão", "skip", "modo offline")
            return
        from src.common.db import Database

        try:
            db = (self._db_factory or Database)(url)
        except Exception as exc:
            hint = "use o Session pooler (IPv4) e confira usuário.<project-ref> e senha"
            self.add("banco", "conexão", "fail", f"{self.error(exc)}; {hint}", "18")
            return
        try:
            owner = db.can_change_schema()
            pending = db.pending_migrations()
            if db.dialect == "postgres":
                if owner:
                    self.add(
                        "banco",
                        "usuário",
                        "warn",
                        "esta URL é do DONO (pode alterar tabelas). No GitHub use a do garimpo_pipeline",
                        "5.4",
                    )
                else:
                    self.add("banco", "usuário", "ok", "usuário do pipeline, sem permissão de alterar tabelas")
            if pending:
                status = "warn" if owner else "fail"
                detail = f"pendentes: {', '.join(pending)}; rode migrate como dono"
                self.add("banco", "migrations", status, detail, "5.3")
            else:
                db.scalar("SELECT count(*) FROM content_item")
                self.add("banco", "migrations", "ok", "schema em dia e tabelas acessíveis")
        finally:
            db.close()

    def check_shopee(self) -> None:
        needed = any(n.uses_shopee_api for n in self.active_niches())
        app_id, secret = self.value("SHOPEE_APP_ID"), self.value("SHOPEE_APP_SECRET")
        if not (app_id and secret):
            if needed:
                detail = "mode: api sem SHOPEE_APP_ID/SECRET (ou use mode: off + CSV, §6.4)"
                self.add("shopee", "Open API", "fail", detail, "6.2")
            else:
                self.add("shopee", "Open API", "skip", "não configurada (ofertas só pelo CSV)")
            return
        if self.offline:
            self.add("shopee", "Open API", "skip", "modo offline")
            return
        from src.sources.shopee import ShopeeClient

        client = (self._shopee_factory or (lambda a, s: ShopeeClient(a, s, max_retries=0)))(app_id, secret)
        try:
            offers = client.search("organizador", 1)
            self.add("shopee", "Open API", "ok", f"assinatura aceita ({len(offers)} oferta na busca de teste)")
        except Exception as exc:
            self.add("shopee", "Open API", "fail", f"{self.error(exc)}: confira AppID/Secret no painel", "6.2")

    def check_claude(self) -> None:
        key = self.value("ANTHROPIC_API_KEY")
        if not key:
            self.add("claude", "API", "skip", "opcional: sem chave a copy sai do template")
            return
        if not key.startswith("sk-ant-"):
            self.add("claude", "API", "fail", "ANTHROPIC_API_KEY não começa com sk-ant-", "9")
            return
        if self.offline:
            self.add("claude", "API", "skip", "modo offline")
            return
        resp = self.http.get(
            "https://api.anthropic.com/v1/models",
            params={"limit": 1},
            headers={"x-api-key": key, "anthropic-version": "2023-06-01"},
        )
        if resp.status_code == 200:
            self.add("claude", "API", "ok", "chave aceita")
        elif resp.status_code in (401, 403):
            self.add("claude", "API", "fail", f"chave recusada (HTTP {resp.status_code})", "9")
        else:
            self.add("claude", "API", "warn", f"resposta inesperada HTTP {resp.status_code}; tente mais tarde", "9")

    def check_cloudflare(self) -> None:
        present = [n for n in secrets.CLOUDFLARE_SECRETS if self.value(n)]
        if not present:
            self.add("cloudflare", "redirecionador /go", "skip", "opcional: sem contagem de cliques")
            return
        absent = secrets.missing(list(secrets.CLOUDFLARE_SECRETS), self.env)
        if absent:
            self.add("cloudflare", "variáveis", "fail", "configure as 4 juntas; faltam " + ", ".join(absent), "10.3")
            return
        base = self.value("REDIRECT_BASE_URL")
        if not base.startswith("https://"):
            self.add("cloudflare", "REDIRECT_BASE_URL", "fail", "ausente ou sem https://", "10.3")
        if self.offline:
            self.add("cloudflare", "token", "skip", "modo offline")
            return
        resp = self.http.get(
            "https://api.cloudflare.com/client/v4/user/tokens/verify",
            headers={"Authorization": f"Bearer {self.value('CF_API_TOKEN')}"},
        )
        body = resp.json() if resp.content else {}
        if resp.status_code == 200 and (body.get("result") or {}).get("status") == "active":
            self.add("cloudflare", "token", "ok", "CF_API_TOKEN ativo")
        else:
            detail = f"CF_API_TOKEN recusado ou expirado (HTTP {resp.status_code})"
            self.add("cloudflare", "token", "fail", detail, "10.3")
        if base.startswith("https://"):
            try:
                health = self.http.get(f"{base.rstrip('/')}/health")
                ok = health.status_code == 200 and health.text.strip() == "ok"
            except httpx.HTTPError:
                ok = False
            if ok:
                self.add("cloudflare", "Worker", "ok", "/health respondeu ok")
            else:
                self.add("cloudflare", "Worker", "fail", "/health não respondeu ok: rode npx wrangler deploy", "10.2")

    def check_monitor(self) -> None:
        from src.run import HEARTBEAT_RE

        url = self.value("HEARTBEAT_URL")
        if not url:
            detail = "HEARTBEAT_URL ausente: se o sistema parar, ninguém avisa"
            self.add("monitor", "aviso de parada", "warn", detail, "13.2")
        elif not HEARTBEAT_RE.match(url):
            self.add("monitor", "aviso de parada", "fail", "HEARTBEAT_URL precisa ser https:// (Ping URL)", "13.2")
        else:
            self.add("monitor", "aviso de parada", "ok", "configurado; o primeiro ping vem da próxima execução")
        rehearsal = self.value("GARIMPO_REHEARSAL").lower()
        if rehearsal in ("1", "true", "yes", "sim", "on"):
            self.add("monitor", "modo ensaio", "warn", "ativo no .env: posts vão só para o seu chat", "13.1")

    def check_github(self) -> None:
        if self.offline:
            self.add("github", "secrets", "skip", "modo offline")
            return
        if not self.which("gh"):
            self.add("github", "secrets", "skip", "GitHub CLI (gh) não instalado", "2")
            return
        repo = ["--repo", self.repo] if self.repo else []
        result = self.runner(
            ["gh", "secret", "list", "--json", "name", *repo], capture_output=True, text=True, timeout=60
        )
        if result.returncode != 0:
            self.add("github", "secrets", "skip", "gh sem login ou sem acesso ao repositório (gh auth login)", "2")
            return
        names = {item["name"] for item in json.loads(result.stdout or "[]")}
        required = secrets.required_secrets(self.config) if self.config else list(secrets.CORE_SECRETS)
        absent = [n for n in required if n not in names]
        if absent:
            self.add("github", "secrets", "fail", "faltam no GitHub: " + ", ".join(absent), "12.2")
        else:
            self.add("github", "secrets", "ok", f"{len(required)} obrigatórios cadastrados")
        optional = [n for n in (*secrets.OPTIONAL_SECRETS, *secrets.SHOPEE_SECRETS) if self.value(n)]
        local_only = [n for n in optional if n not in names]
        if local_only:
            detail = "no .env mas não no GitHub: " + ", ".join(local_only)
            self.add("github", "secrets opcionais", "warn", detail, "12.2")
        variables = self.runner(
            ["gh", "variable", "list", "--json", "name,value", *repo], capture_output=True, text=True, timeout=60
        )
        if variables.returncode == 0:
            values = {v["name"]: v.get("value", "") for v in json.loads(variables.stdout or "[]")}
            if values.get("GARIMPO_REHEARSAL", "").strip().lower() in ("1", "true", "yes", "sim", "on"):
                self.add("github", "modo ensaio", "warn", "GARIMPO_REHEARSAL ativo em produção", "13.1")


def summary(checks: list[Check]) -> str:
    count = {s: sum(1 for c in checks if c.status == s) for s in ICONS}
    text = f"Resumo: {count['ok']} ok · {count['warn']} avisos · {count['fail']} falhas · {count['skip']} pulados"
    first = next((c for c in checks if c.status == "fail"), None)
    if first:
        text += f"\nComece por: {first.group} · {first.name}" + (f" (SETUP §{first.section})" if first.section else "")
    return text


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--only", help=f"grupos separados por vírgula: {', '.join(GROUPS)}")
    parser.add_argument("--offline", action="store_true", help="não chama Telegram, banco, Shopee, Claude nem GitHub")
    parser.add_argument("--repo", help="dono/repositório para conferir os secrets (padrão: o do gh)")
    parser.add_argument("--config", default=None)
    args = parser.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")  # console do Windows usa cp1252
    load_env_file(ROOT / ".env")

    from src.config.loader import load_config

    try:
        config = load_config(args.config)
    except Exception:
        config = None
    only = {g.strip() for g in args.only.split(",")} if args.only else None
    if only and only - set(GROUPS):
        parser.error(f"grupo desconhecido: {', '.join(sorted(only - set(GROUPS)))}")
    doctor = Doctor(dict(os.environ), config, repo=args.repo, offline=args.offline)
    checks = doctor.run(only)
    print("Garimpo doctor\n")
    for check in checks:
        print(check.line())
    print("\n" + summary(checks))
    return 1 if any(c.status == "fail" for c in checks) else 0


if __name__ == "__main__":
    raise SystemExit(main())
