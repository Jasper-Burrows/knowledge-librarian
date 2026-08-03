from __future__ import annotations

from typing import Any, cast

import pytest

from knowledge_librarian.adapters.pinecone import PineconeVectorStore
from knowledge_librarian.adapters.slack import SlackApplicationAdapter, SlackConfigurationError
from knowledge_librarian.chunking import chunk_document
from knowledge_librarian.models import ChatEvent, ChatRequest
from knowledge_librarian.service import LibrarianService


def synthetic_slack_token(kind: str) -> str:
    return "-".join((kind, "synthetic", "test"))


class FakeEmbeddings:
    fingerprint = "fake:dimensions=2"

    async def embed(self, texts):
        return [[float(index), 1.0] for index, _ in enumerate(texts, 1)]


class FakeIndex:
    def __init__(self, match: dict[str, Any]) -> None:
        self.match = match
        self.upserts: list[dict[str, Any]] = []
        self.deletes: list[dict[str, Any]] = []

    def upsert(self, **kwargs) -> None:
        self.upserts.append(kwargs)

    def delete(self, **kwargs) -> None:
        self.deletes.append(kwargs)

    def query(self, **kwargs) -> dict[str, Any]:
        return {"matches": [self.match], "request": kwargs}


@pytest.mark.asyncio
async def test_pinecone_adapter_runs_sync_sdk_work_off_loop(make_document) -> None:
    chunk = chunk_document(make_document())[0]
    match = {
        "id": chunk.id,
        "score": 0.9,
        "metadata": {
            "document_id": chunk.document_id,
            "source": chunk.source.value,
            "source_uri": chunk.source_uri,
            "title": chunk.title,
            "text": chunk.text,
            "ordinal": chunk.ordinal,
            "content_hash": chunk.content_hash,
            "token_estimate": chunk.token_estimate,
        },
    }
    store = PineconeVectorStore.__new__(PineconeVectorStore)
    store.index = FakeIndex(match)
    store.index_name = "test-index"
    store.embeddings = FakeEmbeddings()
    store.namespace = "test"

    assert "index=test-index" in store.fingerprint

    await store.upsert([chunk])
    assert store.index.upserts[0]["namespace"] == "test"
    assert store.index.upserts[0]["vectors"][0]["metadata"]["title"] == chunk.title
    await store.delete_document(chunk.document_id)
    assert store.index.deletes[0]["filter"] == {"document_id": {"$eq": chunk.document_id}}
    results = await store.search("policy", limit=2)
    assert results[0].chunk == chunk
    assert results[0].semantic_rank == 1


class FakeService:
    def __init__(self) -> None:
        self.requests: list[ChatRequest] = []

    async def events(self, request: ChatRequest):
        self.requests.append(request)
        yield ChatEvent(type="delta", data={"text": "A" * 250 + " [1]"})
        yield ChatEvent(
            type="citation",
            data={
                "id": "1",
                "title": "Synthetic guide",
                "document_id": "doc",
                "chunk_id": "chunk",
                "source": "demo",
                "source_uri": "kb://guide",
                "excerpt": "Excerpt",
            },
        )
        yield ChatEvent(type="done", data={"grounded": True})


class FakeSlackClient:
    def __init__(self) -> None:
        self.messages: list[dict[str, Any]] = []
        self.updates: list[dict[str, Any]] = []
        self.ephemeral: list[dict[str, Any]] = []

    async def chat_postMessage(self, **kwargs) -> dict[str, str]:
        self.messages.append(kwargs)
        return {"ts": f"response-{len(self.messages)}"}

    async def chat_update(self, **kwargs) -> None:
        self.updates.append(kwargs)

    async def chat_postEphemeral(self, **kwargs) -> None:
        self.ephemeral.append(kwargs)


@pytest.mark.asyncio
async def test_slack_streams_updates_keeps_thread_history_and_persists_feedback() -> None:
    service = FakeService()
    feedback: list[tuple[str, str, str]] = []

    async def sink(response_id: str, rating: str, actor_hash: str) -> None:
        feedback.append((response_id, rating, actor_hash))

    times = iter([0.0, 2.0, 3.0, 5.0, 6.0, 8.0])
    adapter = SlackApplicationAdapter(
        service=cast(LibrarianService, service),
        bot_token=synthetic_slack_token("xoxb"),
        app_token=synthetic_slack_token("xapp"),
        signing_secret="synthetic-signing-secret",
        feedback_sink=sink,
        clock=lambda: next(times),
    )
    client = FakeSlackClient()
    event = {"text": "<@BOT123> What is the policy?", "channel": "C1", "ts": "T1"}
    await adapter.handle_mention(event, client)
    await adapter.handle_mention(event, client)
    await adapter.handle_mention({**event, "thread_ts": "T2"}, client)
    assert len(client.updates) == 6  # one interim and one final update per answer
    assert client.updates[0]["text"].endswith(" ▌")
    assert "*Sources*" in client.updates[1]["text"]
    assert service.requests[0].history == []
    assert len(service.requests[1].history) == 2
    assert service.requests[2].history == []

    body = {
        "actions": [{"action_id": "librarian_helpful", "value": "response-1"}],
        "channel": {"id": "C1"},
        "user": {"id": "U1"},
    }
    await adapter.handle_feedback(body, client)
    assert feedback[0][:2] == ("response-1", "helpful")
    assert len(feedback[0][2]) == 64
    assert client.ephemeral
    assert adapter.build() is not None


@pytest.mark.asyncio
async def test_slack_empty_mention_and_token_validation() -> None:
    service = cast(LibrarianService, FakeService())
    client = FakeSlackClient()
    adapter = SlackApplicationAdapter(
        service=service,
        bot_token=synthetic_slack_token("xoxb"),
        app_token=synthetic_slack_token("xapp"),
        signing_secret="synthetic-signing-secret",
    )
    await adapter.handle_mention({"text": "<@BOT123>", "channel": "C1", "ts": "T1"}, client)
    assert client.messages[0]["text"].startswith("Ask me")

    with pytest.raises(SlackConfigurationError, match="bot token"):
        SlackApplicationAdapter(
            service=service,
            bot_token="bad",
            app_token=synthetic_slack_token("xapp"),
            signing_secret="synthetic-signing-secret",
        )
    with pytest.raises(SlackConfigurationError, match="Socket Mode"):
        SlackApplicationAdapter(
            service=service,
            bot_token=synthetic_slack_token("xoxb"),
            app_token="bad",
            signing_secret="synthetic-signing-secret",
        )
    with pytest.raises(SlackConfigurationError, match="signing secret"):
        SlackApplicationAdapter(
            service=service,
            bot_token=synthetic_slack_token("xoxb"),
            app_token=synthetic_slack_token("xapp"),
            signing_secret="short",
        )
