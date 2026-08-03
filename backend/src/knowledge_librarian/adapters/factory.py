"""Explicit construction of configured document-source adapters."""

from __future__ import annotations

from knowledge_librarian.config import Settings
from knowledge_librarian.ports import DocumentSource


class SourceNotConfiguredError(ValueError):
    pass


def build_document_source(settings: Settings, name: str) -> DocumentSource:
    if name == "demo":
        from knowledge_librarian.demo_data import DemoDocumentSource

        return DemoDocumentSource()
    if name == "clickup" and settings.clickup_enabled:
        from knowledge_librarian.adapters.clickup import ClickUpDocumentSource

        if not settings.clickup_api_token or not settings.clickup_team_id:
            raise SourceNotConfiguredError("ClickUp is enabled but is not fully configured")
        return ClickUpDocumentSource(
            token=settings.clickup_api_token.get_secret_value(),
            team_id=settings.clickup_team_id,
            timeout=settings.connector_timeout_seconds,
        )
    if name == "hubspot" and settings.hubspot_enabled:
        from knowledge_librarian.adapters.hubspot import HubSpotDocumentSource

        if not settings.hubspot_access_token:
            raise SourceNotConfiguredError("HubSpot is enabled but is not fully configured")
        return HubSpotDocumentSource(
            access_token=settings.hubspot_access_token.get_secret_value(),
            timeout=settings.connector_timeout_seconds,
        )
    if name == "stonly" and settings.stonly_enabled:
        from knowledge_librarian.adapters.stonly import StonlyDocumentSource

        if not settings.stonly_api_token or not settings.stonly_base_url:
            raise SourceNotConfiguredError("Stonly is enabled but is not fully configured")
        return StonlyDocumentSource(
            base_url=settings.stonly_base_url,
            api_token=settings.stonly_api_token.get_secret_value(),
            timeout=settings.connector_timeout_seconds,
        )
    if name == "microsoft_graph" and settings.ms_graph_enabled:
        from knowledge_librarian.adapters.microsoft_graph import MicrosoftGraphEmailSource

        if not (
            settings.ms_graph_tenant_id
            and settings.ms_graph_client_id
            and settings.ms_graph_client_secret
            and settings.ms_graph_mailbox
        ):
            raise SourceNotConfiguredError("Microsoft Graph is enabled but is not fully configured")
        return MicrosoftGraphEmailSource(
            tenant_id=settings.ms_graph_tenant_id,
            client_id=settings.ms_graph_client_id,
            client_secret=settings.ms_graph_client_secret.get_secret_value(),
            mailbox=settings.ms_graph_mailbox,
            timeout=settings.connector_timeout_seconds,
        )
    raise SourceNotConfiguredError(f"Source '{name}' is disabled or unknown")
