"""Restaura um backup já descriptografado (garimpo-AAAA-MM-DD.jsonl.gz).

    gpg --decrypt garimpo-2026-10-25.jsonl.gz.gpg > garimpo-2026-10-25.jsonl.gz
    DATABASE_URL=<url do DONO do banco> uv run python scripts/restore_backup.py garimpo-2026-10-25.jsonl.gz

Não sobrescreve linhas existentes. Rode antes `--steps migrate` num banco novo.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.backup import restore_backup  # noqa: E402
from src.common.db import Database  # noqa: E402


def main() -> int:
    if len(sys.argv) != 2 or not os.environ.get("DATABASE_URL"):
        print(__doc__, file=sys.stderr)
        return 2
    db = Database(os.environ["DATABASE_URL"])
    db.migrate()
    counts = restore_backup(db, Path(sys.argv[1]))
    for table, n in counts.items():
        print(f"{table}: {n} linhas restauradas")
    return 0


if __name__ == "__main__":
    sys.exit(main())
