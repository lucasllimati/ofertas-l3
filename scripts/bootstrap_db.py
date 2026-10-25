"""Prepara o banco de produção de uma vez (substitui os passos manuais do SETUP §5.3 e §5.4).

    uv run python scripts/bootstrap_db.py            # pede a URL do dono (digitação escondida)
    uv run python scripts/bootstrap_db.py --rotate   # troca a senha do usuário do pipeline

1. Conecta com a URL do DONO (só nesta máquina; ela nunca vai para o GitHub).
2. Aplica as migrations pendentes (schema, tabelas, papéis, RLS).
3. Cria o usuário `garimpo_pipeline` no papel `app_writer`, com senha aleatória forte.
4. Testa a URL do pipeline: lê as tabelas e confirma que NÃO consegue alterar o schema.
5. Grava `DATABASE_URL` (a do pipeline) no .env. A senha não aparece na tela.

Depois: `uv run python scripts/push_secrets.py --only DATABASE_URL` envia para o GitHub.
"""

from __future__ import annotations

import argparse
import getpass
import os
import re
import secrets
import sys
import time
from pathlib import Path
from urllib.parse import quote, urlsplit, urlunsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.common.db import Database  # noqa: E402
from src.common.envfile import set_env_value  # noqa: E402

ROLE = "garimpo_pipeline"
ROLE_RE = re.compile(r"^[a-z_][a-z0-9_]{2,40}$")


def pipeline_url(owner_url: str, role: str, password: str) -> str:
    """Mesma conexão do dono, com o usuário do pipeline. No pooler do Supabase o usuário leva o
    `.<project-ref>` (postgres.abc -> garimpo_pipeline.abc)."""
    parts = urlsplit(owner_url)
    user = parts.username or ""
    suffix = user[user.index(".") :] if "." in user else ""
    host = parts.hostname or ""
    if ":" in host:
        host = f"[{host}]"
    netloc = f"{quote(role + suffix, safe='.')}:{quote(password, safe='')}@{host}"
    if parts.port:
        netloc += f":{parts.port}"
    return urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))


def ensure_role(db: Database, role: str, password: str, rotate: bool) -> str:
    """Cria o usuário (ou troca a senha, com rotate). Devolve 'created', 'rotated' ou 'exists'."""
    from psycopg import sql

    exists = db.scalar("SELECT count(*) FROM pg_roles WHERE rolname = ?", (role,))
    if exists and not rotate:
        return "exists"
    if exists:
        statement = sql.SQL("ALTER ROLE {} WITH LOGIN PASSWORD {}")
    else:
        statement = sql.SQL("CREATE ROLE {} LOGIN PASSWORD {} IN ROLE app_writer")
    db._conn.execute(statement.format(sql.Identifier(role), sql.Literal(password)))
    db._conn.execute(sql.SQL("ALTER ROLE {} SET search_path = garimpo, public").format(sql.Identifier(role)))
    return "rotated" if exists else "created"


def verify_pipeline(url: str, attempts: int = 5, wait_s: float = 3.0) -> None:
    """O pooler do Supabase pode levar alguns segundos para conhecer o usuário novo."""
    last: Exception | None = None
    for attempt in range(attempts):
        try:
            db = Database(url)
            break
        except Exception as exc:
            last = exc
            if attempt < attempts - 1:
                time.sleep(wait_s)
    else:
        raise RuntimeError(f"o usuário do pipeline não conectou ({type(last).__name__})") from None
    try:
        db.scalar("SELECT count(*) FROM content_item")
        if db.can_change_schema():
            raise RuntimeError("o usuário do pipeline consegue alterar o schema: confira o papel app_writer")
    finally:
        db.close()


def bootstrap(owner_url: str, env_path: Path, role: str = ROLE, rotate: bool = False, verify_attempts: int = 5) -> str:
    if not owner_url.startswith(("postgres://", "postgresql://")):
        raise SystemExit("a URL do dono precisa começar com postgresql:// (Supabase → Connect → Session pooler)")
    if not ROLE_RE.match(role):
        raise SystemExit("nome de usuário inválido")
    db = Database(owner_url)
    try:
        if not db.can_change_schema():
            raise SystemExit("esta URL não é do dono do banco (não pode criar tabelas): use a do usuário postgres")
        applied = db.migrate()
        print(f"✅ migrations: {', '.join(applied) if applied else 'nenhuma pendente'}")
        password = secrets.token_urlsafe(32)
        status = ensure_role(db, role, password, rotate)
    finally:
        db.close()
    if status == "exists":
        print(f"ℹ️ o usuário {role} já existe. Para gerar uma senha nova e gravar no .env: --rotate")
        return status
    url = pipeline_url(owner_url, role, password)
    verify_pipeline(url, attempts=verify_attempts)
    action = "criado" if status == "created" else "com senha nova"
    print(f"✅ usuário {role} {action}; lê as tabelas e não altera o schema")
    replaced = set_env_value(env_path, "DATABASE_URL", url)
    print(f"✅ DATABASE_URL do pipeline gravada em {env_path}" + (" (substituiu a anterior)" if replaced else ""))
    print("Próximo passo: uv run python scripts/push_secrets.py --only DATABASE_URL")
    if status == "rotated":
        print("⚠️ A senha antiga parou de valer: envie a nova ao GitHub antes da próxima execução.")
    return status


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--rotate", action="store_true", help="troca a senha do usuário do pipeline")
    parser.add_argument("--env-file", default=str(ROOT / ".env"))
    parser.add_argument("--role", default=ROLE)
    args = parser.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    owner_url = os.environ.get("OWNER_DATABASE_URL") or getpass.getpass(
        "URL do DONO (Supabase → Connect → Session pooler; a digitação não aparece): "
    )
    try:
        bootstrap(owner_url.strip(), Path(args.env_file), args.role, args.rotate)
    except SystemExit:
        raise
    except Exception as exc:
        # Só o tipo do erro: mensagens do driver podem repetir partes da URL.
        print(f"❌ falhou ({type(exc).__name__}). Confira a URL do Session pooler e a senha do dono.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
