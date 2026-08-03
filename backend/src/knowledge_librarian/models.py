"""Domain models shared by ingestion, retrieval, chat, and adapters."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


def utc_now() -> datetime:
    return datetime.now(UTC)


class SourceKind(StrEnum):
    DEMO = "demo"
    LOCAL_PDF = "local_pdf"
    CLICKUP = "clickup"
    HUBSPOT = "hubspot"
    STONLY = "stonly"
    MICROSOFT_GRAPH = "microsoft_graph"


class SourceDocument(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str = Field(min_length=8, max_length=128)
    source: SourceKind
    source_uri: str = Field(max_length=2048)
    title: str = Field(min_length=1, max_length=500)
    content: str = Field(min_length=1, max_length=2_000_000)
    content_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    updated_at: datetime
    metadata: dict[str, Any] = Field(default_factory=dict)


class Chunk(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    document_id: str
    source: SourceKind
    source_uri: str
    title: str
    text: str
    ordinal: int = Field(ge=0)
    content_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    token_estimate: int = Field(ge=1)
    embedding: list[float] | None = None


class RetrievedChunk(BaseModel):
    chunk: Chunk
    score: float = Field(ge=0)
    lexical_rank: int | None = Field(default=None, ge=1)
    semantic_rank: int | None = Field(default=None, ge=1)


class Citation(BaseModel):
    id: str
    document_id: str
    chunk_id: str
    title: str
    source: SourceKind
    source_uri: str
    excerpt: str = Field(min_length=1, max_length=600)


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=12_000)


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4_000)
    conversation_id: str = Field(default="default", min_length=1, max_length=100)
    history: list[ChatMessage] = Field(default_factory=list, max_length=20)

    @field_validator("message")
    @classmethod
    def strip_message(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("message must contain non-whitespace characters")
        return value


class ChatEvent(BaseModel):
    type: Literal["status", "delta", "citation", "done", "error"]
    data: dict[str, Any]


class Answer(BaseModel):
    text: str
    citations: list[Citation]
    grounded: bool
    mode: Literal["offline", "live"]


class SyncStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETE = "complete"
    FAILED = "failed"


class SyncJob(BaseModel):
    id: str
    source: SourceKind
    status: SyncStatus
    started_at: datetime = Field(default_factory=utc_now)
    completed_at: datetime | None = None
    discovered: int = 0
    created: int = 0
    updated: int = 0
    unchanged: int = 0
    deleted: int = 0
    error: str | None = None


class SourceSummary(BaseModel):
    source: SourceKind
    enabled: bool
    configured: bool
    document_count: int = 0
    last_synced_at: datetime | None = None


class DocumentSummary(BaseModel):
    id: str
    source: SourceKind
    source_uri: str
    title: str
    updated_at: datetime
    content_hash: str
    chunk_count: int
