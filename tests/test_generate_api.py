import uuid

from app.services.ai_provider import MockLLM, MockLLMOptions
from app.services.metering import DEFAULT_MAX_COMPLETION_TOKENS, estimate_credits
from tests.conftest import (
    ALICE,
    CAROL,
    GEN_USER,
    MULTI_GEN_USER,
    UNKNOWN,
    configure_user,
    seed_user,
    set_used_credits,
    user_headers,
)


def test_generate_success_response_has_all_fields(injectable_client, repo):
    client = injectable_client
    configure_user(client, GEN_USER, quota_credits=1000, credit_multiplier=1.0, repo=repo)

    response = client.post(
        "/api/v1/generate",
        headers=user_headers(GEN_USER),
        json={"prompt": "hello world"},
    )
    assert response.status_code == 200
    body = response.json()
    expected_keys = {
        "response_text",
        "prompt_tokens",
        "completion_tokens",
        "total_tokens",
        "estimated_credits",
        "actual_credits",
        "credits_remaining",
        "usage_record_id",
    }
    assert set(body.keys()) == expected_keys
    assert body["response_text"].startswith("Echo:")
    assert body["total_tokens"] == body["prompt_tokens"] + body["completion_tokens"]
    assert isinstance(body["usage_record_id"], int)


def test_generate_prompt_only_uses_internal_512_cap(injectable_client, repo):
    client = injectable_client
    configure_user(client, GEN_USER, quota_credits=5000, credit_multiplier=1.0, repo=repo)

    prompt = "alpha beta gamma"
    _, expected_estimate = estimate_credits(prompt, DEFAULT_MAX_COMPLETION_TOKENS, 1.0)

    response = client.post(
        "/api/v1/generate",
        headers=user_headers(GEN_USER),
        json={"prompt": prompt},
    )
    assert response.status_code == 200
    assert response.json()["estimated_credits"] == expected_estimate


def test_generate_quota_exceeded_pre_check_returns_402_with_error_shape(
    injectable_client, repo
):
    client = injectable_client
    configure_user(client, GEN_USER, quota_credits=100, credit_multiplier=1.0, repo=repo)
    set_used_credits(repo, GEN_USER, credits_used=100)

    response = client.post(
        "/api/v1/generate",
        headers=user_headers(GEN_USER),
        json={"prompt": "hello"},
    )
    assert response.status_code == 402
    body = response.json()
    assert body["error_code"] == "quota_exceeded"
    assert body["message"]
    assert "credits_remaining" in body["details"]


def test_generate_insufficient_credits_estimated_returns_402_with_error_shape(
    injectable_client, repo
):
    client = injectable_client
    configure_user(client, ALICE, quota_credits=100, credit_multiplier=1.0, repo=repo)
    set_used_credits(repo, ALICE, credits_used=80)

    prompt = "one two three four five six seven eight nine ten"
    _, estimated = estimate_credits(prompt, DEFAULT_MAX_COMPLETION_TOKENS, 1.0)

    response = client.post(
        "/api/v1/generate",
        headers=user_headers(ALICE),
        json={"prompt": prompt},
    )
    assert response.status_code == 402
    body = response.json()
    assert body["error_code"] == "insufficient_credits_estimated"
    assert body["details"]["credits_remaining"] == 20
    assert body["details"]["credits_required"] == estimated


def test_generate_pre_check_rejection_does_not_create_usage_record(
    injectable_client, repo
):
    client = injectable_client
    configure_user(client, ALICE, quota_credits=50, credit_multiplier=1.0, repo=repo)
    set_used_credits(repo, ALICE, credits_used=45)

    response = client.post(
        "/api/v1/generate",
        headers=user_headers(ALICE),
        json={"prompt": "one two three four five six seven eight nine ten"},
    )
    assert response.status_code == 402

    history = client.get(
        "/api/v1/usage/history", headers=user_headers(ALICE)
    ).json()
    assert history["records"] == []


def test_generate_post_generation_quota_exceeded_returns_402_with_error_shape(
    injectable_client, repo
):
    client = injectable_client
    configure_user(client, CAROL, quota_credits=600, credit_multiplier=1.0, repo=repo)
    set_used_credits(repo, CAROL, credits_used=10)

    client.app.state.test_ai_provider = MockLLM(
        MockLLMOptions(return_high_token_count=True, high_total_tokens=591)
    )

    response = client.post(
        "/api/v1/generate",
        headers=user_headers(CAROL),
        json={"prompt": "one two three four five"},
    )
    assert response.status_code == 402
    body = response.json()
    assert body["error_code"] == "insufficient_credits_actual"
    assert body["message"]
    assert "response_text" not in body
    assert "actual_credits" in body["details"]


def test_generate_user_not_found_returns_404(client):
    missing = str(uuid.uuid4())
    response = client.post(
        "/api/v1/generate",
        headers=user_headers(missing),
        json={"prompt": "hello"},
    )
    assert response.status_code == 404
    body = response.json()
    assert body["error_code"] == "user_not_found"
    assert body["details"]["user_id"] == missing


def test_generate_user_not_configured_returns_404(client, repo):
    seed_user(repo, UNKNOWN)
    response = client.post(
        "/api/v1/generate",
        headers=user_headers(UNKNOWN),
        json={"prompt": "hello"},
    )
    assert response.status_code == 404
    assert response.json()["error_code"] == "user_not_configured"


