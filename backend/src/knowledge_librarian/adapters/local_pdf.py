"""Memory-only local PDF ingestion with strict validation."""

from __future__ import annotations

import re
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import PurePath

import pymupdf

from knowledge_librarian.chunking import content_hash, stable_id
from knowledge_librarian.models import SourceDocument, SourceKind


class PdfValidationError(ValueError):
    pass


def safe_filename(filename: str) -> str:
    name = PurePath(filename).name
    if (
        name != filename
        or PurePath(name).suffix.casefold() != ".pdf"
        or not PurePath(name).stem.strip(". ")
    ):
        raise PdfValidationError("A plain .pdf filename is required")
    cleaned = re.sub(r"[^A-Za-z0-9._ -]", "_", name).strip(". ")
    if not cleaned or len(cleaned) > 180:
        raise PdfValidationError("The PDF filename is invalid")
    return cleaned


def document_from_pdf(filename: str, data: bytes) -> SourceDocument:
    name = safe_filename(filename)
    if not data.startswith(b"%PDF-"):
        raise PdfValidationError("The upload is not a PDF")
    try:
        with pymupdf.open(stream=data, filetype="pdf") as pdf:  # type: ignore[no-untyped-call]
            if pdf.page_count > 500:
                raise PdfValidationError("PDFs may contain at most 500 pages")
            pages = [page.get_text("text").strip() for page in pdf]
            title = (pdf.metadata or {}).get("title") or name.removesuffix(".pdf")
    except PdfValidationError:
        raise
    except Exception as exc:
        raise PdfValidationError("The PDF could not be read") from exc
    content = "\n\n".join(f"Page {index}\n{text}" for index, text in enumerate(pages, 1) if text)
    if len(content.strip()) < 20:
        raise PdfValidationError("No usable text was found in the PDF")
    digest = content_hash(content)
    return SourceDocument(
        id=stable_id(SourceKind.LOCAL_PDF.value, name, digest, prefix="doc_"),
        source=SourceKind.LOCAL_PDF,
        source_uri=f"local-pdf://{stable_id(name, digest)}",
        title=title[:500],
        content=content,
        content_hash=digest,
        updated_at=datetime.now(UTC),
        metadata={"filename": name, "page_count": len(pages)},
    )


class LocalPdfSource:
    name = SourceKind.LOCAL_PDF.value

    def __init__(self, document: SourceDocument) -> None:
        self.document = document

    async def documents(self, *, cursor: str | None = None) -> AsyncIterator[SourceDocument]:
        del cursor
        yield self.document
