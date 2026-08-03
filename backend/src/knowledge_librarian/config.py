"""Typed, cached application configuration."""

from __future__ import annotations

from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="LIBRARIAN_",
        env_file=".env",
        env_file_encoding="utf-8",
        populate_by_name=True,
        extra="ignore",
    )

    mode: Literal["offline", "live"] = "offline"
    database_path: Path = Path("data/librarian.db")
    frontend_dist: Path = Path("frontend/dist")
    allowed_origins: Annotated[list[str], NoDecode] = ["http://localhost:5173"]
    max_upload_bytes: int = Field(default=10 * 1024 * 1024, ge=1, le=25 * 1024 * 1024)
    sync_token: SecretStr | None = None
    connector_timeout_seconds: float = Field(default=20, ge=1, le=60)
    retrieval_limit: int = Field(default=6, ge=1, le=20)
    context_token_budget: int = Field(default=3_000, ge=500, le=12_000)
    live_validation_budget_usd: Decimal = Field(
        default=Decimal("10.00"), gt=0, le=Decimal("100.00")
    )
    live_validation_approval: str = ""
    live_validation_key_rotated: bool = False

    openai_api_key: SecretStr | None = Field(default=None, validation_alias="OPENAI_API_KEY")
    openai_model: str = "gpt-5.6-terra"
    embedding_model: str = "text-embedding-3-small"

    clickup_enabled: bool = False
    clickup_api_token: SecretStr | None = Field(default=None, validation_alias="CLICKUP_API_TOKEN")
    clickup_team_id: str | None = Field(default=None, validation_alias="CLICKUP_TEAM_ID")
    hubspot_enabled: bool = False
    hubspot_access_token: SecretStr | None = Field(
        default=None, validation_alias="HUBSPOT_ACCESS_TOKEN"
    )
    stonly_enabled: bool = False
    stonly_base_url: str | None = Field(default=None, validation_alias="STONLY_BASE_URL")
    stonly_api_token: SecretStr | None = Field(default=None, validation_alias="STONLY_API_TOKEN")
    ms_graph_enabled: bool = False
    ms_graph_tenant_id: str | None = Field(default=None, validation_alias="MS_GRAPH_TENANT_ID")
    ms_graph_client_id: str | None = Field(default=None, validation_alias="MS_GRAPH_CLIENT_ID")
    ms_graph_client_secret: SecretStr | None = Field(
        default=None, validation_alias="MS_GRAPH_CLIENT_SECRET"
    )
    ms_graph_mailbox: str | None = Field(default=None, validation_alias="MS_GRAPH_MAILBOX")
    pinecone_enabled: bool = False
    pinecone_api_key: SecretStr | None = Field(default=None, validation_alias="PINECONE_API_KEY")
    pinecone_index_name: str | None = Field(default=None, validation_alias="PINECONE_INDEX_NAME")
    slack_enabled: bool = False
    slack_bot_token: SecretStr | None = Field(default=None, validation_alias="SLACK_BOT_TOKEN")
    slack_app_token: SecretStr | None = Field(default=None, validation_alias="SLACK_APP_TOKEN")
    slack_signing_secret: SecretStr | None = Field(
        default=None, validation_alias="SLACK_SIGNING_SECRET"
    )

    @field_validator("allowed_origins", mode="before")
    @classmethod
    def split_origins(cls, value: object) -> object:
        if isinstance(value, str) and not value.lstrip().startswith("["):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    @field_validator(
        "sync_token",
        "openai_api_key",
        "clickup_api_token",
        "hubspot_access_token",
        "stonly_api_token",
        "ms_graph_client_secret",
        "pinecone_api_key",
        "slack_bot_token",
        "slack_app_token",
        "slack_signing_secret",
        mode="before",
    )
    @classmethod
    def empty_secret_to_none(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        if isinstance(value, SecretStr) and not value.get_secret_value().strip():
            return None
        return value

    @property
    def live_ready(self) -> bool:
        return self.mode == "live" and self.openai_api_key is not None


@lru_cache
def get_settings() -> Settings:
    return Settings()
