from math import ceil
from unittest.mock import MagicMock

from app.services.ai_provider import MockLLM, MockLLMOptions
from app.services.metering import DEFAULT_MAX_COMPLETION_TOKENS, estimate_credits
from tests.conftest import (
    ALICE,
    BOB,
    CAROL,
    EVE,
    FRANK,
    configure_user,
    set_used_credits,
    user_headers,
)


def test_rejected_on_estimate(injectable_client, repo):
    """Scenario 2: alice rejects before AI is called."""
    client = injectable_client
    configure_user(client, ALICE, quota_credits=100, credit_multiplier=0.5, repo=repo)
    set_used_credits(repo, ALICE, credits_used=80)

    mock_llm = MagicMock()
    injectable_client.app.state.test_ai_provider = mock_llm

    prompt = "one two three four five six seven eight nine ten"
    _, estimated = estimate_credits(prompt, DEFAULT_MAX_COMPLETION_TOKENS, 0.5)
    assert estimated == ceil((10 + DEFAULT_MAX_COMPLETION_TOKENS) * 0.5)

    response = injectable_client.post(
        "/api/v1/generate",
        headers=user_headers(ALICE),
        json={"prompt": prompt},
    )
    assert response.status_code == 402
    body = response.json()
    assert body["error_code"] == "insufficient_credits_estimated"
    assert body["details"]["credits_remaining"] == 20
    assert body["details"]["credits_required"] == estimated
    mock_llm.generate.assert_not_called()

    usage = client.get("/api/v1/usage", headers=user_headers(ALICE)).json()
    assert usage["credits_used"] == 80
    assert usage["credits_reserved"] == 0


