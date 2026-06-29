from app.core.exceptions import UserNotConfiguredError
from app.db.repository import Repository
from app.services.metering import DEFAULT_MAX_COMPLETION_TOKENS, estimate_credits


class QuotaService:
    def __init__(self, repository: Repository) -> None:
        self.repository = repository

    def estimate_generation_credits(
        self, user_id: str, prompt: str
    ) -> tuple[int, float]:
        self.repository.require_user(user_id)
        config = self.repository.get_user_config(user_id)
        if config is None:
            raise UserNotConfiguredError()
        _, estimated_credits = estimate_credits(
            prompt, DEFAULT_MAX_COMPLETION_TOKENS, config.credit_multiplier
        )
        return estimated_credits, config.credit_multiplier
