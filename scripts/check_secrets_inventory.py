"""Compara os segredos usados (config + código + workflows) com o inventário em docs/secrets.md
e avisa sobre itens perto de expirar. Nunca lê valores, só nomes."""

from __future__ import annotations

import re
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.common import secrets  # noqa: E402
from src.config.loader import load_config  # noqa: E402

WARN_DAYS = 7
DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")


def inventory() -> dict[str, str | None]:
    """{nome: data de expiração ou None} a partir da tabela de docs/secrets.md."""
    items: dict[str, str | None] = {}
    for line in (ROOT / "docs" / "secrets.md").read_text(encoding="utf-8").splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 6 or not re.fullmatch(r"`?[A-Z][A-Z0-9_]+`?", cells[0]):
            continue
        expiry = DATE_RE.search(cells[5])
        items[cells[0].strip("`")] = expiry.group(0) if expiry else None
    return items


def used() -> set[str]:
    config = load_config()
    names = set(secrets.required_secrets(config)) | set(secrets.OPTIONAL_SECRETS)
    for niche in config.niches:
        var = secrets.telegram_chat_var(niche)
        if var:
            names.add(var)
    for wf in (ROOT / ".github" / "workflows").glob("*.yml"):
        names |= set(re.findall(r"secrets\.([A-Z][A-Z0-9_]+)", wf.read_text(encoding="utf-8")))
    names.discard("GITHUB_TOKEN")  # fornecido pelo GitHub
    return names


def main() -> int:
    inv = inventory()
    missing = sorted(used() - inv.keys())
    status = 0
    if missing:
        print("segredos sem entrada em docs/secrets.md: " + ", ".join(missing))
        status = 1
    soon = date.today() + timedelta(days=WARN_DAYS)
    for name, expiry in sorted(inv.items()):
        if expiry and date.fromisoformat(expiry) <= soon:
            print(f"ATENÇÃO: {name} expira em {expiry}: rotacione (docs/runbook.md)")
            status = 1
    if status == 0:
        print(f"inventário ok ({len(inv)} itens)")
    return status


if __name__ == "__main__":
    sys.exit(main())
