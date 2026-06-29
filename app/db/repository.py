import uuid
from dataclasses import dataclass
from math import ceil

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.core.exceptions import (
    DuplicateEmailError,
    InsufficientCreditsEstimatedError,
    QuotaExceededError,
    UserNotConfiguredError,
    UserNotFoundError,
)
from app.db.models import Reservation, UsageRecord, User, UserBalance, UserConfig


@dataclass
class UsageSummary:
    user_id: str
    quota: int
    multiplier: float
    credits_used: int
    credits_reserved: int
    credits_remaining: int


@dataclass
class ReservationResult:
    reservation_id: int
    usage_record_id: int
    estimated_credits: int
    multiplier_at_time: float
    quota_at_time: int
    credits_used: int


@dataclass
class UserConfigResult:
    config: UserConfig
    credits_added: int


class Repository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create_user(
        self,
        name: str,
        email: str,
        user_id: str | None = None,
    ) -> User:
        existing = self.session.scalar(select(User).where(User.email == email))
        if existing is not None:
            raise DuplicateEmailError(details={"email": email})

        uid = user_id or str(uuid.uuid4())
        user = User(id=uid, name=name, email=email)
        balance = UserBalance(user_id=uid)
        self.session.add(user)
        self.session.add(balance)
        self.session.commit()
        self.session.refresh(user)
        return user

    def get_user_by_id(self, user_id: str) -> User | None:
        return self.session.get(User, user_id)

    def get_user_by_email(self, email: str) -> User | None:
        return self.session.scalar(select(User).where(User.email == email))

    def require_user(self, user_id: str) -> User:
        user = self.get_user_by_id(user_id)
        if user is None:
            raise UserNotFoundError(details={"user_id": user_id})
        return user

    def upsert_user_config(
        self, user_id: str, credits_to_add: int, credit_multiplier: float
    ) -> UserConfigResult:
        self.require_user(user_id)
        config = self.session.get(UserConfig, user_id)
        if config is None:
            config = UserConfig(
                user_id=user_id,
                quota_credits=credits_to_add,
                credit_multiplier=credit_multiplier,
            )
            self.session.add(config)
        else:
            config.quota_credits += credits_to_add
            config.credit_multiplier = credit_multiplier
        self.session.commit()
        self.session.refresh(config)
        return UserConfigResult(config=config, credits_added=credits_to_add)

    def get_user_config(self, user_id: str) -> UserConfig | None:
        return self.session.get(UserConfig, user_id)

    def get_user_balance(self, user_id: str) -> UserBalance | None:
        return self.session.get(UserBalance, user_id)

    def set_user_balance(
        self,
        user_id: str,
        credits_used: int,
        credits_reserved: int = 0,
    ) -> UserBalance:
        balance = self.get_user_balance(user_id)
        if balance is None:
            raise UserNotFoundError(details={"user_id": user_id})
        balance.credits_used = credits_used
        balance.credits_reserved = credits_reserved
        self.session.commit()
        self.session.refresh(balance)
        return balance

    def get_usage_summary(self, user_id: str) -> UsageSummary:
        self.require_user(user_id)
        config = self.get_user_config(user_id)
        if config is None:
            raise UserNotConfiguredError()
        balance = self.get_user_balance(user_id)
        assert balance is not None
        remaining = config.quota_credits - balance.credits_used - balance.credits_reserved
        return UsageSummary(
            user_id=user_id,
            quota=config.quota_credits,
            multiplier=config.credit_multiplier,
            credits_used=balance.credits_used,
            credits_reserved=balance.credits_reserved,
            credits_remaining=remaining,
        )

    def get_usage_history(
        self, user_id: str, limit: int = 50, offset: int = 0
    ) -> list[UsageRecord]:
        self.require_user(user_id)
        config = self.get_user_config(user_id)
        if config is None:
            raise UserNotConfiguredError()
        stmt = (
            select(UsageRecord)
            .where(UsageRecord.user_id == user_id)
            .order_by(UsageRecord.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(self.session.scalars(stmt).all())

    def reserve_credits(
        self,
        user_id: str,
        estimated_credits: int,
        prompt: str,
        operation_type: str = "generate",
    ) -> ReservationResult:
        """Reserve credits inside BEGIN IMMEDIATE for concurrency safety."""
        if self.session.in_transaction():
            self.session.commit()

        if self.session.bind and self.session.bind.dialect.name == "sqlite":
            self.session.execute(text("BEGIN IMMEDIATE"))

        self.require_user(user_id)

        config = self.session.get(UserConfig, user_id)
        if config is None:
            self.session.rollback()
            raise UserNotConfiguredError()

        balance = self.session.get(UserBalance, user_id)
        assert balance is not None

        remaining = (
            config.quota_credits - balance.credits_used - balance.credits_reserved
        )

        if remaining <= 0:
            self.session.rollback()
            raise QuotaExceededError(
                details={
                    "credits_remaining": remaining,
                    "credits_required": estimated_credits,
                }
            )

        if remaining < estimated_credits:
            self.session.rollback()
            raise InsufficientCreditsEstimatedError(
                details={
                    "credits_remaining": remaining,
                    "credits_required": estimated_credits,
                }
            )

        usage_record = UsageRecord(
            user_id=user_id,
            prompt=prompt,
            estimated_credits=estimated_credits,
            multiplier_at_time=config.credit_multiplier,
            quota_at_time=config.quota_credits,
            operation_type=operation_type,
            status="pending",
        )
        self.session.add(usage_record)
        self.session.flush()

        reservation = Reservation(
            user_id=user_id,
            estimated_credits=estimated_credits,
            status="pending",
            usage_record_id=usage_record.id,
        )
        self.session.add(reservation)
        self.session.flush()
        balance.credits_reserved += estimated_credits
        balance.version += 1

        reservation_id = reservation.id
        usage_record_id = usage_record.id
        credits_used = balance.credits_used

        self.session.commit()

        return ReservationResult(
            reservation_id=reservation_id,
            usage_record_id=usage_record_id,
            estimated_credits=estimated_credits,
            multiplier_at_time=config.credit_multiplier,
            quota_at_time=config.quota_credits,
            credits_used=credits_used,
        )

    def reconcile_success(
        self,
        reservation_id: int,
        usage_record_id: int,
        response_text: str,
        prompt_tokens: int,
        completion_tokens: int,
        total_tokens: int,
        actual_credits: int,
    ) -> UsageRecord:
        reservation = self.session.get(Reservation, reservation_id)
        usage_record = self.session.get(UsageRecord, usage_record_id)
        balance = self.session.get(UserBalance, reservation.user_id)

        reservation.status = "consumed"
        usage_record.response = response_text
        usage_record.prompt_tokens = prompt_tokens
        usage_record.completion_tokens = completion_tokens
        usage_record.total_tokens = total_tokens
        usage_record.actual_credits = actual_credits
        usage_record.status = "succeeded"

        balance.credits_used += actual_credits
        balance.credits_reserved -= reservation.estimated_credits
        balance.version += 1

        self.session.commit()
        self.session.refresh(usage_record)
        return usage_record

    def reconcile_insufficient_actual(
        self,
        reservation_id: int,
        usage_record_id: int,
        prompt_tokens: int,
        completion_tokens: int,
        total_tokens: int,
        actual_credits: int,
    ) -> UsageRecord:
        reservation = self.session.get(Reservation, reservation_id)
        usage_record = self.session.get(UsageRecord, usage_record_id)
        balance = self.session.get(UserBalance, reservation.user_id)

        reservation.status = "released"
        usage_record.response = None
        usage_record.prompt_tokens = prompt_tokens
        usage_record.completion_tokens = completion_tokens
        usage_record.total_tokens = total_tokens
        usage_record.actual_credits = actual_credits
        usage_record.status = "insufficient_credits_actual"

        balance.credits_reserved -= reservation.estimated_credits
        balance.version += 1

        self.session.commit()
        self.session.refresh(usage_record)
        return usage_record

    def release_reservation_failed(
        self,
        reservation_id: int,
        usage_record_id: int,
        status: str,
        prompt_tokens: int | None = None,
        completion_tokens: int | None = None,
        total_tokens: int | None = None,
        actual_credits: int | None = None,
    ) -> UsageRecord:
        reservation = self.session.get(Reservation, reservation_id)
        usage_record = self.session.get(UsageRecord, usage_record_id)
        balance = self.session.get(UserBalance, reservation.user_id)

        reservation.status = "released"
        usage_record.status = status
        usage_record.response = None

        if prompt_tokens is not None:
            usage_record.prompt_tokens = prompt_tokens
        if completion_tokens is not None:
            usage_record.completion_tokens = completion_tokens
        if total_tokens is not None:
            usage_record.total_tokens = total_tokens
        if actual_credits is not None:
            usage_record.actual_credits = actual_credits

        balance.credits_reserved -= reservation.estimated_credits
        if actual_credits is not None and actual_credits > 0:
            balance.credits_used += actual_credits
        balance.version += 1

        self.session.commit()
        self.session.refresh(usage_record)
        return usage_record
