from __future__ import annotations

from decimal import Decimal

import pytest

from knowledge_librarian.config import Settings
from knowledge_librarian.container import build_container
from knowledge_librarian.live_validation import (
    APPROVAL_PHRASE,
    VALIDATION_QUESTION,
    LiveValidationBlocked,
    build_live_validation_plan,
    require_live_validation_approval,
)
from knowledge_librarian.models import ChatRequest


def test_live_validation_plan_is_deterministic_and_budget_enforced(tmp_path) -> None:
    settings = Settings(database_path=tmp_path / "plan.sqlite")
    plan = build_live_validation_plan(settings)
    assert plan.expected_embedding_calls == 6
    assert plan.maximum_embedding_attempts == 18
    assert plan.expected_response_calls == 1
    assert plan.maximum_response_attempts == 3
    assert plan.expected_cost_usd < plan.maximum_projected_cost_usd < Decimal("0.10")
    assert plan.within_budget
    assert plan.as_dict()["approval_phrase"] == APPROVAL_PHRASE

    low_budget = settings.model_copy(update={"live_validation_budget_usd": Decimal("0.01")})
    low_plan = build_live_validation_plan(low_budget)
    with pytest.raises(LiveValidationBlocked, match="exceeds"):
        require_live_validation_approval(low_budget, low_plan)
    with pytest.raises(LiveValidationBlocked, match="approval phrase"):
        require_live_validation_approval(settings, plan)
    approved = settings.model_copy(update={"live_validation_approval": APPROVAL_PHRASE})
    with pytest.raises(LiveValidationBlocked, match="newly issued key"):
        require_live_validation_approval(approved, plan)
    rotated = approved.model_copy(update={"live_validation_key_rotated": True})
    with pytest.raises(LiveValidationBlocked, match="OPENAI_API_KEY"):
        require_live_validation_approval(rotated, plan)

    unknown_model = settings.model_copy(update={"openai_model": "unpriced-model"})
    with pytest.raises(LiveValidationBlocked, match="No reviewed pricing profile"):
        build_live_validation_plan(unknown_model)


@pytest.mark.live
@pytest.mark.asyncio
async def test_opt_in_openai_live_validation(tmp_path) -> None:
    settings = Settings()
    if (
        settings.live_validation_approval != APPROVAL_PHRASE
        or not settings.live_validation_key_rotated
    ):
        pytest.skip("live OpenAI validation requires explicit approval and rotated-key attestation")

    plan = build_live_validation_plan(settings)
    require_live_validation_approval(settings, plan)
    live_settings = settings.model_copy(
        update={"mode": "live", "database_path": tmp_path / "live-validation.sqlite"}
    )
    container = await build_container(live_settings)
    answer = await container.service.answer(ChatRequest(message=VALIDATION_QUESTION))
    assert answer.mode == "live"
    assert answer.grounded
    assert answer.citations
