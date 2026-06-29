import threading
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.exceptions import AppError
from app.db.models import Base
from app.db.repository import Repository
from app.services.ai_provider import MockLLM
from app.services.generation import GenerationService
from app.services.metering import DEFAULT_MAX_COMPLETION_TOKENS, estimate_credits
from tests.conftest import DAVE


@pytest.fixture
def concurrent_engine(tmp_path: Path):
    db_file = tmp_path / "concurrent.db"
    engine = create_engine(
        f"sqlite:///{db_file}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(bind=engine)
    yield engine
    Base.metadata.drop_all(bind=engine)
    engine.dispose()


def test_concurrent_requests_one_succeeds(concurrent_engine):
    """Scenario 3: dave concurrent requests; only one succeeds."""
    SessionLocal = sessionmaker(bind=concurrent_engine, autocommit=False, autoflush=False)

    prompt = "one two"
    _, estimated = estimate_credits(prompt, DEFAULT_MAX_COMPLETION_TOKENS, 1.0)

    setup_session = SessionLocal()
    setup_repo = Repository(setup_session)
    setup_repo.create_user(
        user_id=DAVE,
        name="Dave",
        email="dave@example.com",
    )
    setup_repo.upsert_user_config(DAVE, credits_to_add=1000, credit_multiplier=1.0)
    setup_repo.set_user_balance(DAVE, credits_used=485)
    setup_session.close()

    barrier = threading.Barrier(2)
    results: list[tuple[str, object]] = []
    lock = threading.Lock()

    def run_request() -> None:
        session = SessionLocal()
        try:
            service = GenerationService(repository=Repository(session), ai_provider=MockLLM())
            barrier.wait()
            try:
                result = service.generate(
                    user_id=DAVE,
                    prompt=prompt,
                )
                with lock:
                    results.append(("success", result))
            except AppError as exc:
                with lock:
                    results.append(("error", exc))
        finally:
            session.close()

    threads = [threading.Thread(target=run_request) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    assert len(results) == 2
    outcomes = {name for name, _ in results}
    assert outcomes == {"success", "error"}

    error = next(payload for name, payload in results if name == "error")
    assert error.error_code == "insufficient_credits_estimated"

    success = next(payload for name, payload in results if name == "success")
    verify_session = SessionLocal()
    usage = Repository(verify_session).get_usage_summary(DAVE)
    verify_session.close()
    initial_used = 485
    assert usage.credits_used == initial_used + success.actual_credits
    assert usage.credits_reserved == 0
    assert usage.credits_remaining == 1000 - usage.credits_used
