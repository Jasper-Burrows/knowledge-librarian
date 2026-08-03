"""Idempotent ingestion orchestration."""

from __future__ import annotations

import uuid
from collections.abc import Sequence

import structlog

from knowledge_librarian.chunking import chunk_document
from knowledge_librarian.database import Database
from knowledge_librarian.models import SourceDocument, SourceKind, SyncJob, SyncStatus, utc_now
from knowledge_librarian.ports import DocumentSource, VectorStore

logger = structlog.get_logger()


class IngestionService:
    def __init__(self, database: Database, vector_store: VectorStore) -> None:
        self.database = database
        self.vector_store = vector_store
        self.jobs: dict[str, SyncJob] = {}

    async def sync(self, source: DocumentSource) -> SyncJob:
        source_name = source.name
        job = SyncJob(
            id=f"sync_{uuid.uuid4().hex}",
            source=self._source_kind(source_name),
            status=SyncStatus.RUNNING,
        )
        self.jobs[job.id] = job
        await self.database.save_sync_job(job)
        seen_ids: list[str] = []
        try:
            async for document in source.documents():
                job.discovered += 1
                seen_ids.append(document.id)
                await self.ingest_documents([document], job=job)
                await self.database.save_sync_job(job)
            stale_ids = await self.database.missing_document_ids(job.source, seen_ids)
            for document_id in stale_ids:
                await self.database.mark_document_deleting(document_id)
                await self.vector_store.delete_document(document_id)
                await self.database.delete_document(document_id)
                job.deleted += 1
            job.status = SyncStatus.COMPLETE
            job.completed_at = utc_now()
            logger.info("source_sync_complete", source=source_name, discovered=job.discovered)
        except Exception as exc:
            job.status = SyncStatus.FAILED
            job.completed_at = utc_now()
            job.error = f"{type(exc).__name__}: source synchronization failed"
            logger.warning("source_sync_failed", source=source_name, error_type=type(exc).__name__)
        await self.database.save_sync_job(job)
        return job

    async def ingest_documents(
        self, documents: Sequence[SourceDocument], *, job: SyncJob | None = None
    ) -> None:
        for document in documents:
            chunks = chunk_document(document)
            action, needs_index = await self.database.upsert_document(
                document,
                chunks,
                index_fingerprint=self.vector_store.fingerprint,
            )
            if job is not None:
                setattr(job, action, getattr(job, action) + 1)
            if needs_index:
                # Provider vector stores must remove older chunk IDs before replacement. The
                # database remains pending until both operations succeed, so a retry repairs any
                # partial failure even when document content is unchanged.
                await self.vector_store.delete_document(document.id)
                await self.vector_store.upsert(chunks)
                await self.database.mark_document_indexed(
                    document.id, self.vector_store.fingerprint
                )

    async def reconcile_index(self) -> None:
        """Repair pending documents and reindex every fingerprint mismatch before serving."""
        candidates = await self.database.documents_needing_index(self.vector_store.fingerprint)
        for document_id, chunks in candidates:
            await self.vector_store.delete_document(document_id)
            await self.vector_store.upsert(chunks)
            await self.database.mark_document_indexed(document_id, self.vector_store.fingerprint)

    def get_job(self, job_id: str) -> SyncJob | None:
        return self.jobs.get(job_id)

    @staticmethod
    def _source_kind(value: str) -> SourceKind:
        return SourceKind(value)
