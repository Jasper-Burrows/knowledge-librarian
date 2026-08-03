from __future__ import annotations

import json

import httpx
import pytest

from knowledge_librarian.adapters.clickup import ClickUpDocumentSource
from knowledge_librarian.adapters.factory import SourceNotConfiguredError, build_document_source
from knowledge_librarian.adapters.http import ConnectorError, JsonConnector, require_https
from knowledge_librarian.adapters.hubspot import HubSpotDocumentSource
from knowledge_librarian.adapters.microsoft_graph import MicrosoftGraphEmailSource, html_to_text
from knowledge_librarian.adapters.stonly import StonlyDocumentSource
from knowledge_librarian.config import Settings
from knowledge_librarian.database import Database
from knowledge_librarian.embeddings import DeterministicEmbeddingProvider
from knowledge_librarian.ingestion import IngestionService
from knowledge_librarian.models import SourceKind, SyncStatus
from knowledge_librarian.retrieval import LocalVectorStore


def json_response(payload: dict, status: int = 200) -> httpx.Response:
    return httpx.Response(
        status, content=json.dumps(payload), headers={"content-type": "application/json"}
    )


def test_connector_origin_validation() -> None:
    assert require_https("https://example.com/") == "https://example.com"
    with pytest.raises(ValueError, match="HTTPS"):
        require_https("http://127.0.0.1")


@pytest.mark.asyncio
async def test_json_connector_sanitizes_provider_errors() -> None:
    transport = httpx.MockTransport(lambda request: httpx.Response(500, request=request))
    client = httpx.AsyncClient(transport=transport, base_url="https://example.com")
    connector = JsonConnector(base_url="https://example.com", client=client)
    with pytest.raises(ConnectorError, match="Provider request failed"):
        await connector.get_json("/failure")
    await client.aclose()


@pytest.mark.asyncio
async def test_clickup_pagination_contract() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        page = request.url.params.get("page")
        if page == "0":
            return json_response(
                {
                    "tasks": [
                        {
                            "id": "task-1",
                            "name": "Incident guide",
                            "text_content": "Acknowledge alerts within ten minutes.",
                            "date_updated": "1767225600000",
                        }
                    ]
                }
            )
        return json_response({"tasks": [], "last_page": True})

    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="https://api.clickup.com"
    )
    source = ClickUpDocumentSource(token="test", team_id="team", client=client)
    documents = [item async for item in source.documents()]
    assert len(documents) == 1
    assert documents[0].source is SourceKind.CLICKUP
    assert documents[0].title == "Incident guide"
    await client.aclose()


@pytest.mark.asyncio
async def test_hubspot_cursor_contract() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return json_response(
                {
                    "results": [
                        {
                            "id": "note-1",
                            "properties": {
                                "hs_note_body": "<p>Safe note body</p>",
                                "hs_lastmodifieddate": "2026-01-01T00:00:00Z",
                            },
                        }
                    ],
                    "paging": {"next": {"after": "next"}},
                }
            )
        assert request.url.params["after"] == "next"
        return json_response({"results": []})

    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="https://api.hubapi.com"
    )
    source = HubSpotDocumentSource(access_token="test", client=client)
    documents = [item async for item in source.documents()]
    assert documents[0].content == "Safe note body"
    assert calls == 2
    await client.aclose()


@pytest.mark.asyncio
async def test_stonly_cursor_contract() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if "cursor" not in request.url.params:
            return json_response(
                {
                    "items": [{"id": "guide-1", "title": "Guide", "body": "Useful body"}],
                    "next_cursor": "two",
                }
            )
        return json_response({"items": []})

    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="https://stonly.test"
    )
    source = StonlyDocumentSource(base_url="https://stonly.test", api_token="test", client=client)
    documents = [item async for item in source.documents()]
    assert documents[0].source_uri == "stonly://guide/guide-1"
    await client.aclose()


@pytest.mark.asyncio
async def test_malformed_clickup_page_fails_without_reconciling_deletions(settings) -> None:
    responses = iter(
        [
            {"tasks": [{"id": "task-1", "name": "Guide", "text_content": "Keep me."}]},
            {"tasks": [], "last_page": True},
        ]
    )
    first_client = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: json_response(next(responses))),
        base_url="https://api.clickup.com",
    )
    database = Database(settings.database_path)
    await database.initialize()
    ingestion = IngestionService(
        database, LocalVectorStore(database, DeterministicEmbeddingProvider())
    )
    first = await ingestion.sync(
        ClickUpDocumentSource(token="test", team_id="team", client=first_client)
    )
    assert first.status is SyncStatus.COMPLETE
    await first_client.aclose()

    malformed_client = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: json_response({"tasks": {}})),
        base_url="https://api.clickup.com",
    )
    failed = await ingestion.sync(
        ClickUpDocumentSource(token="test", team_id="team", client=malformed_client)
    )
    assert failed.status is SyncStatus.FAILED
    assert [item.title for item in await database.list_documents()] == ["Guide"]
    await malformed_client.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [{"items": {}}, {"data": "bad"}, {}])
async def test_malformed_stonly_page_fails_without_reconciling_deletions(
    settings, make_document, payload
) -> None:
    database = Database(settings.database_path)
    await database.initialize()
    ingestion = IngestionService(
        database, LocalVectorStore(database, DeterministicEmbeddingProvider())
    )

    class ExistingStonlySource:
        name = SourceKind.STONLY.value

        async def documents(self, *, cursor=None):
            del cursor
            yield make_document(
                title="Existing guide",
                source=SourceKind.STONLY,
                source_uri="stonly://guide/existing",
            )

    assert (await ingestion.sync(ExistingStonlySource())).status is SyncStatus.COMPLETE
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: json_response(payload)),
        base_url="https://stonly.test",
    )
    failed = await ingestion.sync(
        StonlyDocumentSource(base_url="https://stonly.test", api_token="test", client=client)
    )
    assert failed.status is SyncStatus.FAILED
    assert [item.title for item in await database.list_documents()] == ["Existing guide"]
    await client.aclose()


@pytest.mark.asyncio
async def test_microsoft_graph_oauth_and_pagination_contract() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        if "login.microsoftonline.com" in str(request.url):
            return json_response({"access_token": "token"})
        if "skiptoken" not in str(request.url):
            return json_response(
                {
                    "value": [
                        {
                            "id": "mail-1",
                            "subject": "Policy",
                            "body": {"content": "<p>Approved &amp; safe</p>"},
                            "lastModifiedDateTime": "2026-01-01T00:00:00Z",
                        }
                    ],
                    "@odata.nextLink": "https://graph.microsoft.com/v1.0/users/demo/messages?skiptoken=2",
                }
            )
        return json_response({"value": []})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    source = MicrosoftGraphEmailSource(
        tenant_id="tenant",
        client_id="client",
        client_secret="secret",
        mailbox="demo@example.test",
        client=client,
    )
    documents = [item async for item in source.documents()]
    assert documents[0].content == "Approved & safe"
    assert len(calls) == 3
    assert html_to_text("<p>Hello&nbsp;world</p>") == "Hello world"
    await client.aclose()


def test_source_factory_requires_explicit_enablement(tmp_path) -> None:
    settings = Settings(database_path=tmp_path / "db.sqlite")
    assert build_document_source(settings, "demo").name == "demo"
    with pytest.raises(SourceNotConfiguredError, match="disabled"):
        build_document_source(settings, "clickup")
