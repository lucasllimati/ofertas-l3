"""Verifica os workflows do GitHub Actions.

- toda action externa fixada por SHA de 40 caracteres;
- `permissions` declarado no topo do arquivo;
- nada de `pull_request_target`;
- segredo nunca interpolado direto em `run:` (vai por `env:`);
- nada de `secrets: inherit` (cada segredo é passado pelo nome);
- workflow de produção (garimpo.yml) só roda depois do job `verify` (commit verde em ci e security);
- e o agendamento dele só roda com a produção ligada (`vars.GARIMPO_ENABLED`).
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
SHA_RE = re.compile(r"^[^@\s]+@[0-9a-f]{40}$")
PRODUCTION_WORKFLOW = "garimpo.yml"


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
        if job.get("secrets") == "inherit":
            problems.append(f"job {job_name}: secrets: inherit repassa todos os segredos")
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
    if path.name == PRODUCTION_WORKFLOW:
        jobs = data.get("jobs") or {}
        if "verify" not in jobs:
            problems.append("workflow de produção sem o job verify (trava de ci/security)")
        elif "vars.GARIMPO_ENABLED" not in str(jobs["verify"].get("if", "")):
            problems.append("job verify sem a chave GARIMPO_ENABLED: agendamento rodaria sem a produção configurada")
        for job_name, job in jobs.items():
            needs = job.get("needs") or []
            needs = [needs] if isinstance(needs, str) else needs
            if job_name != "verify" and "verify" not in needs:
                problems.append(f"job {job_name}: roda em produção sem needs: verify")
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
