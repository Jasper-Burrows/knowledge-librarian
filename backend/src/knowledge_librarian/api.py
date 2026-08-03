"""FastAPI application and versioned HTTP/SSE interfaces."""

from __future__ import annotations

import hmac
import json
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Annotated, Any, cast

import structlog
from fastapi import FastAPI, File, Header, HTTPException, Request, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from knowledge_librarian.adapters.factory import SourceNotConfiguredError, build_document_source
from knowledge_librarian.adapters.local_pdf import (
    LocalPdfSource,
    PdfValidationError,
    document_from_pdf,
)
from knowledge_librarian.config import Settings, get_settings
from knowledge_librarian.container import Container, build_container
from knowledge_librarian.demo_data import DemoDocumentSource
from knowledge_librarian.logging import configure_logging
from knowledge_librarian.models import ChatRequest, SourceKind, SourceSummary

logger = structlog.get_logger()


class StatusResponse(BaseModel):
    status: str
    mode: str
    requested_mode: str
    live_ready: bool
    version: str = "1.0.0"


def get_container(request: Request) -> Container:
    return cast(Container, request.app.state.container)


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        configure_logging()
        app.state.container = await build_container(resolved)
        yield

    app = FastAPI(
        title="Knowledge Librarian API",
        version="1.0.0",
        description="Offline-first, source-grounded organizational knowledge retrieval.",
        lifespan=lifespan,
        docs_url="/api/docs",
        redoc_url=None,
        openapi_url="/api/openapi.json",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=resolved.allowed_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type", "Accept"],
    )

    @app.middleware("http")
    async def security_headers(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        response = await call_next(request)
        response.headers["X-Request-ID"] = uuid.uuid4().hex
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; "
            "img-src 'self' data:; connect-src 'self'; font-src 'self'; object-src 'none'; "
            "base-uri 'self'; frame-ancestors 'none'; form-action 'self'"
        )
        if request.url.path.startswith("/api/v1/chat"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.exception_handler(Exception)
    async def unhandled_exception(request: Request, exc: Exception) -> JSONResponse:
        logger.exception(
            "request_failed",
            method=request.method,
            path=request.url.path,
            error_type=type(exc).__name__,
        )
        return JSONResponse(
            status_code=500,
            content={"detail": "The request could not be completed."},
        )

    @app.get("/healthz", response_model=StatusResponse, tags=["operations"])
    async def health(request: Request) -> StatusResponse:
        container = get_container(request)
        return StatusResponse(
            status="ok",
            mode=container.mode,
            requested_mode=resolved.mode,
            live_ready=resolved.live_ready,
        )

    @app.get("/readyz", response_model=StatusResponse, tags=["operations"])
    async def readiness(request: Request) -> StatusResponse:
        container = get_container(request)
        if not await container.database.healthcheck():
            raise HTTPException(status_code=503, detail="Storage is unavailable")
        return StatusResponse(
            status="ready",
            mode=container.mode,
            requested_mode=resolved.mode,
            live_ready=resolved.live_ready,
        )

    @app.post("/api/v1/chat", tags=["chat"])
    async def chat(request: Request, payload: ChatRequest) -> StreamingResponse:
        container = get_container(request)

        async def event_stream() -> AsyncIterator[str]:
            try:
                async for event in container.service.events(payload):
                    body = json.dumps(event.data, separators=(",", ":"), ensure_ascii=False)
                    yield f"event: {event.type}\ndata: {body}\n\n"
            except Exception as exc:
                logger.warning("chat_stream_failed", error_type=type(exc).__name__)
                body = json.dumps({"message": "The answer could not be completed."})
                yield f"event: error\ndata: {body}\n\n"

        return StreamingResponse(
            event_stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache, no-store, no-transform",
                "X-Accel-Buffering": "no",
                "X-Content-Type-Options": "nosniff",
            },
        )

    @app.post("/api/v1/chat/answer", tags=["chat"])
    async def answer(request: Request, payload: ChatRequest) -> dict[str, Any]:
        result = await get_container(request).service.answer(payload)
        return result.model_dump(mode="json")

    @app.get("/api/v1/documents", tags=["library"])
    async def documents(request: Request) -> list[dict[str, Any]]:
        items = await get_container(request).database.list_documents()
        return [item.model_dump(mode="json") for item in items]

    @app.get("/api/v1/sources", tags=["library"])
    async def sources(request: Request) -> list[dict[str, Any]]:
        container = get_container(request)
        counts = await container.database.document_count_by_source()
        jobs = await container.database.list_sync_jobs()
        last_synced: dict[SourceKind, datetime] = {}
        for job in jobs:
            if job.status.value == "complete" and job.source not in last_synced:
                last_synced[job.source] = job.completed_at or job.started_at
        configured = {
            SourceKind.DEMO: True,
            SourceKind.LOCAL_PDF: True,
            SourceKind.CLICKUP: bool(resolved.clickup_api_token and resolved.clickup_team_id),
            SourceKind.HUBSPOT: resolved.hubspot_access_token is not None,
            SourceKind.STONLY: bool(resolved.stonly_api_token and resolved.stonly_base_url),
            SourceKind.MICROSOFT_GRAPH: bool(
                resolved.ms_graph_tenant_id
                and resolved.ms_graph_client_id
                and resolved.ms_graph_client_secret
                and resolved.ms_graph_mailbox
            ),
        }
        enabled = {
            SourceKind.DEMO: True,
            SourceKind.LOCAL_PDF: True,
            SourceKind.CLICKUP: resolved.clickup_enabled,
            SourceKind.HUBSPOT: resolved.hubspot_enabled,
            SourceKind.STONLY: resolved.stonly_enabled,
            SourceKind.MICROSOFT_GRAPH: resolved.ms_graph_enabled,
        }
        return [
            SourceSummary(
                source=source,
                enabled=enabled[source],
                configured=configured[source],
                document_count=counts.get(source, 0),
                last_synced_at=last_synced.get(source),
            ).model_dump(mode="json")
            for source in SourceKind
        ]

    @app.post("/api/v1/sources/demo/sync", tags=["library"])
    async def sync_demo(request: Request) -> dict[str, Any]:
        job = await get_container(request).ingestion.sync(DemoDocumentSource())
        return job.model_dump(mode="json")

    @app.post("/api/v1/sources/{source_name}/sync", tags=["library"])
    async def sync_source(
        request: Request,
        source_name: str,
        x_sync_token: Annotated[str | None, Header()] = None,
    ) -> dict[str, Any]:
        client_host = request.client.host if request.client else ""
        loopback = client_host in {"127.0.0.1", "::1", "localhost", "testclient"}
        expected = resolved.sync_token.get_secret_value() if resolved.sync_token else None
        authorized = bool(expected and x_sync_token and hmac.compare_digest(expected, x_sync_token))
        if not loopback and not authorized:
            raise HTTPException(
                status_code=403, detail="Source sync requires loopback access or a sync token"
            )
        try:
            source = build_document_source(resolved, source_name)
        except SourceNotConfiguredError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        job = await get_container(request).ingestion.sync(source)
        if job.status.value == "failed":
            raise HTTPException(
                status_code=502, detail=job.error or "Source synchronization failed"
            )
        return job.model_dump(mode="json")

    @app.get("/api/v1/sync-jobs/{job_id}", tags=["library"])
    async def sync_job(request: Request, job_id: str) -> dict[str, Any]:
        job = await get_container(request).database.get_sync_job(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="Sync job not found")
        return job.model_dump(mode="json")

    @app.get("/api/v1/sync-jobs", tags=["library"])
    async def sync_jobs(request: Request) -> list[dict[str, Any]]:
        jobs = await get_container(request).database.list_sync_jobs()
        return [job.model_dump(mode="json") for job in jobs]

    @app.post("/api/v1/sources/local-pdf", status_code=status.HTTP_201_CREATED, tags=["library"])
    async def upload_pdf(
        request: Request,
        file: Annotated[UploadFile, File(description="A text-based PDF, at most 10 MB")],
    ) -> dict[str, Any]:
        filename = file.filename or ""
        data = await file.read(resolved.max_upload_bytes + 1)
        await file.close()
        if len(data) > resolved.max_upload_bytes:
            raise HTTPException(status_code=413, detail="The PDF exceeds the upload limit")
        try:
            document = document_from_pdf(filename, data)
        except PdfValidationError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        job = await get_container(request).ingestion.sync(LocalPdfSource(document))
        return {"job": job.model_dump(mode="json"), "document_id": document.id}

    frontend_dist = resolved.frontend_dist
    if frontend_dist.is_dir():
        app.mount("/", StaticFiles(directory=frontend_dist, html=True), name="web")

    return app


app = create_app()
