"""Verifica os workflows do GitHub Actions.

- toda action externa fixada por SHA de 40 caracteres;
- `permissions` declarado no topo do arquivo;
- nada de `pull_request_target`;
- segredo nunca interpolado direto em `run:` (vai por `env:`).
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
SHA_RE = re.compile(r"^[^@\s]+@[0-9a-f]{40}$")


def check_file(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8")
    data = yaml.safe_load(text) or {}
    problems = []
    triggers = data.get(True) or data.get("on") or {}  # PyYAML lê `on:` como True
    if "pull_request_target" in (triggers if isinstance(triggers, (dict, list)) else [triggers]):
        problems.append("usa pull_request_target")
    if "permissions" not in data:
        problems.append("sem bloco permissions no topo")
    for job_name, job in (data.get("jobs") or {}).items():
        uses = job.get("uses")
        if uses and not uses.startswith("./") and not SHA_RE.match(uses):
            problems.append(f"job {job_name}: workflow reutilizável sem SHA ({uses})")
        for step in job.get("steps") or []:
            ref = step.get("uses")
            if ref and not ref.startswith("./") and not ref.startswith("docker://") and not SHA_RE.match(ref):
                problems.append(f"job {job_name}: action sem SHA ({ref})")
            run = step.get("run") or ""
            if "secrets." in run:
                problems.append(f"job {job_name}: segredo interpolado em run (use env)")
    return problems


def main() -> int:
    failed = False
    for path in sorted((ROOT / ".github" / "workflows").glob("*.yml")):
        for problem in check_file(path):
            failed = True
            print(f"{path.name}: {problem}")
    if not failed:
        print("workflows ok")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
