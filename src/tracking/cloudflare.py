"""Integração com o Worker de redirecionamento via API REST da Cloudflare.

- KV: content_id -> destino (o Worker só redireciona para o que está aqui e na allowlist).
- D1: tabela `clicks` gravada pelo Worker; o pipeline copia para click_event.
"""

from __future__ import annotations

import json
from typing import Any

import httpx

API = "https://api.cloudflare.com/client/v4"
KV_TTL_SECONDS = 90 * 24 * 3600


class CloudflareError(RuntimeError):
    pass


class CloudflareApi:
    def __init__(self, token: str, account_id: str, http: httpx.Client | None = None):
        self._token = token
        self.account_id = account_id
        self.http = http or httpx.Client(timeout=30)

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._token}"}

    def kv_put(self, namespace_id: str, key: str, value: str, ttl: int = KV_TTL_SECONDS) -> None:
        url = f"{API}/accounts/{self.account_id}/storage/kv/namespaces/{namespace_id}/values/{key}"
        resp = self.http.put(url, params={"expiration_ttl": ttl}, content=value.encode(), headers=self._headers())
        if resp.status_code >= 300:
            raise CloudflareError(f"KV put HTTP {resp.status_code}")

    def d1_query(self, database_id: str, sql: str, params: list[Any]) -> list[dict[str, Any]]:
        url = f"{API}/accounts/{self.account_id}/d1/database/{database_id}/query"
        resp = self.http.post(url, json={"sql": sql, "params": params}, headers=self._headers())
        body = resp.json()
        if resp.status_code >= 300 or not body.get("success"):
            raise CloudflareError(f"D1 query HTTP {resp.status_code}")
        result = body.get("result") or [{}]
        return result[0].get("results") or []


class RedirectRegistry:
    def __init__(self, api: CloudflareApi, namespace_id: str, base_url: str):
        self.api = api
        self.namespace_id = namespace_id
        self.base_url = base_url.rstrip("/")

    def register(self, content_id: str, url: str, niche_id: str, channel_code: str) -> str:
        value = json.dumps({"url": url, "niche": niche_id, "channel": channel_code})
        self.api.kv_put(self.namespace_id, f"go:{content_id}", value)
        return f"{self.base_url}/go/{niche_id}/{channel_code}/{content_id}"


class D1ClickSource:
    def __init__(self, api: CloudflareApi, database_id: str):
        self.api = api
        self.database_id = database_id

    def fetch(self, after_id: int, limit: int = 5000) -> list[dict[str, Any]]:
        return self.api.d1_query(
            self.database_id,
            "SELECT id, ts, niche, channel, content_id, country FROM clicks WHERE id > ? ORDER BY id LIMIT ?",
            [after_id, limit],
        )

    def purge(self, up_to_id: int, before_ts: str) -> None:
        self.api.d1_query(self.database_id, "DELETE FROM clicks WHERE id <= ? AND ts < ?", [up_to_id, before_ts])
