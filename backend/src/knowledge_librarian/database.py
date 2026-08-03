"""SQLite persistence with FTS5 and cached-vector support."""

from __future__ import annotations

import json
import re
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path

import aiosqlite

from knowledge_librarian.models import (
    Chunk,
    DocumentSummary,
    RetrievedChunk,
    SourceDocument,
    SourceKind,
    SyncJob,
    SyncStatus,
)

SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS documents (
    id TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    source_uri TEXT NOT NULL,
    title TEXT NOT NULL,
    content TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    metadata_json TEXT NOT NULL,
    index_status TEXT NOT NULL DEFAULT 'pending',
    index_fingerprint TEXT
);
CREATE TABLE IF NOT EXISTS chunks (
    id TEXT PRIMARY KEY,
    document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    source TEXT NOT NULL,
    source_uri TEXT NOT NULL,
    title TEXT NOT NULL,
    text TEXT NOT NULL,
    ordinal INTEGER NOT NULL,
    content_hash TEXT NOT NULL,
    token_estimate INTEGER NOT NULL,
    embedding_json TEXT
);
CREATE INDEX IF NOT EXISTS ix_chunks_document ON chunks(document_id);
CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
    chunk_id UNINDEXED, title, text, tokenize='unicode61 remove_diacritics 2'
);
CREATE TABLE IF NOT EXISTS sync_jobs (
    id TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    status TEXT NOT NULL,
    started_at TEXT NOT NULL,
    completed_at TEXT,
    stats_json TEXT NOT NULL,
    error TEXT
);
CREATE TABLE IF NOT EXISTS feedback (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    response_id TEXT NOT NULL,
    rating TEXT NOT NULL CHECK(rating IN ('helpful', 'needs_work')),
    actor_hash TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""


class Database:
    def __init__(self, path: Path) -> None:
        self.path = path

    @asynccontextmanager
    async def connect(self) -> AsyncIterator[aiosqlite.Connection]:
        connection = await aiosqlite.connect(self.path)
        connection.row_factory = aiosqlite.Row
        await connection.execute("PRAGMA foreign_keys=ON")
        await connection.execute("PRAGMA busy_timeout=5000")
        try:
            yield connection
        finally:
            await connection.close()

    async def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        async with self.connect() as connection:
            await connection.executescript(SCHEMA)
            column_rows = await (
                await connection.execute("PRAGMA table_info(documents)")
            ).fetchall()
            columns = {str(row["name"]) for row in column_rows}
            if "index_status" not in columns:
                await connection.execute(
                    "ALTER TABLE documents ADD COLUMN index_status TEXT NOT NULL DEFAULT 'pending'"
                )
            if "index_fingerprint" not in columns:
                await connection.execute("ALTER TABLE documents ADD COLUMN index_fingerprint TEXT")
            await connection.commit()

    async def upsert_document(
        self,
        document: SourceDocument,
        chunks: Sequence[Chunk],
        *,
        index_fingerprint: str,
    ) -> tuple[str, bool]:
        async with self.connect() as connection:
            row = await (
                await connection.execute(
                    """SELECT content_hash, index_status, index_fingerprint
                       FROM documents WHERE id = ?""",
                    (document.id,),
                )
            ).fetchone()
            if row is not None and row["content_hash"] == document.content_hash:
                needs_index = (
                    row["index_status"] != "indexed"
                    or row["index_fingerprint"] != index_fingerprint
                )
                if needs_index:
                    await connection.execute(
                        """UPDATE documents SET index_status = 'pending', index_fingerprint = ?
                           WHERE id = ?""",
                        (index_fingerprint, document.id),
                    )
                    await connection.commit()
                return "unchanged", needs_index
            action = "created" if row is None else "updated"
            if row is not None:
                old_ids = await (
                    await connection.execute(
                        "SELECT id FROM chunks WHERE document_id = ?", (document.id,)
                    )
                ).fetchall()
                await connection.executemany(
                    "DELETE FROM chunks_fts WHERE chunk_id = ?", [(item["id"],) for item in old_ids]
                )
            await connection.execute(
                """
                INSERT INTO documents(id, source, source_uri, title, content, content_hash,
                                      updated_at, metadata_json, index_status, index_fingerprint)
                VALUES(?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?)
                ON CONFLICT(id) DO UPDATE SET source=excluded.source,
                    source_uri=excluded.source_uri, title=excluded.title, content=excluded.content,
                    content_hash=excluded.content_hash, updated_at=excluded.updated_at,
                    metadata_json=excluded.metadata_json, index_status='pending',
                    index_fingerprint=excluded.index_fingerprint
                """,
                (
                    document.id,
                    document.source.value,
                    document.source_uri,
                    document.title,
                    document.content,
                    document.content_hash,
                    document.updated_at.isoformat(),
                    json.dumps(document.metadata, separators=(",", ":")),
                    index_fingerprint,
                ),
            )
            await connection.execute("DELETE FROM chunks WHERE document_id = ?", (document.id,))
            await connection.executemany(
                """
                INSERT INTO chunks(id, document_id, source, source_uri, title, text, ordinal,
                                   content_hash, token_estimate, embedding_json)
                VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        chunk.id,
                        chunk.document_id,
                        chunk.source.value,
                        chunk.source_uri,
                        chunk.title,
                        chunk.text,
                        chunk.ordinal,
                        chunk.content_hash,
                        chunk.token_estimate,
                        json.dumps(chunk.embedding) if chunk.embedding is not None else None,
                    )
                    for chunk in chunks
                ],
            )
            await connection.executemany(
                "INSERT INTO chunks_fts(chunk_id, title, text) VALUES(?, ?, ?)",
                [(chunk.id, chunk.title, chunk.text) for chunk in chunks],
            )
            await connection.commit()
            return action, True

    async def mark_document_indexed(self, document_id: str, index_fingerprint: str) -> None:
        async with self.connect() as connection:
            await connection.execute(
                """UPDATE documents SET index_status = 'indexed', index_fingerprint = ?
                   WHERE id = ?""",
                (index_fingerprint, document_id),
            )
            await connection.commit()

    async def mark_document_deleting(self, document_id: str) -> None:
        async with self.connect() as connection:
            await connection.execute(
                "UPDATE documents SET index_status = 'deleting' WHERE id = ?", (document_id,)
            )
            await connection.commit()

    async def document_index_state(self, document_id: str) -> tuple[str, str | None] | None:
        async with self.connect() as connection:
            row = await (
                await connection.execute(
                    "SELECT index_status, index_fingerprint FROM documents WHERE id = ?",
                    (document_id,),
                )
            ).fetchone()
        if row is None:
            return None
        return str(row["index_status"]), row["index_fingerprint"]

    async def set_embeddings(self, embeddings: dict[str, list[float]]) -> None:
        async with self.connect() as connection:
            await connection.executemany(
                "UPDATE chunks SET embedding_json = ? WHERE id = ?",
                [(json.dumps(vector), chunk_id) for chunk_id, vector in embeddings.items()],
            )
            await connection.commit()

    async def lexical_search(self, query: str, *, limit: int) -> list[RetrievedChunk]:
        tokens = re.findall(r"[\w-]+", query.casefold(), flags=re.UNICODE)[:12]
        if not tokens:
            return []
        fts_query = " OR ".join(f'"{token.replace(chr(34), "")}"' for token in tokens)
        sql = """
            SELECT c.*, bm25(chunks_fts, 2.0, 1.0) AS rank_score
            FROM chunks_fts
            JOIN chunks c ON c.id = chunks_fts.chunk_id
            JOIN documents d ON d.id = c.document_id
            WHERE chunks_fts MATCH ? AND d.index_status = 'indexed'
            ORDER BY rank_score LIMIT ?
        """
        async with self.connect() as connection:
            rows = await (await connection.execute(sql, (fts_query, limit))).fetchall()
        return [
            RetrievedChunk(
                chunk=self._row_to_chunk(row),
                score=1.0 / (index + 1),
                lexical_rank=index + 1,
            )
            for index, row in enumerate(rows)
        ]

    async def documents_needing_index(
        self, index_fingerprint: str
    ) -> list[tuple[str, list[Chunk]]]:
        async with self.connect() as connection:
            documents = await (
                await connection.execute(
                    """SELECT id FROM documents
                       WHERE index_status != 'indexed' OR index_fingerprint IS NOT ?""",
                    (index_fingerprint,),
                )
            ).fetchall()
            result: list[tuple[str, list[Chunk]]] = []
            for document in documents:
                rows = await (
                    await connection.execute(
                        "SELECT * FROM chunks WHERE document_id = ? ORDER BY ordinal",
                        (document["id"],),
                    )
                ).fetchall()
                result.append((str(document["id"]), [self._row_to_chunk(row) for row in rows]))
        return result

    async def all_embedded_chunks(self, *, index_fingerprint: str | None = None) -> list[Chunk]:
        async with self.connect() as connection:
            rows = await (
                await connection.execute(
                    """SELECT c.* FROM chunks c JOIN documents d ON d.id = c.document_id
                       WHERE c.embedding_json IS NOT NULL AND d.index_status = 'indexed'
                       AND (? IS NULL OR d.index_fingerprint = ?)""",
                    (index_fingerprint, index_fingerprint),
                )
            ).fetchall()
        return [self._row_to_chunk(row) for row in rows]

    async def list_documents(self, *, limit: int = 100) -> list[DocumentSummary]:
        sql = """
            SELECT d.id, d.source, d.source_uri, d.title, d.updated_at, d.content_hash,
                   COUNT(c.id) AS chunk_count
            FROM documents d LEFT JOIN chunks c ON c.document_id = d.id
            GROUP BY d.id ORDER BY d.updated_at DESC LIMIT ?
        """
        async with self.connect() as connection:
            rows = await (await connection.execute(sql, (limit,))).fetchall()
        return [
            DocumentSummary(
                id=row["id"],
                source=SourceKind(row["source"]),
                source_uri=row["source_uri"],
                title=row["title"],
                updated_at=datetime.fromisoformat(row["updated_at"]),
                content_hash=row["content_hash"],
                chunk_count=row["chunk_count"],
            )
            for row in rows
        ]

    async def document_count_by_source(self) -> dict[SourceKind, int]:
        async with self.connect() as connection:
            rows = await (
                await connection.execute(
                    "SELECT source, COUNT(*) AS count FROM documents GROUP BY source"
                )
            ).fetchall()
        return {SourceKind(row["source"]): int(row["count"]) for row in rows}

    async def missing_document_ids(self, source: SourceKind, seen_ids: Sequence[str]) -> list[str]:
        async with self.connect() as connection:
            rows = await (
                await connection.execute(
                    "SELECT id FROM documents WHERE source = ?", (source.value,)
                )
            ).fetchall()
        seen = set(seen_ids)
        return [str(row["id"]) for row in rows if row["id"] not in seen]

    async def delete_document(self, document_id: str) -> None:
        async with self.connect() as connection:
            rows = await (
                await connection.execute(
                    "SELECT id FROM chunks WHERE document_id = ?", (document_id,)
                )
            ).fetchall()
            await connection.executemany(
                "DELETE FROM chunks_fts WHERE chunk_id = ?", [(row["id"],) for row in rows]
            )
            await connection.execute("DELETE FROM documents WHERE id = ?", (document_id,))
            await connection.commit()

    async def save_sync_job(self, job: SyncJob) -> None:
        stats = {
            "discovered": job.discovered,
            "created": job.created,
            "updated": job.updated,
            "unchanged": job.unchanged,
            "deleted": job.deleted,
        }
        async with self.connect() as connection:
            await connection.execute(
                """
                INSERT INTO sync_jobs(
                    id, source, status, started_at, completed_at, stats_json, error
                )
                VALUES(?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET status=excluded.status,
                    completed_at=excluded.completed_at, stats_json=excluded.stats_json,
                    error=excluded.error
                """,
                (
                    job.id,
                    job.source.value,
                    job.status.value,
                    job.started_at.isoformat(),
                    job.completed_at.isoformat() if job.completed_at else None,
                    json.dumps(stats, separators=(",", ":")),
                    job.error,
                ),
            )
            await connection.commit()

    async def get_sync_job(self, job_id: str) -> SyncJob | None:
        async with self.connect() as connection:
            row = await (
                await connection.execute("SELECT * FROM sync_jobs WHERE id = ?", (job_id,))
            ).fetchone()
        return self._row_to_sync_job(row) if row is not None else None

    async def list_sync_jobs(self, *, limit: int = 50) -> list[SyncJob]:
        async with self.connect() as connection:
            rows = await (
                await connection.execute(
                    "SELECT * FROM sync_jobs ORDER BY started_at DESC LIMIT ?", (limit,)
                )
            ).fetchall()
        return [self._row_to_sync_job(row) for row in rows]

    async def record_feedback(self, response_id: str, rating: str, actor_hash: str) -> None:
        if rating not in {"helpful", "needs_work"}:
            raise ValueError("invalid feedback rating")
        async with self.connect() as connection:
            await connection.execute(
                """
                INSERT INTO feedback(response_id, rating, actor_hash, created_at)
                VALUES(?, ?, ?, ?)
                """,
                (response_id[:100], rating, actor_hash[:64], datetime.now(UTC).isoformat()),
            )
            await connection.commit()

    async def feedback_count(self) -> int:
        async with self.connect() as connection:
            row = await (
                await connection.execute("SELECT COUNT(*) AS count FROM feedback")
            ).fetchone()
        return int(row["count"]) if row else 0

    async def healthcheck(self) -> bool:
        try:
            async with self.connect() as connection:
                row = await (await connection.execute("SELECT 1 AS ok")).fetchone()
            return bool(row and row["ok"] == 1)
        except (aiosqlite.Error, OSError):
            return False

    @staticmethod
    def _row_to_chunk(row: aiosqlite.Row) -> Chunk:
        embedding = json.loads(row["embedding_json"]) if row["embedding_json"] else None
        return Chunk(
            id=row["id"],
            document_id=row["document_id"],
            source=SourceKind(row["source"]),
            source_uri=row["source_uri"],
            title=row["title"],
            text=row["text"],
            ordinal=row["ordinal"],
            content_hash=row["content_hash"],
            token_estimate=row["token_estimate"],
            embedding=embedding,
        )

    @staticmethod
    def _row_to_sync_job(row: aiosqlite.Row) -> SyncJob:
        stats = json.loads(row["stats_json"])
        return SyncJob(
            id=row["id"],
            source=SourceKind(row["source"]),
            status=SyncStatus(row["status"]),
            started_at=parse_db_timestamp(row["started_at"]),
            completed_at=(parse_db_timestamp(row["completed_at"]) if row["completed_at"] else None),
            error=row["error"],
            **stats,
        )


def parse_db_timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
