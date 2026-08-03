"""Microsoft Graph email source using OAuth client credentials."""

from __future__ import annotations

import html
import re
from collections.abc import AsyncIterator
from datetime import UTC, datetime

import httpx

from knowledge_librarian.adapters.http import ConnectorError, JsonConnector
from knowledge_librarian.chunking import content_hash, stable_id
from knowledge_librarian.models import SourceDocument, SourceKind


def html_to_text(value: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", value))).strip()


class MicrosoftGraphEmailSource:
    name = SourceKind.MICROSOFT_GRAPH.value

    def __init__(
        self,
        *,
        tenant_id: str,
        client_id: str,
        client_secret: str,
        mailbox: str,
        timeout: float = 20,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.tenant_id = tenant_id
        self.client_id = client_id
        self.client_secret = client_secret
        self.mailbox = mailbox
        self.timeout = timeout
        self.client = client

    async def _access_token(self, client: httpx.AsyncClient) -> str:
        try:
            response = await client.post(
                f"https://login.microsoftonline.com/{self.tenant_id}/oauth2/v2.0/token",
                data={
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                    "scope": "https://graph.microsoft.com/.default",
                    "grant_type": "client_credentials",
                },
            )
            response.raise_for_status()
            token = response.json().get("access_token")
        except (httpx.HTTPError, ValueError) as exc:
            raise ConnectorError("Microsoft authentication failed") from exc
        if not isinstance(token, str) or not token:
            raise ConnectorError("Microsoft authentication failed")
        return token

    async def documents(self, *, cursor: str | None = None) -> AsyncIterator[SourceDocument]:
        owned = self.client is None
        client = self.client or httpx.AsyncClient(
            timeout=httpx.Timeout(self.timeout), follow_redirects=False
        )
        try:
            token = await self._access_token(client)
            connector = JsonConnector(
                base_url="https://graph.microsoft.com",
                headers={"Authorization": f"Bearer {token}"},
                timeout=self.timeout,
                client=client,
            )
            path = cursor or f"/v1.0/users/{self.mailbox}/messages"
            params = (
                {"$top": 50, "$select": "id,subject,body,webLink,lastModifiedDateTime"}
                if cursor is None
                else None
            )
            while path:
                payload = await connector.get_json(path, params=params)
                params = None
                for message in payload.get("value", []):
                    if not isinstance(message, dict) or not message.get("id"):
                        continue
                    body_value = str((message.get("body") or {}).get("content") or "")
                    body = html_to_text(body_value)
                    if not body:
                        continue
                    message_id = str(message["id"])
                    raw_updated = str(message.get("lastModifiedDateTime") or "")
                    try:
                        updated = datetime.fromisoformat(raw_updated.replace("Z", "+00:00"))
                    except ValueError:
                        updated = datetime.now(UTC)
                    yield SourceDocument(
                        id=stable_id(self.name, self.mailbox, message_id, prefix="doc_"),
                        source=SourceKind.MICROSOFT_GRAPH,
                        source_uri=str(message.get("webLink") or f"msgraph://message/{message_id}"),
                        title=str(message.get("subject") or "Email message"),
                        content=body,
                        content_hash=content_hash(body),
                        updated_at=updated,
                        metadata={"provider_id": message_id},
                    )
                next_link = payload.get("@odata.nextLink")
                if not next_link:
                    break
                # Only follow pagination on the fixed Graph origin.
                path = str(next_link).removeprefix("https://graph.microsoft.com")
                if not path.startswith("/v1.0/"):
                    raise ConnectorError("Microsoft pagination URL was rejected")
        finally:
            if owned:
                await client.aclose()
