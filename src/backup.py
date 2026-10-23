"""Backup lógico do histórico (o Supabase Free não faz backup automático).

Gera out/backup/garimpo-<data>.jsonl.gz em texto. O workflow criptografa com AES-256
(BACKUP_PASSPHRASE) e só então guarda como artefato; o arquivo aberto é apagado.
Restauração: scripts/restore_backup.py (docs/runbook.md).
"""

from __future__ import annotations

import gzip
import json
import re
from pathlib import Path
from typing import Any

from src.common.db import Database
from src.common.util import iso
from src.context import AppContext

FORMAT_VERSION = 1
# Ordem respeita as chaves estrangeiras (product antes das tabelas que apontam para ele).
# Ficam de fora os snapshots brutos (bronze), que são grandes e podem ser recoletados.
BACKUP_TABLES = [
    "niche",
    "product",
    "product_niche",
    "product_daily",
    "price_history",
    "product_score",
    "content_item",
    "click_event",
    "conversion",
    "agent_run",
    "pipeline_run",
    "audit_log",
    "channel_state",
    "kv_state",
]
IDENTIFIER_RE = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")


def export_backup(ctx: AppContext) -> dict[str, Any]:
    out = ctx.out_dir / "backup" / f"garimpo-{ctx.run_date.isoformat()}.jsonl.gz"
    out.parent.mkdir(parents=True, exist_ok=True)
    counts: dict[str, int] = {}
    with gzip.open(out, "wt", encoding="utf-8") as fh:
        fh.write(json.dumps({"format": FORMAT_VERSION, "created_at": iso(ctx.now), "tables": BACKUP_TABLES}) + "\n")
        for table in BACKUP_TABLES:
            rows = ctx.db.fetchall(f"SELECT * FROM {table}")
            counts[table] = len(rows)
            for row in rows:
                fh.write(json.dumps({"t": table, "r": row}, ensure_ascii=False, default=str) + "\n")
    return {"file": out.name, "rows": sum(counts.values()), "tables": counts}


def restore_backup(db: Database, path: Path) -> dict[str, int]:
    """Insere o conteúdo do backup sem sobrescrever o que já existe (ON CONFLICT DO NOTHING).

    Tabela e colunas vêm do arquivo: só nomes conhecidos e no formato de identificador são aceitos,
    para que um backup adulterado não vire SQL arbitrário.
    """
    counts: dict[str, int] = {}
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        header = json.loads(fh.readline())
        if header.get("format") != FORMAT_VERSION:
            raise ValueError(f"formato de backup não suportado: {header.get('format')}")
        with db.transaction():
            for line in fh:
                item = json.loads(line)
                table, row = item["t"], item["r"]
                if table not in BACKUP_TABLES:
                    raise ValueError(f"tabela inesperada no backup: {table!r}")
                columns = list(row)
                if not columns or not all(IDENTIFIER_RE.match(c) for c in columns):
                    raise ValueError(f"coluna inválida no backup da tabela {table}")
                placeholders = ", ".join("?" for _ in columns)
                inserted = db.execute(
                    f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({placeholders}) ON CONFLICT DO NOTHING",
                    [row[c] for c in columns],
                )
                counts[table] = counts.get(table, 0) + max(inserted, 0)
    return counts
