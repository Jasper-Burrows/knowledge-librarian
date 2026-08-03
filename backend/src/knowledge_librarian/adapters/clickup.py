"""ClickUp task/document source."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime

import httpx

from knowledge_librarian.adapters.http import ConnectorError, JsonConnector
from knowledge_librarian.chunking import content_hash, stable_id
from knowledge_librarian.models import SourceDocument, SourceKind


class ClickUpDocumentSource:
    name = SourceKind.CLICKUP.value

    def __init__(
        self,
        *,
        token: str,
        team_id: str,
        timeout: float = 20,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.team_id = team_id
        self.http = JsonConnector(
            base_url="https://api.clickup.com",
            headers={"Authorization": token},
            timeout=timeout,
            client=client,
        )

    async def documents(self, *, cursor: str | None = None) -> AsyncIterator[SourceDocument]:
        page = int(cursor or 0)
        try:
            while True:
                payload = await self.http.get_json(
                    f"/api/v2/team/{self.team_id}/task",
                    params={"page": page, "include_closed": "true", "subtasks": "true"},
                )
                tasks = payload.get("tasks")
                if not isinstance(tasks, list):
                    raise ConnectorError("ClickUp returned a malformed tasks page")
                for task in tasks:
                    if not isinstance(task, dict) or not task.get("id") or not task.get("name"):
                        continue
                    body = str(task.get("text_content") or task.get("description") or "").strip()
                    if not body:
                        continue
                    task_id = str(task["id"])
                    updated_ms = str(task.get("date_updated") or "0")
                    updated = (
                        datetime.fromtimestamp(int(updated_ms) / 1000, tz=UTC)
                        if updated_ms.isdigit()
                        else datetime.now(UTC)
                    )
                    yield SourceDocument(
                        id=stable_id(self.name, task_id, prefix="doc_"),
                        source=SourceKind.CLICKUP,
                        source_uri=str(task.get("url") or f"https://app.clickup.com/t/{task_id}"),
                        title=str(task["name"]),
                        content=body,
                        content_hash=content_hash(body),
                        updated_at=updated,
                        metadata={"provider_id": task_id, "page": page},
                    )
                if len(tasks) == 0 or payload.get("last_page") is True:
                    break
                page += 1
        finally:
            await self.http.close()
