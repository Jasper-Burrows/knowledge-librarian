"""Shared defensive HTTP behavior for optional SaaS connectors."""

from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

import httpx


class ConnectorError(RuntimeError):
    pass


def require_https(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname:
        raise ValueError("Connector URLs must use HTTPS")
    return url.rstrip("/")


class JsonConnector:
    def __init__(
        self,
        *,
        base_url: str,
        headers: dict[str, str] | None = None,
        timeout: float = 20,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.base_url = require_https(base_url)
        self._owned_client = client is None
        self.client = client or httpx.AsyncClient(
            base_url=self.base_url,
            headers=headers,
            timeout=httpx.Timeout(timeout),
            follow_redirects=False,
        )

    async def get_json(self, path: str, *, params: dict[str, Any] | None = None) -> dict[str, Any]:
        try:
            target = path if urlparse(path).scheme else f"{self.base_url}/{path.lstrip('/')}"
            response = await self.client.get(target, params=params)
            response.raise_for_status()
            value = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise ConnectorError("Provider request failed") from exc
        if not isinstance(value, dict):
            raise ConnectorError("Provider returned an unexpected response")
        return value

    async def close(self) -> None:
        if self._owned_client:
            await self.client.aclose()
