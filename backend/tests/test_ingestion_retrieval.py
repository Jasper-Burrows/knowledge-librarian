from __future__ import annotations

import aiosqlite
import pytest

from conftest import StaticSource
from knowledge_librarian.database import Database
from knowledge_librarian.embeddings import DeterministicEmbeddingProvider
from knowledge_librarian.ingestion import IngestionService
from knowledge_librarian.models import SourceKind, SyncStatus
from knowledge_librarian.retrieval import HybridRetriever, LocalVectorStore


class FailingOnceVectorStore:
    def __init__(self, inner: LocalVectorStore) -> None:
        self.inner = inner
        self.fail_upsert = True
        self.fail_delete = False
        self.upsert_calls = 0

    @property
    def fingerprint(self) -> str:
        return self.inner.fingerprint

    async def upsert(self, chunks) -> None:
        self.upsert_calls += 1
        if self.fail_upsert:
            self.fail_upsert = False
            raise RuntimeError("synthetic vector failure")
        await self.inner.upsert(chunks)

    async def delete_document(self, document_id: str) -> None:
        if self.fail_delete:
            self.fail_delete = False
            raise RuntimeError("synthetic delete failure")
        await self.inner.delete_document(document_id)

    async def search(self, query: str, *, limit: int):
        return await self.inner.search(query, limit=limit)


class WideEmbeddingProvider:
    fingerprint = "openai:text-embedding-3-small:dimensions=1536"

    async def embed(self, texts):
        return [[1.0] * 1536 for _ in texts]


@pytest.mark.asyncio
async def test_database_initialization_migrates_pre_fingerprint_schema(settings) -> None:
    async with aiosqlite.connect(settings.database_path) as connection:
        await connection.execute(
            """CREATE TABLE documents (
                id TEXT PRIMARY KEY, source TEXT NOT NULL, source_uri TEXT NOT NULL,
                title TEXT NOT NULL, content TEXT NOT NULL, content_hash TEXT NOT NULL,
                updated_at TEXT NOT NULL, metadata_json TEXT NOT NULL
            )"""
        )
        await connection.commit()
    database = Database(settings.database_path)
    await database.initialize()
    async with database.connect() as connection:
        columns = await (await connection.execute("PRAGMA table_info(documents)")).fetchall()
    names = {str(row["name"]) for row in columns}
    assert {"index_status", "index_fingerprint"}.issubset(names)


@pytest.mark.asyncio
async def test_incremental_sync_persists_status_and_reconciles_deletions(
    settings, make_document
) -> None:
    database = Database(settings.database_path)
    await database.initialize()
    vectors = LocalVectorStore(database, DeterministicEmbeddingProvider())
    ingestion = IngestionService(database, vectors)
    first_doc = make_document(title="First", source_uri="kb://first")
    second_doc = make_document(title="Second", source_uri="kb://second")

    first_job = await ingestion.sync(StaticSource([first_doc, second_doc]))
    assert first_job.status is SyncStatus.COMPLETE
    assert first_job.created == 2
    assert first_job.deleted == 0
    assert (await database.get_sync_job(first_job.id)) == first_job

    second_job = await ingestion.sync(StaticSource([first_doc]))
    assert second_job.unchanged == 1
    assert second_job.deleted == 1
    documents = await database.list_documents()
    assert [document.id for document in documents] == [first_doc.id]
    assert len(await database.list_sync_jobs()) == 2


@pytest.mark.asyncio
async def test_failed_sync_preserves_previous_documents(settings, make_document) -> None:
    database = Database(settings.database_path)
    await database.initialize()
    vectors = LocalVectorStore(database, DeterministicEmbeddingProvider())
    ingestion = IngestionService(database, vectors)
    document = make_document()
    await ingestion.sync(StaticSource([document]))
    failed = await ingestion.sync(StaticSource([], fail=True))
    assert failed.status is SyncStatus.FAILED
    assert failed.error == "RuntimeError: source synchronization failed"
    assert [item.id for item in await database.list_documents()] == [document.id]


