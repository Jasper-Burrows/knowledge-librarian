"""Optional Pinecone vector-store adapter loaded only when configured."""

from __future__ import annotations

import asyncio
from collections.abc import Sequence

from knowledge_librarian.models import Chunk, RetrievedChunk, SourceKind
from knowledge_librarian.ports import EmbeddingProvider


class PineconeVectorStore:
    def __init__(
        self,
        *,
        api_key: str,
        index_name: str,
        embeddings: EmbeddingProvider,
        namespace: str = "knowledge-librarian-v1",
    ) -> None:
        from pinecone import Pinecone

        self.index = Pinecone(api_key=api_key).Index(index_name)
        self.index_name = index_name
        self.embeddings = embeddings
        self.namespace = namespace

    @property
    def fingerprint(self) -> str:
        return (
            f"pinecone:index={self.index_name}:namespace={self.namespace}"
            f"|{self.embeddings.fingerprint}"
        )

    async def upsert(self, chunks: Sequence[Chunk]) -> None:
        vectors = await self.embeddings.embed([chunk.text for chunk in chunks])
        records = [
            {
                "id": chunk.id,
                "values": vector,
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
            for chunk, vector in zip(chunks, vectors, strict=True)
        ]
        if records:
            await asyncio.to_thread(self.index.upsert, vectors=records, namespace=self.namespace)

    async def delete_document(self, document_id: str) -> None:
        await asyncio.to_thread(
            self.index.delete,
            filter={"document_id": {"$eq": document_id}},
            namespace=self.namespace,
        )

    async def search(self, query: str, *, limit: int) -> list[RetrievedChunk]:
        vector = (await self.embeddings.embed([query]))[0]
        result = await asyncio.to_thread(
            self.index.query,
            vector=vector,
            top_k=limit,
            include_metadata=True,
            namespace=self.namespace,
        )
        matches = result.get("matches", []) if isinstance(result, dict) else result.matches
        output: list[RetrievedChunk] = []
        for rank, match in enumerate(matches, 1):
            metadata = match.get("metadata", {}) if isinstance(match, dict) else match.metadata
            match_id = match.get("id") if isinstance(match, dict) else match.id
            score = match.get("score", 0.0) if isinstance(match, dict) else match.score
            chunk = Chunk(
                id=match_id,
                document_id=metadata["document_id"],
                source=SourceKind(metadata["source"]),
                source_uri=metadata["source_uri"],
                title=metadata["title"],
                text=metadata["text"],
                ordinal=int(metadata["ordinal"]),
                content_hash=metadata["content_hash"],
                token_estimate=int(metadata["token_estimate"]),
            )
            output.append(
                RetrievedChunk(chunk=chunk, score=max(0.0, float(score)), semantic_rank=rank)
            )
        return output
