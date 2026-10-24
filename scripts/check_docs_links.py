"""Confere os links internos de toda a documentação (.md versionados, exceto docs/archive).

Para cada link relativo: o arquivo precisa existir e, se houver âncora (#secao), a seção precisa
existir no destino (mesma regra de âncora do GitHub). Links http(s) não são verificados.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CODE_BLOCK_RE = re.compile(r"```.*?```", re.S)
LINK_RE = re.compile(r"\]\(([^)\s]+)\)")


def markdown_files() -> list[Path]:
    git = shutil.which("git")  # caminho absoluto: não depende de um "git" qualquer no PATH
    if not git:
        raise SystemExit("git não encontrado")
    listed = subprocess.run([git, "ls-files", "*.md"], cwd=ROOT, capture_output=True, text=True, check=True)  # noqa: S603
    return [ROOT / p for p in listed.stdout.split() if not p.startswith("docs/archive")]


def slug(heading: str) -> str:
    text = heading.strip().lower().replace("`", "")
    text = re.sub(r"[^\w\- ]", "", text)
    return text.replace(" ", "-")


def anchors(path: Path) -> set[str]:
    text = CODE_BLOCK_RE.sub("", path.read_text(encoding="utf-8"))
    seen: dict[str, int] = {}
    found = set()
    for match in re.finditer(r"^#{1,6} (.+)$", text, re.M):
        base = slug(match.group(1))
        count = seen.get(base, 0)
        found.add(base if count == 0 else f"{base}-{count}")  # títulos repetidos ganham sufixo -1, -2...
        seen[base] = count + 1
    return found


def check(files: list[Path]) -> list[str]:
    problems = []
    for file in files:
        text = CODE_BLOCK_RE.sub("", file.read_text(encoding="utf-8"))
        for match in LINK_RE.finditer(text):
            target = match.group(1)
            if re.match(r"^(https?:|mailto:)", target):
                continue
            path_part, _, anchor = target.partition("#")
            dest = (file.parent / path_part).resolve() if path_part else file
            where = file.relative_to(ROOT).as_posix()
            if not dest.exists():
                problems.append(f"{where}: arquivo não existe -> {target}")
            elif anchor and dest.suffix == ".md" and anchor not in anchors(dest):
                problems.append(f"{where}: seção não existe -> {target}")
    return problems


def main() -> int:
    files = markdown_files()
    problems = check(files)
    for problem in problems:
        print(problem)
    if not problems:
        print(f"documentação ok: {len(files)} arquivos, links internos válidos")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
