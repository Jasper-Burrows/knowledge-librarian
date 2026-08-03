"""Dependency-inversion boundaries for provider integrations."""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from typing import Protocol, runtime_checkable

from knowledge_librarian.models import (
    Answer,
    ChatRequest,
    Chunk,
    RetrievedChunk,
    SourceDocument,
)


@runtime_checkable
class DocumentSource(Protocol):
    name: str

    def documents(self, *, cursor: str | None = None) -> AsyncIterator[SourceDocument]: ...


@runtime_checkable
class EmbeddingProvider(Protocol):
    @property
    def fingerprint(self) -> str: ...

    async def embed(self, texts: Sequence[str]) -> list[list[float]]: ...


@runtime_checkable
class VectorStore(Protocol):
    @property
    def fingerprint(self) -> str: ...

    async def upsert(self, chunks: Sequence[Chunk]) -> None: ...

    async def delete_document(self, document_id: str) -> None: ...

    async def search(self, query: str, *, limit: int) -> list[RetrievedChunk]: ...


@runtime_checkable
class Reranker(Protocol):
    async def rerank(
        self, query: str, chunks: Sequence[RetrievedChunk], *, limit: int
    ) -> list[RetrievedChunk]: ...


@runtime_checkable
class AnswerGenerator(Protocol):
    async def answer(self, request: ChatRequest, context: Sequence[RetrievedChunk]) -> Answer: ...

    def stream(
        self, request: ChatRequest, context: Sequence[RetrievedChunk]
    ) -> AsyncIterator[str]: ...
