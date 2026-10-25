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


def agent_config_problems(config) -> list[str]:
    """Confere os arquivos editados à mão pelos agentes: calendário, cupons e finanças."""
    from src.agents.coupons import COUPONS_PATH, parse_coupons
    from src.agents.finance import load_finance
    from src.agents.seasonal import load_calendar

    problems: list[str] = []
    known = {n.id for n in config.niches}
    try:
        calendar = load_calendar()
        for event in calendar.events:
            unknown = (set(event.niches) | set(event.extra_keywords)) - known
            if unknown:
                problems.append(f"calendar.yaml: evento {event.id} cita nichos inexistentes {sorted(unknown)}")
    except (ValidationError, ValueError) as exc:
        problems.append(f"calendar.yaml: {exc}")
    if COUPONS_PATH.exists():
        coupons, errors = parse_coupons(COUPONS_PATH.read_text(encoding="utf-8-sig"), config.defaults.timezone)
        problems += [f"coupons.csv {e}" for e in errors]
        for c in coupons:
            if set(c.niches) - known:
                problems.append(f"coupons.csv: cupom {c.code} cita nichos inexistentes")
    try:
        load_finance()
    except (ValidationError, ValueError, OSError) as exc:
        problems.append(f"finance.yaml: {exc}")
    return problems


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

    problems = agent_config_problems(config)
    if problems:
        print("configuração dos agentes inválida:\n" + "\n".join(f"- {p}" for p in problems), file=sys.stderr)
        return 1
    print("agentes ok: calendar.yaml, coupons.csv e finance.yaml")

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
