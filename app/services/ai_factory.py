import logging
from functools import lru_cache

from app.core.settings import Settings, get_settings
from app.services.ai_provider import AIProvider, MockLLM, MockLLMOptions

logger = logging.getLogger(__name__)


def create_ai_provider(
    settings: Settings | None = None,
    mock_options: MockLLMOptions | None = None,
) -> AIProvider:
    settings = settings or get_settings()
    provider = settings.ai_provider.lower()
    options = mock_options or MockLLMOptions()

    if provider == "mock":
        return MockLLM(options)

    if provider == "local":
        try:
            return get_local_llm_provider(settings.model_name)
        except ImportError as exc:
            logger.warning(
                "Local LLM dependencies missing (%s); falling back to MockLLM",
                exc,
            )
            return MockLLM(options)

    raise ValueError(f"Unknown AI provider: {settings.ai_provider!r}")


@lru_cache
def get_local_llm_provider(model_name: str) -> AIProvider:
    from app.services.local_llm import LocalLLMProvider

    return LocalLLMProvider(model_name=model_name)
