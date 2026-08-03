from __future__ import annotations

import pymupdf
import pytest
from pydantic import ValidationError

from knowledge_librarian.adapters.local_pdf import (
    PdfValidationError,
    document_from_pdf,
    safe_filename,
)
from knowledge_librarian.config import Settings
from knowledge_librarian.models import SourceKind


def pdf_bytes(text: str | None = None) -> bytes:
    document = pymupdf.open()  # type: ignore[no-untyped-call]
    page = document.new_page()
    if text:
        page.insert_text((72, 72), text)
    data = document.tobytes()
    document.close()
    return data


def test_pdf_is_normalized_without_retaining_path() -> None:
    document = document_from_pdf("policy.pdf", pdf_bytes("A synthetic policy body for testing."))
    assert document.source is SourceKind.LOCAL_PDF
    assert document.source_uri.startswith("local-pdf://")
    assert document.metadata["filename"] == "policy.pdf"
    assert "Page 1" in document.content


@pytest.mark.parametrize("filename", ["../secret.pdf", "/tmp/file.pdf", "file.txt", ".pdf"])
def test_pdf_rejects_unsafe_names(filename: str) -> None:
    with pytest.raises(PdfValidationError):
        safe_filename(filename)


def test_pdf_rejects_malformed_and_empty_documents() -> None:
    with pytest.raises(PdfValidationError, match="not a PDF"):
        document_from_pdf("bad.pdf", b"not-pdf")
    with pytest.raises(PdfValidationError, match="No usable text"):
        document_from_pdf("empty.pdf", pdf_bytes())


def test_settings_parse_origins_and_require_key_for_live(tmp_path) -> None:
    settings = Settings(
        mode="live",
        database_path=tmp_path / "db.sqlite",
        allowed_origins="https://one.test,https://two.test",  # type: ignore[arg-type]
    )
    assert settings.allowed_origins == ["https://one.test", "https://two.test"]
    assert not settings.live_ready
    keyed = Settings(
        mode="live",
        database_path=tmp_path / "keyed.sqlite",
        openai_api_key="new-test-key",  # type: ignore[arg-type]
    )
    assert keyed.live_ready
    assert "new-test-key" not in repr(keyed)
    with pytest.raises(ValidationError):
        Settings(database_path=tmp_path / "bad.sqlite", max_upload_bytes=0)


def test_settings_parse_origins_from_environment(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LIBRARIAN_ALLOWED_ORIGINS", "https://first.test,https://second.test")
    monkeypatch.setenv("LIBRARIAN_FRONTEND_DIST", str(tmp_path / "web-dist"))
    settings = Settings(database_path=tmp_path / "environment.sqlite")
    assert settings.allowed_origins == ["https://first.test", "https://second.test"]
    assert settings.frontend_dist == tmp_path / "web-dist"


def test_blank_copied_secrets_are_normalized_to_none(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LIBRARIAN_MODE", "live")
    monkeypatch.setenv("OPENAI_API_KEY", "")
    monkeypatch.setenv("SLACK_BOT_TOKEN", "   ")
    settings = Settings(database_path=tmp_path / "blank-secrets.sqlite")
    assert settings.openai_api_key is None
    assert settings.slack_bot_token is None
    assert not settings.live_ready
