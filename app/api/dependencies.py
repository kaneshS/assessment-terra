import uuid

from fastapi import Depends, Header
from sqlalchemy.orm import Session

from app.core.exceptions import InvalidUserIdError, UserNotFoundError
from app.db.repository import Repository
from app.db.session import get_db


def get_user_id(x_user_id: str | None = Header(default=None, alias="X-User-Id")) -> str:
    if x_user_id is None:
        raise InvalidUserIdError(message="X-User-Id header is required")
    try:
        uuid.UUID(x_user_id)
    except ValueError:
        raise InvalidUserIdError(
            message="X-User-Id must be a valid UUID",
            details={"user_id": x_user_id},
        )
    return x_user_id


def get_existing_user_id(
    user_id: str = Depends(get_user_id),
    db: Session = Depends(get_db),
) -> str:
    repo = Repository(db)
    if repo.get_user_by_id(user_id) is None:
        raise UserNotFoundError(details={"user_id": user_id})
    return user_id
