from __future__ import annotations

import pytest
from pydantic import ValidationError

from knowledge_librarian.chunking import chunk_document, content_hash, estimate_tokens, stable_id
from knowledge_librarian.embeddings import DeterministicEmbeddingProvider, cosine_similarity
from knowledge_librarian.models import ChatRequest, RetrievedChunk
from knowledge_librarian.retrieval import pack_context, reciprocal_rank_fusion


def test_stable_id_and_hash_are_deterministic() -> None:
    assert stable_id("a", "b", prefix="doc_") == stable_id("a", "b", prefix="doc_")
    assert stable_id("a", "b") != stable_id("b", "a")
    assert len(content_hash("content")) == 64
    assert estimate_tokens("") == 1
    assert estimate_tokens("12345") == 2


def test_chunking_is_stable_and_validates_sizing(make_document) -> None:
    document = make_document(content=("First paragraph. " * 30) + "\n\n" + ("Second. " * 30))
    first = chunk_document(document, max_chars=240, overlap_chars=30)
    second = chunk_document(document, max_chars=240, overlap_chars=30)
    assert len(first) > 2
    assert [chunk.id for chunk in first] == [chunk.id for chunk in second]
    assert [chunk.ordinal for chunk in first] == list(range(len(first)))
    assert all(chunk.document_id == document.id for chunk in first)
    with pytest.raises(ValueError, match="invalid chunk"):
        chunk_document(document, max_chars=100)


@pytest.mark.asyncio
async def test_deterministic_embeddings_and_cosine() -> None:
    provider = DeterministicEmbeddingProvider(64)
    vectors = await provider.embed(["incident response", "incident response", "travel meals"])
    assert vectors[0] == vectors[1]
    assert cosine_similarity(vectors[0], vectors[1]) == pytest.approx(1.0)
    assert cosine_similarity(vectors[0], []) == 0.0
    assert cosine_similarity([1.0], [1.0, 2.0]) == 0.0
    with pytest.raises(ValueError, match="at least 32"):
        DeterministicEmbeddingProvider(8)


def test_rrf_combines_rankings_and_pack_respects_budget(make_document) -> None:
    chunks = chunk_document(make_document(content="One paragraph with enough useful test content."))
    first = RetrievedChunk(chunk=chunks[0], score=1, lexical_rank=1)
    other_doc = make_document(
        title="Other", content="Different useful content.", source_uri="kb://other"
    )
    second_chunk = chunk_document(other_doc)[0]
    second = RetrievedChunk(chunk=second_chunk, score=1, semantic_rank=1)
    fused = reciprocal_rank_fusion([first], [second, first])
    assert fused[0].chunk.id == first.chunk.id
    assert fused[0].lexical_rank == 1
    assert fused[0].semantic_rank == 2
    assert pack_context(fused, token_budget=first.chunk.token_estimate) == [fused[0]]
    with pytest.raises(ValueError, match="positive"):
        reciprocal_rank_fusion([], [], rank_constant=0)


def test_chat_request_strips_and_bounds_input() -> None:
    request = ChatRequest(message="  hello  ")
    assert request.message == "hello"
    with pytest.raises(ValidationError):
        ChatRequest(message="   ")
    with pytest.raises(ValidationError):
        ChatRequest(message="x" * 4_001)
