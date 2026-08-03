"""Application services shared by HTTP and Slack delivery adapters."""

from __future__ import annotations

from collections.abc import AsyncIterator

from knowledge_librarian.answers import NO_CONTEXT, citations_for, validate_citations
from knowledge_librarian.models import Answer, ChatEvent, ChatRequest, RetrievedChunk
from knowledge_librarian.ports import AnswerGenerator, Reranker
from knowledge_librarian.retrieval import HybridRetriever, pack_context


class LibrarianService:
    def __init__(
        self,
        retriever: HybridRetriever,
        reranker: Reranker,
        answer_generator: AnswerGenerator,
        *,
        retrieval_limit: int,
        context_token_budget: int,
        mode: str,
    ) -> None:
        self.retriever = retriever
        self.reranker = reranker
        self.answer_generator = answer_generator
        self.retrieval_limit = retrieval_limit
        self.context_token_budget = context_token_budget
        self.mode = mode

    async def answer(self, request: ChatRequest) -> Answer:
        context = await self._context(self._retrieval_query(request))
        return await self.answer_generator.answer(request, context)

    async def events(self, request: ChatRequest) -> AsyncIterator[ChatEvent]:
        yield ChatEvent(type="status", data={"stage": "retrieving", "mode": self.mode})
        context = await self._context(self._retrieval_query(request))
        yield ChatEvent(type="status", data={"stage": "answering", "matches": len(context)})

        text = ""
        buffered_live_deltas: list[str] = []
        async for delta in self.answer_generator.stream(request, context):
            text += delta
            if self.mode == "live":
                buffered_live_deltas.append(delta)
            else:
                yield ChatEvent(type="delta", data={"text": delta})

        # Citation numbers always refer to the original packed-context positions. The offline
        # generator may select a later, more relevant chunk, so truncating or renumbering here
        # would attach a correct answer to the wrong source.
        available = citations_for(context)
        grounded = validate_citations(text, available)
        if self.mode == "live":
            # Live model output is untrusted until every marker validates. Holding the deltas
            # prevents an unsupported claim from reaching either the browser or Slack and then
            # being impossible to retract from the stream.
            if grounded:
                for delta in buffered_live_deltas:
                    yield ChatEvent(type="delta", data={"text": delta})
            else:
                text = NO_CONTEXT
                yield ChatEvent(type="delta", data={"text": NO_CONTEXT})
        if grounded:
            used = {marker for marker in __import__("re").findall(r"\[(\d+)]", text)}
            for citation in available:
                if citation.id in used:
                    yield ChatEvent(type="citation", data=citation.model_dump(mode="json"))
        yield ChatEvent(type="done", data={"grounded": grounded})

    async def _context(self, query: str) -> list[RetrievedChunk]:
        retrieved = await self.retriever.retrieve(query, limit=self.retrieval_limit * 2)
        reranked = await self.reranker.rerank(query, retrieved, limit=self.retrieval_limit)
        return pack_context(reranked, token_budget=self.context_token_budget)

    @staticmethod
    def _retrieval_query(request: ChatRequest) -> str:
        # Prior user turns make follow-ups retrievable without mixing conversations server-side.
        prior = [item.content for item in request.history[-6:] if item.role == "user"][-2:]
        return "\n".join([*prior, request.message])[-8_000:]
