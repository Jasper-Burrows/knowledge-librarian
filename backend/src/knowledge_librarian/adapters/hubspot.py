"""HubSpot notes source using the CRM v3 API."""

from __future__ import annotations

import re
from collections.abc import AsyncIterator
from datetime import UTC, datetime

import httpx

from knowledge_librarian.adapters.http import JsonConnector
from knowledge_librarian.chunking import content_hash, stable_id
from knowledge_librarian.models import SourceDocument, SourceKind


def _plain_text(value: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", value)).strip()


class HubSpotDocumentSource:
    name = SourceKind.HUBSPOT.value

    def __init__(
        self,
        *,
        access_token: str,
        timeout: float = 20,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.http = JsonConnector(
            base_url="https://api.hubapi.com",
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=timeout,
            client=client,
        )

    async def documents(self, *, cursor: str | None = None) -> AsyncIterator[SourceDocument]:
        after = cursor
        try:
            while True:
                params = {
                    "limit": 100,
                    "properties": "hs_note_body,hs_timestamp,hs_createdate,hs_lastmodifieddate",
                }
                if after:
                    params["after"] = after
                payload = await self.http.get_json("/crm/v3/objects/notes", params=params)
                for note in payload.get("results", []):
                    if not isinstance(note, dict) or not note.get("id"):
                        continue
                    properties = note.get("properties") or {}
                    body = _plain_text(str(properties.get("hs_note_body") or ""))
                    if not body:
                        continue
                    note_id = str(note["id"])
                    stamp = properties.get("hs_lastmodifieddate") or note.get("updatedAt")
                    try:
                        updated = datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
                    except ValueError:
                        updated = datetime.now(UTC)
                    yield SourceDocument(
                        id=stable_id(self.name, note_id, prefix="doc_"),
                        source=SourceKind.HUBSPOT,
                        source_uri=f"https://app.hubspot.com/contacts/notes/{note_id}",
                        title=f"HubSpot note {note_id}",
                        content=body,
                        content_hash=content_hash(body),
                        updated_at=updated,
                        metadata={"provider_id": note_id},
                    )
                paging = payload.get("paging") or {}
                next_page = (paging.get("next") or {}).get("after")
                if not next_page:
                    break
                after = str(next_page)
        finally:
            await self.http.close()
