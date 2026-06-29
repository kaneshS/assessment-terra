from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.api.dependencies import get_existing_user_id
from app.api.schemas import (
    CreateUserRequest,
    CreateUserResponse,
    UsageHistoryResponse,
    UsageRecordResponse,
    UsageResponse,
    UserConfigRequest,
    UserConfigResponse,
)
from app.db.repository import Repository
from app.db.session import get_db

router = APIRouter(tags=["users"])


def get_repository(db: Session = Depends(get_db)) -> Repository:
    return Repository(db)


@router.post("/users", response_model=CreateUserResponse, status_code=status.HTTP_201_CREATED)
def create_user(
    body: CreateUserRequest,
    repo: Repository = Depends(get_repository),
) -> CreateUserResponse:
    user = repo.create_user(name=body.name, email=body.email)
    return CreateUserResponse(
        user_id=user.id,
        name=user.name,
        email=user.email,
        created_at=user.created_at,
    )


@router.put("/config", response_model=UserConfigResponse)
def upsert_user_config(
    body: UserConfigRequest,
    user_id: str = Depends(get_existing_user_id),
    repo: Repository = Depends(get_repository),
) -> UserConfigResponse:
    result = repo.upsert_user_config(
        user_id=user_id,
        credits_to_add=body.quota_credits,
        credit_multiplier=body.credit_multiplier,
    )
    config = result.config
    return UserConfigResponse(
        user_id=config.user_id,
        quota_credits=config.quota_credits,
        credits_added=result.credits_added,
        credit_multiplier=config.credit_multiplier,
        updated_at=config.updated_at,
    )


@router.get("/usage", response_model=UsageResponse)
def get_user_usage(
    user_id: str = Depends(get_existing_user_id),
    repo: Repository = Depends(get_repository),
) -> UsageResponse:
    summary = repo.get_usage_summary(user_id)
    return UsageResponse(
        user_id=summary.user_id,
        quota=summary.quota,
        multiplier=summary.multiplier,
        credits_used=summary.credits_used,
        credits_reserved=summary.credits_reserved,
        credits_remaining=summary.credits_remaining,
    )


@router.get("/usage/history", response_model=UsageHistoryResponse)
def get_user_usage_history(
    user_id: str = Depends(get_existing_user_id),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    repo: Repository = Depends(get_repository),
) -> UsageHistoryResponse:
    records = repo.get_usage_history(user_id, limit=limit, offset=offset)
    return UsageHistoryResponse(
        records=[
            UsageRecordResponse(
                id=record.id,
                user_id=record.user_id,
                prompt=record.prompt,
                response=record.response,
                prompt_tokens=record.prompt_tokens,
                completion_tokens=record.completion_tokens,
                total_tokens=record.total_tokens,
                estimated_credits=record.estimated_credits,
                actual_credits=record.actual_credits,
                multiplier_at_time=record.multiplier_at_time,
                quota_at_time=record.quota_at_time,
                operation_type=record.operation_type,
                status=record.status,
                created_at=record.created_at,
            )
            for record in records
        ],
        limit=limit,
        offset=offset,
    )