@pytest.mark.asyncio
async def test_hybrid_retrieval_returns_relevant_content(settings, make_document) -> None:
    database = Database(settings.database_path)
    await database.initialize()
    vectors = LocalVectorStore(database, DeterministicEmbeddingProvider())
    ingestion = IngestionService(database, vectors)
    await ingestion.sync(
        StaticSource(
            [
                make_document(
                    title="Incident",
                    content="Severity-one incidents must be acknowledged within ten minutes.",
                    source_uri="kb://incident",
                ),
                make_document(
                    title="Meals",
                    content="The domestic meal allowance is eighty-five dollars per day.",
                    source_uri="kb://meals",
                ),
            ]
        )
    )
    retriever = HybridRetriever(database, vectors)
    results = await retriever.retrieve("severity incident acknowledgement", limit=3)
    assert results
    assert results[0].chunk.title == "Incident"
    assert results[0].lexical_rank == 1

    assert await retriever.retrieve("quantum entanglement", limit=3) == []


@pytest.mark.asyncio
async def test_feedback_is_validated_and_persisted(settings) -> None:
    database = Database(settings.database_path)
    await database.initialize()
    await database.record_feedback("response", "helpful", "a" * 64)
    assert await database.feedback_count() == 1
    with pytest.raises(ValueError, match="invalid feedback"):
        await database.record_feedback("response", "unknown", "a" * 64)
    assert await database.healthcheck()


@pytest.mark.asyncio
async def test_source_counts_include_expected_kind(settings, make_document) -> None:
    database = Database(settings.database_path)
    await database.initialize()
    vectors = LocalVectorStore(database, DeterministicEmbeddingProvider())
    ingestion = IngestionService(database, vectors)
    await ingestion.sync(StaticSource([make_document()]))
    assert await database.document_count_by_source() == {SourceKind.DEMO: 1}


@pytest.mark.asyncio
async def test_failed_vector_write_is_repaired_when_unchanged_document_retries(
    settings, make_document
) -> None:
    database = Database(settings.database_path)
    await database.initialize()
    wrapped = FailingOnceVectorStore(LocalVectorStore(database, DeterministicEmbeddingProvider()))
    ingestion = IngestionService(database, wrapped)
    document = make_document()

    failed = await ingestion.sync(StaticSource([document]))
    assert failed.status is SyncStatus.FAILED
    assert await database.document_index_state(document.id) == (
        "pending",
        wrapped.fingerprint,
    )
    assert await database.all_embedded_chunks() == []

    repaired = await ingestion.sync(StaticSource([document]))
    assert repaired.status is SyncStatus.COMPLETE
    assert repaired.unchanged == 1
    assert wrapped.upsert_calls == 2
    assert await database.document_index_state(document.id) == (
        "indexed",
        wrapped.fingerprint,
    )
    assert await database.all_embedded_chunks()


@pytest.mark.asyncio
async def test_embedding_fingerprint_change_forces_offline_to_live_reindex(
    settings, make_document
) -> None:
    database = Database(settings.database_path)
    await database.initialize()
    document = make_document()
    offline = LocalVectorStore(database, DeterministicEmbeddingProvider())
    await IngestionService(database, offline).sync(StaticSource([document]))
    assert len((await database.all_embedded_chunks())[0].embedding or []) == 256

    live = LocalVectorStore(database, WideEmbeddingProvider())  # type: ignore[arg-type]
    await IngestionService(database, live).reconcile_index()
    chunks = await database.all_embedded_chunks()
    assert len(chunks[0].embedding or []) == 1536
    assert await database.document_index_state(document.id) == ("indexed", live.fingerprint)


@pytest.mark.asyncio
async def test_failed_vector_deletion_is_reconciled_on_retry(settings, make_document) -> None:
    database = Database(settings.database_path)
    await database.initialize()
    inner = LocalVectorStore(database, DeterministicEmbeddingProvider())
    document = make_document()
    await IngestionService(database, inner).sync(StaticSource([document]))

    wrapped = FailingOnceVectorStore(inner)
    wrapped.fail_upsert = False
    wrapped.fail_delete = True
    ingestion = IngestionService(database, wrapped)
    failed = await ingestion.sync(StaticSource([]))
    assert failed.status is SyncStatus.FAILED
    assert (await database.document_index_state(document.id) or (None,))[0] == "deleting"
    assert await database.lexical_search("useful policy", limit=3) == []

    repaired = await ingestion.sync(StaticSource([]))
    assert repaired.status is SyncStatus.COMPLETE
    assert repaired.deleted == 1
    assert await database.document_index_state(document.id) is None
