"""Application composition root."""

from __future__ import annotations

from dataclasses import dataclass

from knowledge_librarian.answers import OfflineAnswerGenerator, OpenAIAnswerGenerator
from knowledge_librarian.config import Settings
from knowledge_librarian.database import Database
from knowledge_librarian.demo_data import DemoDocumentSource
from knowledge_librarian.embeddings import DeterministicEmbeddingProvider, OpenAIEmbeddingProvider
from knowledge_librarian.ingestion import IngestionService
from knowledge_librarian.ports import AnswerGenerator, EmbeddingProvider, VectorStore
from knowledge_librarian.retrieval import HybridRetriever, IdentityReranker, LocalVectorStore
from knowledge_librarian.service import LibrarianService


@dataclass(slots=True)
class Container:
    settings: Settings
    database: Database
    ingestion: IngestionService
    service: LibrarianService
    mode: str


async def build_container(settings: Settings) -> Container:
    database = Database(settings.database_path)
    await database.initialize()

    if settings.live_ready:
        assert settings.openai_api_key is not None
        api_key = settings.openai_api_key.get_secret_value()
        embeddings: EmbeddingProvider = OpenAIEmbeddingProvider(
            api_key=api_key,
            model=settings.embedding_model,
            timeout=settings.connector_timeout_seconds,
        )
        answers: AnswerGenerator = OpenAIAnswerGenerator(
            api_key=api_key,
            model=settings.openai_model,
            timeout=settings.connector_timeout_seconds,
        )
        mode = "live"
    else:
        embeddings = DeterministicEmbeddingProvider()
        answers = OfflineAnswerGenerator()
        mode = "offline"

    vectors: VectorStore = LocalVectorStore(database, embeddings)
    if (
        settings.live_ready
        and settings.pinecone_enabled
        and settings.pinecone_api_key
        and settings.pinecone_index_name
    ):
        from knowledge_librarian.adapters.pinecone import PineconeVectorStore

        vectors = PineconeVectorStore(
            api_key=settings.pinecone_api_key.get_secret_value(),
            index_name=settings.pinecone_index_name,
            embeddings=embeddings,
        )
    ingestion = IngestionService(database, vectors)
    await ingestion.reconcile_index()
    retriever = HybridRetriever(database, vectors)
    service = LibrarianService(
        retriever,
        IdentityReranker(),
        answers,
        retrieval_limit=settings.retrieval_limit,
        context_token_budget=settings.context_token_budget,
        mode=mode,
    )
    container = Container(settings, database, ingestion, service, mode)

    # The synthetic library makes first-run setup useful and is idempotent.
    await ingestion.sync(DemoDocumentSource())
    return container
