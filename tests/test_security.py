"""Testes de segurança rodados também pelo security.yml."""

from pathlib import Path

from scripts import check_secrets_inventory, check_workflows
from src.common.util import host_allowed
from src.sources.base import allowed_domains

ROOT = Path(__file__).resolve().parents[1]


def test_allowlist_blocks_open_redirect_tricks():
    domains = allowed_domains()
    assert host_allowed("https://s.shopee.com.br/abc", domains)
    assert host_allowed("https://produto.mercadolivre.com.br/MLB-1", domains)
    for bad in [
        "http://shopee.com.br/x",
        "https://shopee.com.br.evil.com/x",
        "https://evilshopee.com.br/x",
        "https://shopee.com.br@evil.com/",
        "javascript:alert(1)",
        "https://evil.com/?u=https://shopee.com.br",
    ]:
        assert not host_allowed(bad, domains), bad


def test_repo_workflows_pass_checks():
    for path in (ROOT / ".github" / "workflows").glob("*.yml"):
        assert check_workflows.check_file(path) == [], path.name


def test_workflow_checker_flags_problems(tmp_path):
    bad = tmp_path / "bad.yml"
    bad.write_text(
        "on: pull_request_target\n"
        "jobs:\n  x:\n    runs-on: ubuntu-latest\n    steps:\n"
        "      - uses: actions/checkout@v4\n"
        "      - run: echo ${{ secrets.TOKEN }}\n",
        encoding="utf-8",
    )
    reusable = tmp_path / "reusable.yml"
    reusable.write_text(
        "on: push\npermissions: {contents: read}\n"
        "jobs:\n  x:\n    uses: ./.github/workflows/y.yml\n    secrets: inherit\n",
        encoding="utf-8",
    )
    assert any("inherit" in p for p in check_workflows.check_file(reusable))
    problems = check_workflows.check_file(bad)
    assert any("pull_request_target" in p for p in problems)
    assert any("permissions" in p for p in problems)
    assert any("sem SHA" in p for p in problems)
    assert any("interpolado" in p for p in problems)


def test_production_workflow_requires_verify_gate(tmp_path):
    gated = (ROOT / ".github" / "workflows" / "garimpo.yml").read_text(encoding="utf-8")
    ungated = gated.replace("    needs: verify\n", "")
    assert ungated != gated
    path = tmp_path / "garimpo.yml"
    path.write_text(ungated, encoding="utf-8")
    assert any("needs: verify" in p for p in check_workflows.check_file(path))


def test_secrets_inventory_covers_everything_used():
    assert check_secrets_inventory.used() <= check_secrets_inventory.inventory().keys()


def test_gitignore_blocks_secret_files():
    text = (ROOT / ".gitignore").read_text(encoding="utf-8")
    for pattern in [".env", "*.pem", "*.key", "credentials*.json", "out/"]:
        assert pattern in text
