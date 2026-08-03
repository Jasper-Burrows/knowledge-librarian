"""Deterministic cost preview and hard gates for opt-in live validation."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from decimal import ROUND_UP, Decimal
from typing import Any

from knowledge_librarian.chunking import estimate_tokens
from knowledge_librarian.config import Settings
from knowledge_librarian.demo_data import SYNTHETIC_ARTICLES

APPROVAL_PHRASE = "I_APPROVE_LIVE_OPENAI_COSTS"
PRICING_AS_OF = "2026-08-03"
PRICED_RESPONSE_MODEL = "gpt-5.6-terra"
PRICED_EMBEDDING_MODEL = "text-embedding-3-small"
RESPONSE_INPUT_USD_PER_MILLION = Decimal("2.50")
RESPONSE_OUTPUT_USD_PER_MILLION = Decimal("15.00")
EMBEDDING_USD_PER_MILLION = Decimal("0.02")
MAX_ATTEMPTS_PER_REQUEST = 3  # initial attempt plus the SDK's two bounded retries
VALIDATION_QUESTION = "How quickly must a severity-one incident be acknowledged?"


class LiveValidationBlocked(RuntimeError):
    """Raised before any provider call when a live-validation gate is not satisfied."""


@dataclass(frozen=True, slots=True)
class LiveValidationPlan:
    response_model: str
    embedding_model: str
    pricing_as_of: str
    questions: int
    expected_embedding_calls: int
    maximum_embedding_attempts: int
    expected_response_calls: int
    maximum_response_attempts: int
    embedding_tokens: int
    response_input_tokens: int
    response_output_tokens: int
    expected_cost_usd: Decimal
    maximum_projected_cost_usd: Decimal
    budget_cap_usd: Decimal

    @property
    def within_budget(self) -> bool:
        return self.maximum_projected_cost_usd <= self.budget_cap_usd

    def as_dict(self) -> dict[str, Any]:
        result = asdict(self)
        for key, value in result.items():
            if isinstance(value, Decimal):
                result[key] = f"{value:.6f}"
        result["within_budget"] = self.within_budget
        result["approval_phrase"] = APPROVAL_PHRASE
        return result


def _usd(tokens: int, rate_per_million: Decimal) -> Decimal:
    return Decimal(tokens) * rate_per_million / Decimal(1_000_000)


def build_live_validation_plan(settings: Settings) -> LiveValidationPlan:
    if settings.openai_model != PRICED_RESPONSE_MODEL:
        raise LiveValidationBlocked(
            f"No reviewed pricing profile for response model {settings.openai_model!r}"
        )
    if settings.embedding_model != PRICED_EMBEDDING_MODEL:
        raise LiveValidationBlocked(
            f"No reviewed pricing profile for embedding model {settings.embedding_model!r}"
        )

    document_tokens = sum(estimate_tokens(body) for _, _, body in SYNTHETIC_ARTICLES)
    question_tokens = estimate_tokens(VALIDATION_QUESTION)
    embedding_tokens = document_tokens + question_tokens
    # The response input includes the maximum configured packed context plus a conservative
    # allowance for source labels, safety instructions, and the validation question.
    response_input_tokens = settings.context_token_budget + 500
    response_output_tokens = 900
    expected = (
        _usd(embedding_tokens, EMBEDDING_USD_PER_MILLION)
        + _usd(response_input_tokens, RESPONSE_INPUT_USD_PER_MILLION)
        + _usd(response_output_tokens, RESPONSE_OUTPUT_USD_PER_MILLION)
    )
    maximum = expected * MAX_ATTEMPTS_PER_REQUEST
    quantizer = Decimal("0.000001")
    return LiveValidationPlan(
        response_model=settings.openai_model,
        embedding_model=settings.embedding_model,
        pricing_as_of=PRICING_AS_OF,
        questions=1,
        expected_embedding_calls=len(SYNTHETIC_ARTICLES) + 1,
        maximum_embedding_attempts=(len(SYNTHETIC_ARTICLES) + 1) * MAX_ATTEMPTS_PER_REQUEST,
        expected_response_calls=1,
        maximum_response_attempts=MAX_ATTEMPTS_PER_REQUEST,
        embedding_tokens=embedding_tokens,
        response_input_tokens=response_input_tokens,
        response_output_tokens=response_output_tokens,
        expected_cost_usd=expected.quantize(quantizer, rounding=ROUND_UP),
        maximum_projected_cost_usd=maximum.quantize(quantizer, rounding=ROUND_UP),
        budget_cap_usd=settings.live_validation_budget_usd,
    )


def require_live_validation_approval(settings: Settings, plan: LiveValidationPlan) -> None:
    """Enforce all cost and credential attestations before constructing a live client."""
    if not plan.within_budget:
        raise LiveValidationBlocked(
            "Maximum projected cost exceeds LIBRARIAN_LIVE_VALIDATION_BUDGET_USD"
        )
    if settings.live_validation_approval != APPROVAL_PHRASE:
        raise LiveValidationBlocked(
            "Set LIBRARIAN_LIVE_VALIDATION_APPROVAL to the exact approval phrase "
            "shown in the preview"
        )
    if not settings.live_validation_key_rotated:
        raise LiveValidationBlocked(
            "Set LIBRARIAN_LIVE_VALIDATION_KEY_ROTATED=true only after supplying a newly issued key"
        )
    if settings.openai_api_key is None:
        raise LiveValidationBlocked("OPENAI_API_KEY is required for live validation")
