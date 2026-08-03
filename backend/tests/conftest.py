from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from pathlib import Path

import pytest

from knowledge_librarian.chunking import content_hash, stable_id
from knowledge_librarian.config import Settings
from knowledge_librarian.models import SourceDocument, SourceKind


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        mode="offline",
        database_path=tmp_path / "test.db",
        allowed_origins=["http://testserver"],
    )


@pytest.fixture
def make_document() -> Callable[..., SourceDocument]:
    def factory(
        title: str = "Test policy",
        content: str = "A useful synthetic policy with enough content to index safely.",
        source: SourceKind = SourceKind.DEMO,
        source_uri: str = "kb://test/policy",
    ) -> SourceDocument:
        from datetime import UTC, datetime

        return SourceDocument(
            id=stable_id(source.value, source_uri, prefix="doc_"),
            source=source,
            source_uri=source_uri,
            title=title,
            content=content,
            content_hash=content_hash(content),
            updated_at=datetime(2026, 1, 1, tzinfo=UTC),
        )

    return factory


class StaticSource:
    name = SourceKind.DEMO.value

    def __init__(self, documents: list[SourceDocument], *, fail: bool = False) -> None:
        self.items = documents
        self.fail = fail

    async def documents(self, *, cursor: str | None = None) -> AsyncIterator[SourceDocument]:
        del cursor
        for document in self.items:
            yield document
        if self.fail:
            raise RuntimeError("synthetic connector failure")