def test_generate_ai_failure_pre_usage_returns_502_with_error_shape(
    injectable_client, repo
):
    client = injectable_client
    configure_user(client, GEN_USER, quota_credits=600, credit_multiplier=1.0, repo=repo)
    client.app.state.test_ai_provider = MockLLM(
        MockLLMOptions(fail_before_usage=True)
    )

    response = client.post(
        "/api/v1/generate",
        headers=user_headers(GEN_USER),
        json={"prompt": "hello"},
    )
    assert response.status_code == 502
    body = response.json()
    assert body["error_code"] == "generation_failed"
    assert body["details"]["stage"] == "pre_usage"


def test_generate_ai_failure_partial_returns_502_with_error_shape(
    injectable_client, repo
):
    client = injectable_client
    configure_user(client, GEN_USER, quota_credits=600, credit_multiplier=1.0, repo=repo)
    client.app.state.test_ai_provider = MockLLM(
        MockLLMOptions(fail_after_partial=True)
    )

    response = client.post(
        "/api/v1/generate",
        headers=user_headers(GEN_USER),
        json={"prompt": "one two three"},
    )
    assert response.status_code == 502
    body = response.json()
    assert body["error_code"] == "generation_failed"
    assert body["details"]["stage"] == "partial"
    assert body["details"]["charged_credits"] > 0


def test_generate_usage_record_created_on_success(injectable_client, repo):
    client = injectable_client
    configure_user(client, GEN_USER, quota_credits=1000, credit_multiplier=1.0, repo=repo)

    response = client.post(
        "/api/v1/generate",
        headers=user_headers(GEN_USER),
        json={"prompt": "record me"},
    )
    assert response.status_code == 200
    record_id = response.json()["usage_record_id"]

    record = client.get(
        "/api/v1/usage/history", headers=user_headers(GEN_USER)
    ).json()["records"][0]
    assert record["id"] == record_id
    assert record["status"] == "succeeded"


def test_generate_usage_record_created_on_post_generation_failure(
    injectable_client, repo
):
    client = injectable_client
    configure_user(client, CAROL, quota_credits=600, credit_multiplier=1.0, repo=repo)
    set_used_credits(repo, CAROL, credits_used=10)

    client.app.state.test_ai_provider = MockLLM(
        MockLLMOptions(return_high_token_count=True, high_total_tokens=591)
    )

    response = client.post(
        "/api/v1/generate",
        headers=user_headers(CAROL),
        json={"prompt": "one two three four five"},
    )
    assert response.status_code == 402

    record = client.get(
        "/api/v1/usage/history", headers=user_headers(CAROL)
    ).json()["records"][0]
    assert record["status"] == "insufficient_credits_actual"
    assert record["actual_credits"] == 591


def test_generate_usage_record_created_on_ai_failure(injectable_client, repo):
    client = injectable_client
    configure_user(client, GEN_USER, quota_credits=600, credit_multiplier=1.0, repo=repo)
    client.app.state.test_ai_provider = MockLLM(
        MockLLMOptions(fail_before_usage=True)
    )

    response = client.post(
        "/api/v1/generate",
        headers=user_headers(GEN_USER),
        json={"prompt": "fail me"},
    )
    assert response.status_code == 502

    record = client.get(
        "/api/v1/usage/history", headers=user_headers(GEN_USER)
    ).json()["records"][0]
    assert record["status"] == "failed_pre_usage"
    assert record["actual_credits"] is None


def test_generate_missing_prompt_returns_422(client, repo):
    configure_user(client, GEN_USER, quota_credits=100, credit_multiplier=1.0, repo=repo)
    response = client.post(
        "/api/v1/generate",
        headers=user_headers(GEN_USER),
        json={},
    )
    assert response.status_code == 422


def test_generate_empty_prompt_returns_422(client, repo):
    configure_user(client, GEN_USER, quota_credits=100, credit_multiplier=1.0, repo=repo)
    response = client.post(
        "/api/v1/generate",
        headers=user_headers(GEN_USER),
        json={"prompt": ""},
    )
    assert response.status_code == 422


def test_generate_missing_user_id_header_returns_422(client, repo):
    configure_user(client, GEN_USER, quota_credits=100, credit_multiplier=1.0, repo=repo)
    response = client.post(
        "/api/v1/generate",
        json={"prompt": "hello"},
    )
    assert response.status_code == 422
    assert response.json()["error_code"] == "invalid_user_id"


def test_multiple_generates_decrement_credits_correctly(injectable_client, repo):
    client = injectable_client
    configure_user(
        client, MULTI_GEN_USER, quota_credits=2000, credit_multiplier=1.0, repo=repo
    )

    first = client.post(
        "/api/v1/generate",
        headers=user_headers(MULTI_GEN_USER),
        json={"prompt": "first call"},
    )
    second = client.post(
        "/api/v1/generate",
        headers=user_headers(MULTI_GEN_USER),
        json={"prompt": "second call"},
    )
    assert first.status_code == 200
    assert second.status_code == 200

    total_charged = first.json()["actual_credits"] + second.json()["actual_credits"]
    usage = client.get(
        "/api/v1/usage", headers=user_headers(MULTI_GEN_USER)
    ).json()
    assert usage["credits_used"] == total_charged
    assert usage["credits_remaining"] == 2000 - total_charged
    assert len(client.get(
        "/api/v1/usage/history", headers=user_headers(MULTI_GEN_USER)
    ).json()["records"]) == 2
