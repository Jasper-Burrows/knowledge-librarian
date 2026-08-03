"""Stonly guide source behind a configurable HTTPS API origin."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime

import httpx

from knowledge_librarian.adapters.http import ConnectorError, JsonConnector
from knowledge_librarian.chunking import content_hash, stable_id
from knowledge_librarian.models import SourceDocument, SourceKind


class StonlyDocumentSource:
    name = SourceKind.STONLY.value

    def __init__(
        self,
        *,
        base_url: str,
        api_token: str,
        timeout: float = 20,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.http = JsonConnector(
            base_url=base_url,
            headers={"Authorization": f"Bearer {api_token}"},
            timeout=timeout,
            client=client,
        )

    async def documents(self, *, cursor: str | None = None) -> AsyncIterator[SourceDocument]:
        page = cursor
        try:
            while True:
                payload = await self.http.get_json(
                    "/v1/guides", params={"cursor": page} if page else None
                )
                if "items" in payload:
                    items = payload["items"]
                elif "data" in payload:
                    items = payload["data"]
                else:
                    raise ConnectorError("Stonly returned a page without items")
                if not isinstance(items, list):
                    raise ConnectorError("Stonly returned a malformed items page")
                for guide in items:
                    if not isinstance(guide, dict) or not guide.get("id"):
                        continue
                    body = str(guide.get("content") or guide.get("body") or "").strip()
                    title = str(guide.get("title") or "Untitled guide")
                    if not body:
                        continue
                    guide_id = str(guide["id"])
                    raw_updated = str(guide.get("updated_at") or guide.get("updatedAt") or "")
                    try:
                        updated = datetime.fromisoformat(raw_updated.replace("Z", "+00:00"))
                    except ValueError:
                        updated = datetime.now(UTC)
                    yield SourceDocument(
                        id=stable_id(self.name, guide_id, prefix="doc_"),
                        source=SourceKind.STONLY,
                        source_uri=str(guide.get("url") or f"stonly://guide/{guide_id}"),
                        title=title,
                        content=body,
                        content_hash=content_hash(body),
                        updated_at=updated,
                        metadata={"provider_id": guide_id},
                    )
                next_cursor = payload.get("next_cursor") or payload.get("nextCursor")
                if not next_cursor:
                    break
                page = str(next_cursor)
        finally:
            await self.http.close()
