import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.settings import get_settings
from app.db.models import Base
from app.db.repository import Repository
from app.db.session import get_db
from app.main import create_app
from app.services.ai_provider import MockLLM, MockLLMOptions


@pytest.fixture(autouse=True)
def use_mock_ai_provider(monkeypatch):
    monkeypatch.setenv("AI_PROVIDER", "mock")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()

# Test user UUIDs (valid UUID strings for API header auth)
ALICE = "550e8400-e29b-41d4-a716-446655440000"
BOB = "550e8400-e29b-41d4-a716-446655440001"
CAROL = "550e8400-e29b-41d4-a716-446655440002"
DAVE = "550e8400-e29b-41d4-a716-446655440003"
EVE = "550e8400-e29b-41d4-a716-446655440004"
FRANK = "550e8400-e29b-41d4-a716-446655440005"
USER1 = "550e8400-e29b-41d4-a716-446655440010"
LOW_MULT = "550e8400-e29b-41d4-a716-446655440011"
HIGH_MULT = "550e8400-e29b-41d4-a716-446655440012"
BLOCKED = "550e8400-e29b-41d4-a716-446655440013"
ALLOWED = "550e8400-e29b-41d4-a716-446655440014"
OK_USER = "550e8400-e29b-41d4-a716-446655440015"
EXHAUSTED = "550e8400-e29b-41d4-a716-446655440016"
USAGE_USER = "550e8400-e29b-41d4-a716-446655440017"
UNKNOWN = "550e8400-e29b-41d4-a716-446655440018"
BOUNDARY = "550e8400-e29b-41d4-a716-446655440019"
FULL = "550e8400-e29b-41d4-a716-44665544001a"
FAIL_PRE = "550e8400-e29b-41d4-a716-446655440020"
FAIL_PARTIAL = "550e8400-e29b-41d4-a716-446655440021"
HEADER_USER = "550e8400-e29b-41d4-a716-446655440022"
HEADER_HIGH = "550e8400-e29b-41d4-a716-446655440023"
HISTORY_USER = "550e8400-e29b-41d4-a716-446655440030"
RESERVE_USER = "550e8400-e29b-41d4-a716-446655440031"
CONFIG_USER = "550e8400-e29b-41d4-a716-446655440032"
MULTI_GEN_USER = "550e8400-e29b-41d4-a716-446655440033"
GEN_USER = "550e8400-e29b-41d4-a716-446655440034"


def user_headers(user_id: str, **extra: str) -> dict[str, str]:
    headers = {"X-User-Id": user_id}
    headers.update(extra)
    return headers


@pytest.fixture
def db_engine():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    yield engine
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def db_session(db_engine):
    SessionLocal = sessionmaker(bind=db_engine, autocommit=False, autoflush=False)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def client(db_engine):
    SessionLocal = sessionmaker(bind=db_engine, autocommit=False, autoflush=False)

    def override_get_db():
        db = SessionLocal()
        try:
            yield db
        finally:
            db.close()

    app = create_app()
    app.dependency_overrides[get_db] = override_get_db

    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def repo(db_session):
    return Repository(db_session)


SCENARIO_USER_PROFILES: dict[str, tuple[str, str]] = {
    ALICE: ("Alice", "alice@example.com"),
    BOB: ("Bob", "bob@example.com"),
    CAROL: ("Carol", "carol@example.com"),
    DAVE: ("Dave", "dave@example.com"),
    EVE: ("Eve", "eve@example.com"),
    FRANK: ("Frank", "frank@example.com"),
}


def seed_user(
    repo: Repository,
    user_id: str,
    name: str | None = None,
    email: str | None = None,
) -> None:
    if repo.get_user_by_id(user_id) is None:
        profile = SCENARIO_USER_PROFILES.get(user_id)
        resolved_name = name or (profile[0] if profile else "Test User")
        resolved_email = email or (profile[1] if profile else f"{user_id}@example.com")
        repo.create_user(
            name=resolved_name,
            email=resolved_email,
            user_id=user_id,
        )


def configure_user(
    client: TestClient,
    user_id: str,
    quota_credits: int,
    credit_multiplier: float,
    repo: Repository,
) -> None:
    seed_user(repo, user_id)
    response = client.put(
        "/api/v1/config",
        headers=user_headers(user_id),
        json={
            "quota_credits": quota_credits,
            "credit_multiplier": credit_multiplier,
        },
    )
    assert response.status_code == 200


def set_used_credits(repo: Repository, user_id: str, credits_used: int) -> None:
    seed_user(repo, user_id)
    repo.set_user_balance(user_id, credits_used=credits_used)


@pytest.fixture
def injectable_client(db_engine):
    """Client that allows injecting a custom MockLLM via app state override."""
    SessionLocal = sessionmaker(bind=db_engine, autocommit=False, autoflush=False)

    def override_get_db():
        db = SessionLocal()
        try:
            yield db
        finally:
            db.close()

    app = create_app()
    app.dependency_overrides[get_db] = override_get_db
    app.state.test_ai_provider = None

    from app.api.routes import generate as generate_routes

    def override_ai_provider():
        if app.state.test_ai_provider is not None:
            return app.state.test_ai_provider
        return MockLLM()

    app.dependency_overrides[generate_routes.get_ai_provider] = override_ai_provider

    with TestClient(app) as test_client:
        yield test_client
