from fastapi import APIRouter, Depends, Header
from sqlalchemy.orm import Session

from app.api.dependencies import get_existing_user_id
from app.api.schemas import GenerateRequest, GenerateResponse
from app.core.settings import get_settings
from app.db.repository import Repository
from app.db.session import get_db
from app.services.ai_factory import create_ai_provider
from app.services.ai_provider import AIProvider, MockLLMOptions
from app.services.generation import GenerationService

router = APIRouter(tags=["generate"])


def get_repository(db: Session = Depends(get_db)) -> Repository:
    return Repository(db)


def _mock_options_from_headers(
    x_mock_fail_before_usage: str | None,
    x_mock_fail_after_partial: str | None,
    x_mock_high_tokens: str | None,
) -> MockLLMOptions | None:
    if not any(
        header == "true"
        for header in (
            x_mock_fail_before_usage,
            x_mock_fail_after_partial,
            x_mock_high_tokens,
        )
    ):
        return None

    options = MockLLMOptions()
    if x_mock_fail_before_usage == "true":
        options.fail_before_usage = True
    if x_mock_fail_after_partial == "true":
        options.fail_after_partial = True
    if x_mock_high_tokens == "true":
        options.return_high_token_count = True
    return options


def get_ai_provider(
    x_mock_fail_before_usage: str | None = Header(default=None),
    x_mock_fail_after_partial: str | None = Header(default=None),
    x_mock_high_tokens: str | None = Header(default=None),
) -> AIProvider:
    mock_options = _mock_options_from_headers(
        x_mock_fail_before_usage,
        x_mock_fail_after_partial,
        x_mock_high_tokens,
    )
    settings = get_settings()

    if settings.ai_provider.lower() == "mock" or mock_options is not None:
        return create_ai_provider(settings, mock_options=mock_options or MockLLMOptions())

    return create_ai_provider(settings)


def get_generation_service(
    repo: Repository = Depends(get_repository),
    ai_provider: AIProvider = Depends(get_ai_provider),
) -> GenerationService:
    return GenerationService(repository=repo, ai_provider=ai_provider)


@router.post("/generate", response_model=GenerateResponse)
def generate_text(
    body: GenerateRequest,
    user_id: str = Depends(get_existing_user_id),
    service: GenerationService = Depends(get_generation_service),
) -> GenerateResponse:
    result = service.generate(
        user_id=user_id,
        prompt=body.prompt,
    )
    return GenerateResponse(
        response_text=result.response_text,
        prompt_tokens=result.prompt_tokens,
        completion_tokens=result.completion_tokens,
        total_tokens=result.total_tokens,
        estimated_credits=result.estimated_credits,
        actual_credits=result.actual_credits,
        credits_remaining=result.credits_remaining,
        usage_record_id=result.usage_record_id,
    )
