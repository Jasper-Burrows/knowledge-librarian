"""Hybrid lexical/vector retrieval with reciprocal-rank fusion."""

from __future__ import annotations

import re
from collections.abc import Sequence

from knowledge_librarian.database import Database
from knowledge_librarian.embeddings import cosine_similarity
from knowledge_librarian.models import Chunk, RetrievedChunk
from knowledge_librarian.ports import EmbeddingProvider, VectorStore


def reciprocal_rank_fusion(
    lexical: Sequence[RetrievedChunk],
    semantic: Sequence[RetrievedChunk],
    *,
    rank_constant: int = 60,
) -> list[RetrievedChunk]:
    if rank_constant < 1:
        raise ValueError("rank_constant must be positive")
    by_id: dict[str, RetrievedChunk] = {}
    scores: dict[str, float] = {}
    lexical_ranks = {item.chunk.id: rank for rank, item in enumerate(lexical, 1)}
    semantic_ranks = {item.chunk.id: rank for rank, item in enumerate(semantic, 1)}
    for items in (lexical, semantic):
        for rank, item in enumerate(items, 1):
            by_id[item.chunk.id] = item
            scores[item.chunk.id] = scores.get(item.chunk.id, 0.0) + 1 / (rank_constant + rank)
    return [
        RetrievedChunk(
            chunk=by_id[chunk_id].chunk,
            score=score,
            lexical_rank=lexical_ranks.get(chunk_id),
            semantic_rank=semantic_ranks.get(chunk_id),
        )
        for chunk_id, score in sorted(scores.items(), key=lambda item: item[1], reverse=True)
    ]


class LocalVectorStore:
    """SQLite-backed vector store that performs cosine search in-process."""

    def __init__(self, database: Database, embeddings: EmbeddingProvider) -> None:
        self.database = database
        self.embeddings = embeddings

    @property
    def fingerprint(self) -> str:
        return f"sqlite-vectors-v1|{self.embeddings.fingerprint}"

    async def upsert(self, chunks: Sequence[Chunk]) -> None:
        if not chunks:
            return
        vectors = await self.embeddings.embed([chunk.text for chunk in chunks])
        await self.database.set_embeddings(
            {chunk.id: vector for chunk, vector in zip(chunks, vectors, strict=True)}
        )

    async def delete_document(self, document_id: str) -> None:
        # Chunk vectors share the document rows and cascade with document deletion.
        del document_id

    async def search(self, query: str, *, limit: int) -> list[RetrievedChunk]:
        query_vector = (await self.embeddings.embed([query]))[0]
        chunks = await self.database.all_embedded_chunks(index_fingerprint=self.fingerprint)
        ranked = sorted(
            ((chunk, cosine_similarity(query_vector, chunk.embedding or [])) for chunk in chunks),
            key=lambda item: item[1],
            reverse=True,
        )[:limit]
        return [
            RetrievedChunk(
                chunk=chunk,
                score=max(0.0, (similarity + 1) / 2),
                semantic_rank=index + 1,
            )
            for index, (chunk, similarity) in enumerate(ranked)
        ]


class HybridRetriever:
    def __init__(
        self,
        database: Database,
        vector_store: VectorStore,
        *,
        candidate_limit: int = 20,
    ) -> None:
        self.database = database
        self.vector_store = vector_store
        self.candidate_limit = candidate_limit

    async def retrieve(self, query: str, *, limit: int) -> list[RetrievedChunk]:
        lexical = await self.database.lexical_search(query, limit=self.candidate_limit)
        semantic = await self.vector_store.search(query, limit=self.candidate_limit)
        fused = reciprocal_rank_fusion(lexical, semantic)

        query_terms = set(re.findall(r"[a-z0-9]+", query.casefold()))
        meaningful = {
            term
            for term in query_terms
            if len(term) > 2 and term not in {"the", "and", "for", "are", "what", "how", "does"}
        }
        if meaningful:
            fused = [
                item
                for item in fused
                if meaningful.intersection(re.findall(r"[a-z0-9]+", item.chunk.text.casefold()))
                or item.lexical_rank is not None
            ]
        return fused[:limit]


class IdentityReranker:
    async def rerank(
        self, query: str, chunks: Sequence[RetrievedChunk], *, limit: int
    ) -> list[RetrievedChunk]:
        del query
        return list(chunks[:limit])


def pack_context(chunks: Sequence[RetrievedChunk], *, token_budget: int) -> list[RetrievedChunk]:
    packed: list[RetrievedChunk] = []
    used = 0
    for item in chunks:
        if packed and used + item.chunk.token_estimate > token_budget:
            continue
        if item.chunk.token_estimate > token_budget:
            continue
        packed.append(item)
        used += item.chunk.token_estimate
    return packed
