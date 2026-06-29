from datetime import datetime

from pydantic import BaseModel, EmailStr, Field


class ErrorResponse(BaseModel):
    error_code: str
    message: str
    details: dict = Field(default_factory=dict)


class CreateUserRequest(BaseModel):
    name: str = Field(min_length=1)
    email: EmailStr


class CreateUserResponse(BaseModel):
    user_id: str
    name: str
    email: str
    created_at: datetime


class UserConfigRequest(BaseModel):
    quota_credits: int = Field(
        ge=0,
        description="Credits to add to the user's quota allowance (increment, not replace).",
    )
    credit_multiplier: float = Field(
        gt=0,
        description="Credit multiplier to set for future requests (replaces current value).",
    )


class UserConfigResponse(BaseModel):
    user_id: str
    quota_credits: int = Field(
        description="Total quota allowance after this update.",
    )
    credits_added: int = Field(
        description="Credits added by this request.",
    )
    credit_multiplier: float
    updated_at: datetime


class UsageResponse(BaseModel):
    user_id: str
    quota: int
    multiplier: float
    credits_used: int
    credits_reserved: int
    credits_remaining: int


class UsageRecordResponse(BaseModel):
    id: int
    user_id: str
    prompt: str | None
    response: str | None
    prompt_tokens: int | None
    completion_tokens: int | None
    total_tokens: int | None
    estimated_credits: int
    actual_credits: int | None
    multiplier_at_time: float
    quota_at_time: int
    operation_type: str
    status: str
    created_at: datetime


class UsageHistoryResponse(BaseModel):
    records: list[UsageRecordResponse]
    limit: int
    offset: int


class GenerateRequest(BaseModel):
    prompt: str = Field(min_length=1)


class GenerateResponse(BaseModel):
    response_text: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    estimated_credits: int
    actual_credits: int
    credits_remaining: int
    usage_record_id: int
