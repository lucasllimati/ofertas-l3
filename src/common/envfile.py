"""Carrega um .env local (só para rodar na sua máquina). Variáveis já definidas têm prioridade."""

from __future__ import annotations

import os
from pathlib import Path


def parse_env(text: str) -> dict[str, str]:
    """`NOME=valor` por linha; ignora comentários, linhas vazias e valores vazios."""
    values: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key, value = key.strip(), value.strip().strip('"').strip("'")
        if key and value:
            values[key] = value
    return values


def load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for key, value in parse_env(path.read_text(encoding="utf-8")).items():
        if key not in os.environ:
            os.environ[key] = value


def set_env_value(path: Path, key: str, value: str) -> bool:
    """Grava `key=value` no .env, trocando a linha existente. Devolve True se já havia um valor."""
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    replaced = False
    for i, raw in enumerate(lines):
        if raw.strip().split("=", 1)[0].strip() == key and not raw.lstrip().startswith("#"):
            replaced = bool(raw.split("=", 1)[1].strip()) if "=" in raw else False
            lines[i] = f"{key}={value}"
            break
    else:
        lines.append(f"{key}={value}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return replaced
