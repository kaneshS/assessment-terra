from app.services.ai_provider import MockLLM, MockLLMOptions
from tests.conftest import (
    FAIL_PARTIAL,
    FAIL_PRE,
    HEADER_HIGH,
    HEADER_USER,
    configure_user,
    set_used_credits,
    user_headers,
)


def test_ai_failure_before_usage_releases_reservation(injectable_client, repo):
    client = injectable_client
    configure_user(client, FAIL_PRE, quota_credits=600, credit_multiplier=1.0, repo=repo)

    client.app.state.test_ai_provider = MockLLM(
        MockLLMOptions(fail_before_usage=True)
    )

    response = client.post(
        "/api/v1/generate",
        headers=user_headers(FAIL_PRE),
        json={"prompt": "hello world"},
    )
    assert response.status_code == 502
    body = response.json()
    assert body["error_code"] == "generation_failed"
    assert body["details"]["stage"] == "pre_usage"

    usage = client.get("/api/v1/usage", headers=user_headers(FAIL_PRE)).json()
    assert usage["credits_used"] == 0
    assert usage["credits_reserved"] == 0

    history = client.get(
        "/api/v1/usage/history", headers=user_headers(FAIL_PRE)
    ).json()
    assert history["records"][0]["status"] == "failed_pre_usage"
    assert history["records"][0]["actual_credits"] is None


def test_ai_failure_after_partial_charges_partial(injectable_client, repo):
    client = injectable_client
    configure_user(client, FAIL_PARTIAL, quota_credits=600, credit_multiplier=1.0, repo=repo)
    set_used_credits(repo, FAIL_PARTIAL, credits_used=10)

    client.app.state.test_ai_provider = MockLLM(
        MockLLMOptions(fail_after_partial=True)
    )

    response = client.post(
        "/api/v1/generate",
        headers=user_headers(FAIL_PARTIAL),
        json={"prompt": "one two three"},
    )
    assert response.status_code == 502
    body = response.json()
    assert body["error_code"] == "generation_failed"
    assert body["details"]["stage"] == "partial"
    assert body["details"]["charged_credits"] > 0

    usage = client.get(
        "/api/v1/usage", headers=user_headers(FAIL_PARTIAL)
    ).json()
    assert usage["credits_used"] == 10 + body["details"]["charged_credits"]
    assert usage["credits_reserved"] == 0

    history = client.get(
        "/api/v1/usage/history", headers=user_headers(FAIL_PARTIAL)
    ).json()
    assert history["records"][0]["status"] == "failed_partial"
    assert history["records"][0]["actual_credits"] == body["details"]["charged_credits"]


def test_mock_headers_for_demo(client, repo):
    configure_user(client, HEADER_USER, quota_credits=600, credit_multiplier=1.0, repo=repo)

    response = client.post(
        "/api/v1/generate",
        headers=user_headers(HEADER_USER, **{"X-Mock-Fail-Before-Usage": "true"}),
        json={"prompt": "hello"},
    )
    assert response.status_code == 502
    assert response.json()["error_code"] == "generation_failed"

    configure_user(client, HEADER_HIGH, quota_credits=600, credit_multiplier=1.0, repo=repo)
    response = client.post(
        "/api/v1/generate",
        headers=user_headers(HEADER_HIGH, **{"X-Mock-High-Tokens": "true"}),
        json={"prompt": "one two three four five"},
    )
    assert response.status_code == 200
    assert response.json()["total_tokens"] == 55
