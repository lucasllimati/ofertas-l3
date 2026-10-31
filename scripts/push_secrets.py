"""Envia os segredos do .env para o GitHub Actions, sem digitar um por um.

    uv run python scripts/push_secrets.py --dry-run     # só mostra o que faria
    uv run python scripts/push_secrets.py               # mostra, pede confirmação e envia
    uv run python scripts/push_secrets.py --only TELEGRAM_BOT_TOKEN,TG_CASA_CHAT_ID

- Só envia nomes conhecidos pelo projeto (os de docs/secrets.md); o resto do .env é ignorado.
- O valor vai pela entrada padrão do `gh secret set`: nunca aparece na tela, no histórico nem na
  lista de processos.
- Recusa a URL do DONO do banco e valores ainda iguais aos exemplos do .env.example.
- Depois de enviar, preenche "Criado em" (e "Expira em", para credenciais com rotação de 90 dias)
  em docs/secrets.md.
- GARIMPO_ENABLED e GARIMPO_REHEARSAL vão como *variables* (não são segredo): `gh variable set`.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from collections.abc import Callable
from datetime import date, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.common import secrets  # noqa: E402
from src.common.envfile import parse_env  # noqa: E402
from src.config.loader import load_config  # noqa: E402
from src.doctor import BOT_TOKEN_RE  # noqa: E402

VARIABLES = ("GARIMPO_ENABLED", "GARIMPO_REHEARSAL")
# Credenciais que devem ser trocadas a cada 90 dias (docs/SETUP.md §17); ids e URLs públicas não expiram.
ROTATING = (
    "DATABASE_URL",
    "TELEGRAM_BOT_TOKEN",
    "APPROVAL_HMAC_SECRET",
    "SHOPEE_APP_SECRET",
    "ANTHROPIC_API_KEY",
    "CF_API_TOKEN",
)
ROTATION_DAYS = 90
PLACEHOLDERS = ("SENHA", "COLE_AQUI", "changeme")  # textos do .env.example (sensível a maiúsculas)


def known_names() -> set[str]:
    config = load_config()
    names = {*secrets.CORE_SECRETS, *secrets.SHOPEE_SECRETS, *secrets.OPTIONAL_SECRETS}
    for niche in config.niches:
        if niche.channels.telegram:
            names.add(f"{niche.channels.telegram.channel_ref}_CHAT_ID")
    return names


def problem(name: str, value: str) -> str | None:
    """Por que este valor não deve ir para produção (None = pode enviar)."""
    if any(p in value for p in PLACEHOLDERS):
        return "ainda é o valor de exemplo"
    if name == "DATABASE_URL":
        if not value.startswith(("postgres://", "postgresql://")):
            return "produção precisa de postgresql:// (Supabase)"
        user = urlsplit(value).username or ""
        if user == "postgres" or user.startswith("postgres."):
            return "é a URL do DONO do banco; no GitHub vai a do garimpo_pipeline (SETUP §5.4)"
    if name == "TELEGRAM_BOT_TOKEN" and not BOT_TOKEN_RE.match(value):
        return "fora do formato 123456789:AA..."
    if name == "APPROVAL_HMAC_SECRET" and len(value) < 32:
        return "curto demais (use 32+ caracteres aleatórios)"
    return None


def plan(env: dict[str, str], only: set[str] | None) -> tuple[list[str], list[str], dict[str, str], list[str]]:
    """(segredos a enviar, variáveis a enviar, recusados {nome: motivo}, ignorados)."""
    known = known_names()
    to_send, variables, refused, ignored = [], [], {}, []
    for name, value in sorted(env.items()):
        if only and name not in only:
            continue
        if name in VARIABLES:
            variables.append(name)
        elif name not in known:
            ignored.append(name)
        elif reason := problem(name, value):
            refused[name] = reason
        else:
            to_send.append(name)
    return to_send, variables, refused, ignored


def update_inventory(path: Path, names: list[str], today: date) -> int:
    """Preenche Criado em/Expira em das linhas enviadas. Devolve quantas linhas mudaram."""
    lines = path.read_text(encoding="utf-8").splitlines()
    changed = 0
    for i, line in enumerate(lines):
        cells = line.strip().strip("|").split("|")
        if len(cells) < 7:
            continue
        name = cells[0].strip().strip("`")
        if name not in names or not re.fullmatch(r"[A-Z][A-Z0-9_]+", name):
            continue
        cells[4] = f" {today.isoformat()} "
        if name in ROTATING:
            cells[5] = f" {(today + timedelta(days=ROTATION_DAYS)).isoformat()} "
        lines[i] = "|" + "|".join(cells) + "|"
        changed += 1
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return changed


def push(
    env: dict[str, str],
    secrets_to_send: list[str],
    variables: list[str],
    repo: str | None,
    runner: Callable[..., Any] = subprocess.run,
) -> list[str]:
    """Envia; devolve os nomes que falharam (sem o valor)."""
    repo_args = ["--repo", repo] if repo else []
    failed = []
    for name in secrets_to_send:
        result = runner(["gh", "secret", "set", name, *repo_args], input=env[name], text=True, capture_output=True)
        if result.returncode != 0:
            failed.append(name)
    for name in variables:
        command = ["gh", "variable", "set", name, "--body", env[name], *repo_args]
        result = runner(command, text=True, capture_output=True)
        if result.returncode != 0:
            failed.append(name)
    return failed


def main(argv: list[str] | None = None, runner: Callable[..., Any] = subprocess.run, ask=input) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--env-file", default=str(ROOT / ".env"))
    parser.add_argument("--repo", help="dono/repositório (padrão: o do gh nesta pasta)")
    parser.add_argument("--only", help="só estes nomes, separados por vírgula")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--yes", action="store_true", help="não pede confirmação")
    parser.add_argument("--inventory", default=str(ROOT / "docs" / "secrets.md"))
    args = parser.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    path = Path(args.env_file)
    if not path.exists():
        print(f"{path} não existe: copie o .env.example para .env e preencha (SETUP §12.3)", file=sys.stderr)
        return 2
    env = parse_env(path.read_text(encoding="utf-8"))
    only = {n.strip() for n in args.only.split(",")} if args.only else None
    to_send, variables, refused, ignored = plan(env, only)

    print(f"Segredos a enviar ({len(to_send)}): {', '.join(to_send) or '-'}")
    if variables:
        print(f"Variáveis a enviar: {', '.join(f'{v}={env[v]}' for v in variables)}")
    for name, reason in refused.items():
        print(f"⛔ {name} não será enviado: {reason}")
    if ignored:
        print(f"Ignorados (não são do projeto ou são só locais): {', '.join(ignored)}")
    if not to_send and not variables:
        print("Nada a enviar.")
        return 1 if refused else 0
    if args.dry_run:
        print("--dry-run: nada foi enviado.")
        return 0
    target = args.repo or "o repositório desta pasta"
    if not args.yes and ask(f"Enviar para {target}? [s/N] ").strip().lower() not in ("s", "sim", "y", "yes"):
        print("Cancelado.")
        return 1

    failed = push(env, to_send, variables, args.repo, runner)
    sent = [n for n in to_send if n not in failed]
    if sent:
        changed = update_inventory(Path(args.inventory), sent, date.today())
        print(f"✅ {len(sent)} segredos enviados; {changed} linhas de docs/secrets.md atualizadas (faça commit).")
    if failed:
        print(f"❌ Falharam: {', '.join(failed)}. Rode `gh auth status` e tente de novo.", file=sys.stderr)
        return 1
    print("Confira com: uv run python -m src.doctor --only github")
    return 1 if refused else 0


if __name__ == "__main__":
    raise SystemExit(main())
