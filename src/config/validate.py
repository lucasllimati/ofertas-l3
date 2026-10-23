"""Valida config/niches.yaml.

python -m src.config.validate                 # só estrutura
python -m src.config.validate --check-secrets # também exige os segredos dos nichos ativos
python -m src.config.validate --write-schema  # regenera config/niches.schema.json
python -m src.config.validate --check-schema  # falha se o schema versionado estiver desatualizado
"""

from __future__ import annotations

import argparse
import json
import sys

from pydantic import ValidationError

from src.common import secrets
from src.config.loader import SCHEMA_PATH, generate_schema, load_config, write_schema


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default=None)
    parser.add_argument("--check-secrets", action="store_true")
    parser.add_argument("--write-schema", action="store_true")
    parser.add_argument("--check-schema", action="store_true")
    args = parser.parse_args(argv)

    try:
        config = load_config(args.config)
    except (ValidationError, ValueError) as exc:
        print(f"config inválida:\n{exc}", file=sys.stderr)
        return 1

    active = [n.id for n in config.niches if n.is_active]
    print(f"config ok: {len(config.niches)} nichos, ativos: {', '.join(active) or 'nenhum'}")

    if args.write_schema:
        write_schema()
        print(f"schema escrito em {SCHEMA_PATH}")

    if args.check_schema:
        current = json.loads(SCHEMA_PATH.read_text(encoding="utf-8")) if SCHEMA_PATH.exists() else None
        if current != generate_schema():
            print("niches.schema.json desatualizado: rode --write-schema", file=sys.stderr)
            return 1

    if args.check_secrets:
        absent = secrets.missing(secrets.required_secrets(config))
        if absent:
            # Só nomes, nunca valores.
            print("segredos ausentes: " + ", ".join(absent), file=sys.stderr)
            return 1
        print("segredos ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
