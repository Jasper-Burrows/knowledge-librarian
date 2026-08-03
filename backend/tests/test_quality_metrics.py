from __future__ import annotations

import pytest

from knowledge_librarian.container import build_container


@pytest.mark.asyncio
async def test_synthetic_retrieval_recall_at_five_and_mrr(settings) -> None:
    container = await build_container(settings)
    relevance = {
        "home office allowance and remote days": "Remote Work Handbook",
        "severity one incident acknowledgement": "Customer Incident Playbook",
        "support exports deletion retention": "Data Retention Standard",
        "production release window and rollout": "Product Release Process",
        "daily meal allowance and receipts": "Travel and Expenses",
    }
    hits = 0
    reciprocal_ranks: list[float] = []
    for query, expected_title in relevance.items():
        results = await container.service.retriever.retrieve(query, limit=5)
        titles = [item.chunk.title for item in results]
        if expected_title in titles:
            hits += 1
            reciprocal_ranks.append(1 / (titles.index(expected_title) + 1))
        else:
            reciprocal_ranks.append(0.0)

    recall_at_five = hits / len(relevance)
    mean_reciprocal_rank = sum(reciprocal_ranks) / len(reciprocal_ranks)
    assert recall_at_five == 1.0
    assert mean_reciprocal_rank >= 0.9
