from __future__ import annotations

from pathlib import Path

import pymupdf
import pytest
from pydantic import ValidationError
from typer.testing import CliRunner

from knowledge_librarian.cli import app
from knowledge_librarian.config import get_settings
from knowledge_librarian.models import ChatMessage, ChatRequest
from knowledge_librarian.service import LibrarianService


def test_cli_demo_sync_and_pdf_import(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("LIBRARIAN_DATABASE_PATH", str(tmp_path / "cli.db"))
    monkeypatch.setenv("LIBRARIAN_MODE", "offline")
    get_settings.cache_clear()
    runner = CliRunner()

    demo = runner.invoke(app, ["demo", "What is the incident response time?"])
    assert demo.exit_code == 0
    assert "[1]" in demo.stdout
    sync = runner.invoke(app, ["sync", "demo"])
    assert sync.exit_code == 0
    assert '"status": "complete"' in sync.stdout
    slack = runner.invoke(app, ["slack"])
    assert slack.exit_code != 0
    assert "Slack is disabled" in slack.output
    estimate = runner.invoke(app, ["live-estimate"])
    assert estimate.exit_code == 0
    assert '"expected_embedding_calls": 6' in estimate.stdout
    blocked_live = runner.invoke(app, ["live-validate"])
    assert blocked_live.exit_code != 0

    pdf = pymupdf.open()  # type: ignore[no-untyped-call]
    page = pdf.new_page()
    page.insert_text((72, 72), "A synthetic CLI PDF policy with sufficient text.")
    pdf_path = tmp_path / "policy.pdf"
    pdf.save(pdf_path)
    pdf.close()
    imported = runner.invoke(app, ["import-pdf", str(pdf_path)])
    assert imported.exit_code == 0
    assert '"created": 1' in imported.stdout
    get_settings.cache_clear()


def test_retrieval_query_uses_only_bounded_request_history() -> None:
    request = ChatRequest(
        message="What about its deadline?",
        history=[
            ChatMessage(role="user", content="First unrelated turn"),
            ChatMessage(role="assistant", content="First answer"),
            ChatMessage(role="user", content="Tell me about incident reviews"),
            ChatMessage(role="assistant", content="Second answer"),
        ],
    )
    query = LibrarianService._retrieval_query(request)
    assert "First unrelated turn" in query
    assert "Tell me about incident reviews" in query
    assert query.endswith("What about its deadline?")
    isolated = LibrarianService._retrieval_query(ChatRequest(message="Separate conversation"))
    assert isolated == "Separate conversation"

    with pytest.raises(ValidationError):
        ChatRequest(
            message="too much history",
            history=[ChatMessage(role="user", content=str(index)) for index in range(21)],
        )
