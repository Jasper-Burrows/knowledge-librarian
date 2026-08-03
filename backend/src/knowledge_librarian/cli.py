"""Command-line entry points for local development and automation."""

from __future__ import annotations

import asyncio
import json
import tempfile
from pathlib import Path
from typing import Annotated

import typer

from knowledge_librarian.adapters.factory import build_document_source
from knowledge_librarian.adapters.local_pdf import LocalPdfSource, document_from_pdf
from knowledge_librarian.config import get_settings
from knowledge_librarian.container import build_container
from knowledge_librarian.demo_data import DemoDocumentSource
from knowledge_librarian.live_validation import (
    VALIDATION_QUESTION,
    LiveValidationBlocked,
    build_live_validation_plan,
    require_live_validation_approval,
)
from knowledge_librarian.models import ChatRequest

app = typer.Typer(no_args_is_help=True, help="Operate the Knowledge Librarian locally.")


@app.command()
def serve(host: str = "127.0.0.1", port: int = 8000, reload: bool = False) -> None:
    """Run the HTTP API."""
    import uvicorn

    uvicorn.run("knowledge_librarian.api:app", host=host, port=port, reload=reload)


@app.command()
def demo(
    question: Annotated[
        str, typer.Argument(help="Question to ask the bundled synthetic knowledge base.")
    ] = "What is the Sev-1 response process?",
) -> None:
    """Seed synthetic sources and ask one credential-free question."""

    async def run() -> None:
        container = await build_container(get_settings())
        answer = await container.service.answer(ChatRequest(message=question))
        typer.echo(answer.text)
        for citation in answer.citations:
            typer.echo(f"[{citation.id}] {citation.title} — {citation.source_uri}")

    asyncio.run(run())


@app.command("sync-demo")
def sync_demo() -> None:
    """Idempotently refresh the bundled synthetic source."""

    async def run() -> None:
        container = await build_container(get_settings())
        job = await container.ingestion.sync(DemoDocumentSource())
        typer.echo(json.dumps(job.model_dump(mode="json"), indent=2))

    asyncio.run(run())


@app.command("sync")
def sync_source(source: str) -> None:
    """Refresh an explicitly enabled source: demo, ClickUp, HubSpot, Stonly, or Microsoft Graph."""

    async def run() -> None:
        settings = get_settings()
        container = await build_container(settings)
        job = await container.ingestion.sync(build_document_source(settings, source))
        typer.echo(json.dumps(job.model_dump(mode="json"), indent=2))
        if job.status.value == "failed":
            raise typer.Exit(code=1)

    asyncio.run(run())


@app.command("import-pdf")
def import_pdf(path: Path) -> None:
    """Index a local text PDF without retaining the original file."""
    if not path.is_file():
        raise typer.BadParameter("PDF does not exist")
    data = path.read_bytes()

    async def run() -> None:
        settings = get_settings()
        if len(data) > settings.max_upload_bytes:
            raise typer.BadParameter("PDF exceeds the configured upload limit")
        document = document_from_pdf(path.name, data)
        container = await build_container(settings)
        job = await container.ingestion.sync(LocalPdfSource(document))
        typer.echo(json.dumps(job.model_dump(mode="json"), indent=2))

    asyncio.run(run())


@app.command("slack")
def slack() -> None:
    """Run the optional Slack Socket Mode delivery adapter."""

    async def run() -> None:
        from knowledge_librarian.adapters.slack import SlackApplicationAdapter

        settings = get_settings()
        if not settings.slack_enabled:
            raise typer.BadParameter("Slack is disabled; set LIBRARIAN_SLACK_ENABLED=true")
        if not (
            settings.slack_bot_token and settings.slack_app_token and settings.slack_signing_secret
        ):
            raise typer.BadParameter("Slack bot, app, and signing credentials are required")
        container = await build_container(settings)
        adapter = SlackApplicationAdapter(
            service=container.service,
            bot_token=settings.slack_bot_token.get_secret_value(),
            app_token=settings.slack_app_token.get_secret_value(),
            signing_secret=settings.slack_signing_secret.get_secret_value(),
            feedback_sink=container.database.record_feedback,
        )
        await adapter.run()

    asyncio.run(run())


@app.command("live-estimate")
def live_estimate() -> None:
    """Print deterministic live-validation calls, token bounds, cost, and approval phrase."""
    try:
        plan = build_live_validation_plan(get_settings())
    except LiveValidationBlocked as exc:
        raise typer.BadParameter(str(exc)) from exc
    typer.echo(json.dumps(plan.as_dict(), indent=2))


@app.command("live-validate")
def live_validate() -> None:
    """Run one opt-in OpenAI validation after all credential and budget gates pass."""
    settings = get_settings()
    try:
        plan = build_live_validation_plan(settings)
        require_live_validation_approval(settings, plan)
    except LiveValidationBlocked as exc:
        raise typer.BadParameter(str(exc)) from exc

    async def run() -> None:
        with tempfile.TemporaryDirectory(prefix="knowledge-librarian-live-") as directory:
            live_settings = settings.model_copy(
                update={
                    "mode": "live",
                    "database_path": Path(directory) / "live-validation.db",
                }
            )
            container = await build_container(live_settings)
            answer = await container.service.answer(ChatRequest(message=VALIDATION_QUESTION))
            if not answer.grounded:
                raise typer.Exit(code=1)
            typer.echo(answer.text)
            for citation in answer.citations:
                typer.echo(f"[{citation.id}] {citation.title} — {citation.source_uri}")

    asyncio.run(run())


if __name__ == "__main__":
    app()