def test_estimate_vs_actual_success(injectable_client, repo):
    """Scenario 1 subcase A: bob succeeds; actual differs from estimate."""
    client = injectable_client
    configure_user(client, BOB, quota_credits=600, credit_multiplier=1.0, repo=repo)
    set_used_credits(repo, BOB, credits_used=30)

    prompt = "one two three four five six seven eight nine ten"
    _, estimated = estimate_credits(prompt, DEFAULT_MAX_COMPLETION_TOKENS, 1.0)

    injectable_client.app.state.test_ai_provider = MockLLM(
        MockLLMOptions(fixed_total_tokens=45)
    )

    response = client.post(
        "/api/v1/generate",
        headers=user_headers(BOB),
        json={"prompt": prompt},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["estimated_credits"] == estimated
    assert body["actual_credits"] == 45
    assert body["total_tokens"] == 45

    usage = client.get("/api/v1/usage", headers=user_headers(BOB)).json()
    assert usage["credits_used"] == 75
    assert usage["credits_reserved"] == 0
    assert usage["credits_remaining"] == 600 - 75


def test_actual_exceeds_quota_after_generation(injectable_client, repo):
    """Scenario 1 subcase B: carol gets 402 after generation; no response text."""
    client = injectable_client
    configure_user(client, CAROL, quota_credits=600, credit_multiplier=1.0, repo=repo)
    set_used_credits(repo, CAROL, credits_used=10)

    prompt = "one two three four five"
    _, estimated = estimate_credits(prompt, DEFAULT_MAX_COMPLETION_TOKENS, 1.0)

    injectable_client.app.state.test_ai_provider = MockLLM(
        MockLLMOptions(return_high_token_count=True, high_total_tokens=591)
    )

    response = client.post(
        "/api/v1/generate",
        headers=user_headers(CAROL),
        json={"prompt": prompt},
    )
    assert response.status_code == 402
    body = response.json()
    assert body["error_code"] == "insufficient_credits_actual"
    assert "response_text" not in body

    usage = client.get("/api/v1/usage", headers=user_headers(CAROL)).json()
    assert usage["credits_used"] == 10
    assert usage["credits_reserved"] == 0

    history = client.get(
        "/api/v1/usage/history", headers=user_headers(CAROL)
    ).json()
    assert len(history["records"]) == 1
    record = history["records"][0]
    assert record["status"] == "insufficient_credits_actual"
    assert record["total_tokens"] == 591
    assert record["actual_credits"] == 591
    assert record["response"] is None


def test_multiplier_update_affects_next_request_only(injectable_client, repo):
    """Scenario 4: eve multiplier change applies to future requests only."""
    client = injectable_client
    configure_user(client, EVE, quota_credits=1200, credit_multiplier=0.5, repo=repo)

    prompt = "one two three four five six seven eight nine ten"
    injectable_client.app.state.test_ai_provider = MockLLM(
        MockLLMOptions(fixed_total_tokens=100)
    )

    first = client.post(
        "/api/v1/generate",
        headers=user_headers(EVE),
        json={"prompt": prompt},
    )
    assert first.status_code == 200
    assert first.json()["total_tokens"] == 100
    assert first.json()["actual_credits"] == 50

    history_before = client.get(
        "/api/v1/usage/history", headers=user_headers(EVE)
    ).json()
    old_record = history_before["records"][0]
    assert old_record["multiplier_at_time"] == 0.5
    assert old_record["actual_credits"] == 50

    configure_user(client, EVE, quota_credits=0, credit_multiplier=1.0, repo=repo)

    second = client.post(
        "/api/v1/generate",
        headers=user_headers(EVE),
        json={"prompt": prompt},
    )
    assert second.status_code == 200
    assert second.json()["actual_credits"] == 100

    history = client.get(
        "/api/v1/usage/history", headers=user_headers(EVE)
    ).json()
    assert history["records"][0]["multiplier_at_time"] == 1.0
    assert history["records"][0]["actual_credits"] == 100
    assert history["records"][1]["multiplier_at_time"] == 0.5
    assert history["records"][1]["actual_credits"] == 50


def test_inflight_uses_snapshotted_quota(injectable_client, repo):
    """Scenario 4: frank in-flight request uses snapshotted quota."""
    client = injectable_client
    configure_user(client, FRANK, quota_credits=100, credit_multiplier=1.0, repo=repo)
    set_used_credits(repo, FRANK, credits_used=60)

    prompt = "one two three four five six seven eight nine ten"
    _, estimated = estimate_credits(prompt, 20, 1.0)
    assert estimated == 30

    mock_llm = MockLLM(MockLLMOptions(fixed_total_tokens=30))
    reservation = repo.reserve_credits(
        user_id=FRANK,
        estimated_credits=estimated,
        prompt=prompt,
    )
    assert reservation.quota_at_time == 100
    assert reservation.estimated_credits == 30

    configure_user(client, FRANK, quota_credits=50, credit_multiplier=1.0, repo=repo)

    result = mock_llm.generate(prompt, 20)
    actual_credits = ceil(result.total_tokens * reservation.multiplier_at_time)
    assert actual_credits == 30
    assert 60 + actual_credits <= reservation.quota_at_time

    usage_record = repo.reconcile_success(
        reservation_id=reservation.reservation_id,
        usage_record_id=reservation.usage_record_id,
        response_text=result.text,
        prompt_tokens=result.prompt_tokens,
        completion_tokens=result.completion_tokens,
        total_tokens=result.total_tokens,
        actual_credits=actual_credits,
    )
    assert usage_record.status == "succeeded"

    usage = client.get("/api/v1/usage", headers=user_headers(FRANK)).json()
    assert usage["quota"] == 150
    assert usage["credits_used"] == 90
    assert usage["credits_remaining"] == 60

    configure_user(client, FRANK, quota_credits=500, credit_multiplier=1.0, repo=repo)

    allowed = client.post(
        "/api/v1/generate",
        headers=user_headers(FRANK),
        json={"prompt": "one two"},
    )
    assert allowed.status_code == 200


def test_put_config_adds_credits_to_existing_quota(injectable_client, repo):
    """PUT /config increments quota; used credits unchanged; remaining increases."""
    client = injectable_client
    configure_user(client, ALICE, quota_credits=100, credit_multiplier=1.0, repo=repo)
    set_used_credits(repo, ALICE, credits_used=40)

    response = client.put(
        "/api/v1/config",
        headers=user_headers(ALICE),
        json={"quota_credits": 10, "credit_multiplier": 1.0},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["quota_credits"] == 110
    assert body["credits_added"] == 10
    assert body["credit_multiplier"] == 1.0

    usage = client.get("/api/v1/usage", headers=user_headers(ALICE)).json()
    assert usage["quota"] == 110
    assert usage["credits_used"] == 40
    assert usage["credits_remaining"] == 70
