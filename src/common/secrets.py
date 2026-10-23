"""Inventário de segredos exigidos pela configuração. Só nomes; valores vêm do ambiente."""

from __future__ import annotations

import os
from collections.abc import Mapping

from src.config.models import AppConfig, Niche

CORE_SECRETS = (
    "DATABASE_URL",
    "TELEGRAM_BOT_TOKEN",
    "TELEGRAM_ADMIN_CHAT_ID",
    "TELEGRAM_ADMIN_USER_IDS",
    "APPROVAL_HMAC_SECRET",
)
SHOPEE_SECRETS = ("SHOPEE_APP_ID", "SHOPEE_APP_SECRET")
CLOUDFLARE_SECRETS = ("CF_API_TOKEN", "CF_ACCOUNT_ID", "CF_KV_NAMESPACE_ID", "CF_D1_DATABASE_ID")
OPTIONAL_SECRETS = ("ANTHROPIC_API_KEY", "REDIRECT_BASE_URL", "BACKUP_PASSPHRASE", *CLOUDFLARE_SECRETS)


class MissingSecretsError(RuntimeError):
    def __init__(self, names: list[str]):
        super().__init__("segredos ausentes: " + ", ".join(names))
        self.names = names


def telegram_chat_var(niche: Niche) -> str | None:
    channel = niche.channels.telegram
    return f"{channel.channel_ref}_CHAT_ID" if channel and channel.enabled else None


def niche_secrets(niche: Niche) -> list[str]:
    names: list[str] = []
    if niche.uses_shopee_api:
        names.extend(SHOPEE_SECRETS)
    chat_var = telegram_chat_var(niche)
    if chat_var:
        names.append(chat_var)
    return names


def required_secrets(config: AppConfig) -> list[str]:
    names = list(CORE_SECRETS)
    for niche in config.niches:
        if niche.is_active:
            names.extend(niche_secrets(niche))
    return sorted(set(names))


def missing(names: list[str], env: Mapping[str, str] | None = None) -> list[str]:
    env = os.environ if env is None else env
    return [n for n in names if not env.get(n, "").strip()]


def require(names: list[str], env: Mapping[str, str] | None = None) -> None:
    absent = missing(names, env)
    if absent:
        raise MissingSecretsError(absent)


def cloudflare_configured(env: Mapping[str, str] | None = None) -> bool:
    return not missing(list(CLOUDFLARE_SECRETS), env)
