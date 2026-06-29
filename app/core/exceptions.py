from typing import Any


class AppError(Exception):
    """Base application error with structured API response fields."""

    error_code: str = "internal_error"
    status_code: int = 500
    message: str = "An unexpected error occurred"

    def __init__(
        self,
        message: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        if message is not None:
            self.message = message
        self.details = details or {}
        super().__init__(self.message)


class UserNotFoundError(AppError):
    error_code = "user_not_found"
    status_code = 404
    message = "User not found"


class UserNotConfiguredError(AppError):
    error_code = "user_not_configured"
    status_code = 404
    message = "User quota not configured"


class QuotaExceededError(AppError):
    error_code = "quota_exceeded"
    status_code = 402
    message = "Quota exceeded"


class InsufficientCreditsEstimatedError(AppError):
    error_code = "insufficient_credits_estimated"
    status_code = 402
    message = "Insufficient credits (estimated)"


class InsufficientCreditsActualError(AppError):
    error_code = "insufficient_credits_actual"
    status_code = 402
    message = "Insufficient credits (actual usage)"


class GenerationFailedError(AppError):
    error_code = "generation_failed"
    status_code = 502
    message = "Generation failed"


class InvalidUserIdError(AppError):
    error_code = "invalid_user_id"
    status_code = 422
    message = "Invalid or missing user ID"


class DuplicateEmailError(AppError):
    error_code = "duplicate_email"
    status_code = 409
    message = "Email already registered"
