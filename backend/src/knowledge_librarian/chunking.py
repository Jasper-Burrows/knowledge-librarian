"""Deterministic, token-aware document chunking."""

from __future__ import annotations

import hashlib
import re

from knowledge_librarian.models import Chunk, SourceDocument


def stable_id(*parts: str, prefix: str = "") -> str:
    digest = hashlib.sha256("\x1f".join(parts).encode()).hexdigest()[:32]
    return f"{prefix}{digest}"


def content_hash(content: str) -> str:
    return hashlib.sha256(content.encode()).hexdigest()


def estimate_tokens(text: str) -> int:
    return max(1, (len(text) + 3) // 4)


def chunk_document(
    document: SourceDocument, *, max_chars: int = 1_600, overlap_chars: int = 180
) -> list[Chunk]:
    """Split on paragraph boundaries, then hard-wrap oversized paragraphs."""
    if max_chars < 200 or overlap_chars < 0 or overlap_chars >= max_chars:
        raise ValueError("invalid chunk sizing")

    paragraphs = [part.strip() for part in re.split(r"\n\s*\n", document.content) if part.strip()]
    pieces: list[str] = []
    for paragraph in paragraphs:
        if len(paragraph) <= max_chars:
            pieces.append(paragraph)
            continue
        start = 0
        while start < len(paragraph):
            end = min(start + max_chars, len(paragraph))
            pieces.append(paragraph[start:end].strip())
            if end == len(paragraph):
                break
            start = end - overlap_chars

    groups: list[str] = []
    current = ""
    for piece in pieces:
        candidate = f"{current}\n\n{piece}" if current else piece
        if current and len(candidate) > max_chars:
            groups.append(current)
            carry = current[-overlap_chars:].lstrip() if overlap_chars else ""
            current = f"{carry}\n\n{piece}" if carry else piece
        else:
            current = candidate
    if current:
        groups.append(current)

    chunks: list[Chunk] = []
    for ordinal, text in enumerate(groups):
        digest = content_hash(text)
        chunks.append(
            Chunk(
                id=stable_id(document.id, str(ordinal), digest, prefix="chk_"),
                document_id=document.id,
                source=document.source,
                source_uri=document.source_uri,
                title=document.title,
                text=text,
                ordinal=ordinal,
                content_hash=digest,
                token_estimate=estimate_tokens(text),
            )
        )
    return chunks
