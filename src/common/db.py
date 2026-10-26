"""Acesso ao banco: Postgres em produção, SQLite no modo demo e nos testes.

O SQL do projeto é escrito com placeholders `?` e só usa recursos comuns aos dois
(ON CONFLICT, RETURNING, tipos TEXT/INTEGER/REAL). Todo valor vai parametrizado.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from src.common.logging import get_logger

log = get_logger(__name__)

ROOT = Path(__file__).resolve().parents[2]
MIGRATIONS_DIR = ROOT / "sql" / "migrations"
PG_SCHEMA = "garimpo"


LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1", ""}


class PendingMigrationsError(RuntimeError):
    """Há migration nova, mas o usuário conectado (o do pipeline) não pode alterar o schema."""

    def __init__(self, pending: list[str]):
        super().__init__(
            f"migration pendente: {', '.join(pending)}. O usuário do pipeline não altera o schema: rode "
            "`python -m src.run --steps migrate` com a URL do dono do banco (docs/SETUP.md §5.3) e depois "
            "repita esta execução"
        )
        self.pending = pending


def tls_options(url: str) -> dict[str, str]:
    """Fora da máquina local, exige TLS. O padrão do libpq (sslmode=prefer) aceita cair para texto puro."""
    from psycopg.conninfo import conninfo_to_dict

    info = conninfo_to_dict(url)
    if "sslmode" in info or str(info.get("host", "")) in LOCAL_HOSTS:
        return {}
    return {"sslmode": "require"}


class Database:
    def __init__(self, url: str):
        self.url = url
        self._in_tx = False
        if url.startswith("sqlite:"):
            self.dialect = "sqlite"
            path = url.removeprefix("sqlite:///").removeprefix("sqlite://") or ":memory:"
            if path != ":memory:":
                Path(path).parent.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(path, isolation_level=None, check_same_thread=False)
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA foreign_keys = ON")
            self._conn.execute("PRAGMA busy_timeout = 5000")
        elif url.startswith(("postgres://", "postgresql://")):
            import psycopg
            from psycopg.rows import dict_row

            self.dialect = "postgres"
            self._conn = psycopg.connect(
                url, autocommit=True, row_factory=dict_row, connect_timeout=15, **tls_options(url)
            )
            # Tabelas ficam no schema `garimpo`, fora do schema `public` exposto pela API do Supabase.
            self._conn.execute(f"SET search_path TO {PG_SCHEMA}, public")
        else:
            raise ValueError("DATABASE_URL precisa começar com sqlite:/// ou postgresql://")

    # ------------------------------------------------------------------ queries
    def _sql(self, sql: str) -> str:
        if self.dialect == "postgres":
            return sql.replace("%", "%%").replace("?", "%s")
        return sql

    def execute(self, sql: str, params: Sequence[Any] = ()) -> int:
        cur = self._conn.execute(self._sql(sql), tuple(params))
        return cur.rowcount

    def executemany(self, sql: str, rows: Sequence[Sequence[Any]]) -> None:
        if not rows:
            return
        if self.dialect == "sqlite":
            self._conn.executemany(sql, [tuple(r) for r in rows])
        else:
            with self._conn.cursor() as cur:
                cur.executemany(self._sql(sql), [tuple(r) for r in rows])

    def fetchall(self, sql: str, params: Sequence[Any] = ()) -> list[dict[str, Any]]:
        cur = self._conn.execute(self._sql(sql), tuple(params))
        return [dict(r) for r in cur.fetchall()]

    def fetchone(self, sql: str, params: Sequence[Any] = ()) -> dict[str, Any] | None:
        cur = self._conn.execute(self._sql(sql), tuple(params))
        row = cur.fetchone()
        return dict(row) if row is not None else None

    def scalar(self, sql: str, params: Sequence[Any] = ()) -> Any:
        row = self.fetchone(sql, params)
        return next(iter(row.values())) if row else None

    def executescript(self, script: str) -> None:
        if self.dialect == "sqlite":
            self._conn.executescript(script)
        else:
            self._conn.execute(script)

    @contextmanager
    def transaction(self) -> Iterator[None]:
        if self._in_tx:  # transações aninhadas viram parte da externa
            yield
            return
        self._in_tx = True
        try:
            if self.dialect == "sqlite":
                self._conn.execute("BEGIN")
                try:
                    yield
                except BaseException:
                    self._conn.execute("ROLLBACK")
                    raise
                self._conn.execute("COMMIT")
            else:
                with self._conn.transaction():
                    yield
        finally:
            self._in_tx = False

    def close(self) -> None:
        self._conn.close()

    # --------------------------------------------------------------- migrations
    def _migration_files(self, directory: Path) -> list[Path]:
        return [
            p for p in sorted(directory.glob("*.sql")) if self.dialect == "postgres" or not p.name.endswith(".pg.sql")
        ]

    def pending_migrations(self, directory: Path = MIGRATIONS_DIR) -> list[str]:
        """Migrations ainda não aplicadas, sem alterar nada (doctor e trava do migrate)."""
        if self.dialect == "postgres":
            exists = self.scalar("SELECT to_regclass(?)", (f"{PG_SCHEMA}.schema_migrations",))
        else:
            exists = self.scalar("SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'schema_migrations'")
        done = {r["version"] for r in self.fetchall("SELECT version FROM schema_migrations")} if exists else set()
        return [p.name for p in self._migration_files(directory) if p.name not in done]

    def can_change_schema(self) -> bool:
        """O usuário conectado pode criar objetos no schema (dono) ou é o do pipeline (só DML)?"""
        if self.dialect != "postgres":
            return True
        if not self.scalar("SELECT count(*) FROM pg_namespace WHERE nspname = ?", (PG_SCHEMA,)):
            return bool(self.scalar("SELECT has_database_privilege(current_user, current_database(), 'CREATE')"))
        return bool(self.scalar("SELECT has_schema_privilege(current_user, ?, 'CREATE')", (PG_SCHEMA,)))

    def migrate(self, directory: Path = MIGRATIONS_DIR) -> list[str]:
        """Aplica migrations pendentes. `*.pg.sql` só roda no Postgres.

        Com o usuário do pipeline (sem DDL), não tenta aplicar: falha com uma mensagem que diz o que fazer,
        em vez de um "permission denied" no meio do script.
        """
        pending = self.pending_migrations(directory)
        if not pending:
            return []
        if not self.can_change_schema():
            raise PendingMigrationsError(pending)
        ddl = "CREATE TABLE IF NOT EXISTS schema_migrations (version TEXT PRIMARY KEY, applied_at TEXT NOT NULL)"
        if self.dialect == "postgres":
            # Checa antes de criar: o papel do pipeline (app_writer) não tem permissão de CREATE.
            if not self.scalar("SELECT count(*) FROM pg_namespace WHERE nspname = ?", (PG_SCHEMA,)):
                self._conn.execute(f"CREATE SCHEMA {PG_SCHEMA}")
            self._conn.execute(f"SET search_path TO {PG_SCHEMA}, public")
            if self.scalar("SELECT to_regclass(?)", (f"{PG_SCHEMA}.schema_migrations",)) is None:
                self.execute(ddl)
        else:
            self.execute(ddl)
        done = {r["version"] for r in self.fetchall("SELECT version FROM schema_migrations")}
        applied = []
        for path in self._migration_files(directory):
            if path.name in done:
                continue
            log.info("aplicando migration", extra={"data": {"file": path.name}})
            script = path.read_text(encoding="utf-8")
            record = "INSERT INTO schema_migrations (version, applied_at) VALUES (?, ?)"
            stamp = datetime.now(UTC).isoformat(timespec="seconds")
            if self.dialect == "sqlite":
                # executescript faz COMMIT implícito; a transação vai dentro do próprio script.
                self._conn.executescript(f"BEGIN;\n{script}\nCOMMIT;")
                self.execute(record, (path.name, stamp))
            else:
                with self.transaction():
                    self.executescript(script)
                    self.execute(record, (path.name, stamp))
            applied.append(path.name)
        return applied


def connect(url: str) -> Database:
    return Database(url)
