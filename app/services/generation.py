from dataclasses import dataclass

from app.core.exceptions import (
    GenerationFailedError,
    InsufficientCreditsActualError,
)
from app.db.repository import Repository, ReservationResult
from app.services.ai_provider import AIFailure, AIPartialFailure, AIProvider
from app.services.metering import DEFAULT_MAX_COMPLETION_TOKENS, actual_credits_from_tokens
from app.services.quota import QuotaService


@dataclass
class GenerationResponse:
    response_text: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    estimated_credits: int
    actual_credits: int
    credits_remaining: int
    usage_record_id: int


class GenerationService:
    def __init__(
        self,
        repository: Repository,
        ai_provider: AIProvider,
    ) -> None:
        self.repository = repository
        self.ai_provider = ai_provider
        self.quota_service = QuotaService(repository)

    def generate(
        self,
        user_id: str,
        prompt: str,
        operation_type: str = "generate",
    ) -> GenerationResponse:
        estimated_credits, _ = self.quota_service.estimate_generation_credits(
            user_id, prompt
        )

        reservation = self.repository.reserve_credits(
            user_id=user_id,
            estimated_credits=estimated_credits,
            prompt=prompt,
            operation_type=operation_type,
        )

        try:
            result = self.ai_provider.generate(prompt, DEFAULT_MAX_COMPLETION_TOKENS)
        except AIPartialFailure as exc:
            return self._handle_partial_failure(reservation, exc)
        except AIFailure:
            self.repository.release_reservation_failed(
                reservation_id=reservation.reservation_id,
                usage_record_id=reservation.usage_record_id,
                status="failed_pre_usage",
            )
            raise GenerationFailedError(
                details={"stage": "pre_usage", "reservation_released": True}
            ) from None

        actual_credits = actual_credits_from_tokens(
            result.total_tokens, reservation.multiplier_at_time
        )

        if reservation.credits_used + actual_credits > reservation.quota_at_time:
            self.repository.reconcile_insufficient_actual(
                reservation_id=reservation.reservation_id,
                usage_record_id=reservation.usage_record_id,
                prompt_tokens=result.prompt_tokens,
                completion_tokens=result.completion_tokens,
                total_tokens=result.total_tokens,
                actual_credits=actual_credits,
            )
            summary = self.repository.get_usage_summary(user_id)
            raise InsufficientCreditsActualError(
                details={
                    "actual_credits": actual_credits,
                    "quota_at_time": reservation.quota_at_time,
                    "credits_used": summary.credits_used,
                    "usage_record_id": reservation.usage_record_id,
                }
            )

        usage_record = self.repository.reconcile_success(
            reservation_id=reservation.reservation_id,
            usage_record_id=reservation.usage_record_id,
            response_text=result.text,
            prompt_tokens=result.prompt_tokens,
            completion_tokens=result.completion_tokens,
            total_tokens=result.total_tokens,
            actual_credits=actual_credits,
        )

        summary = self.repository.get_usage_summary(user_id)
        return GenerationResponse(
            response_text=result.text,
            prompt_tokens=result.prompt_tokens,
            completion_tokens=result.completion_tokens,
            total_tokens=result.total_tokens,
            estimated_credits=reservation.estimated_credits,
            actual_credits=actual_credits,
            credits_remaining=summary.credits_remaining,
            usage_record_id=usage_record.id,
        )

    def _handle_partial_failure(
        self, reservation: ReservationResult, exc: AIPartialFailure
    ) -> GenerationResponse:
        partial = exc.partial_result
        actual_credits = actual_credits_from_tokens(
            partial.total_tokens, reservation.multiplier_at_time
        )

        if reservation.credits_used + actual_credits > reservation.quota_at_time:
            self.repository.release_reservation_failed(
                reservation_id=reservation.reservation_id,
                usage_record_id=reservation.usage_record_id,
                status="failed_partial",
                prompt_tokens=partial.prompt_tokens,
                completion_tokens=partial.completion_tokens,
                total_tokens=partial.total_tokens,
                actual_credits=None,
            )
            raise GenerationFailedError(
                details={"stage": "partial", "charged_credits": 0}
            ) from None

        self.repository.release_reservation_failed(
            reservation_id=reservation.reservation_id,
            usage_record_id=reservation.usage_record_id,
            status="failed_partial",
            prompt_tokens=partial.prompt_tokens,
            completion_tokens=partial.completion_tokens,
            total_tokens=partial.total_tokens,
            actual_credits=actual_credits,
        )
        raise GenerationFailedError(
            details={"stage": "partial", "charged_credits": actual_credits}
        ) from None
