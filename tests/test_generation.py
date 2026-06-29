import uuid

from app.services.metering import DEFAULT_MAX_COMPLETION_TOKENS, estimate_credits
from tests.conftest import (
    ALLOWED,
    BLOCKED,
    BOUNDARY,
    EXHAUSTED,
    FULL,
    HIGH_MULT,
    LOW_MULT,
    OK_USER,
    UNKNOWN,
    USAGE_USER,
    USER1,
    configure_user,
    seed_user,
    set_used_credits,
    user_headers,
)


def test_post_users_creates_user_and_returns_uuid(client):
    response = client.post(
        "/api/v1/users",
        json={"name": "Alice", "email": "alice@example.com"},
    )
    assert response.status_code == 201
    body = response.json()
    uuid.UUID(body["user_id"])
    assert body["name"] == "Alice"
    assert body["email"] == "alice@example.com"
    assert "created_at" in body


def test_create_user_with_name_and_email_returns_fields(client):
    response = client.post(
        "/api/v1/users",
        json={"name": "Bob Smith", "email": "bob.smith@example.com"},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["name"] == "Bob Smith"
    assert body["email"] == "bob.smith@example.com"
    uuid.UUID(body["user_id"])
    assert "created_at" in body


def test_duplicate_email_rejected(client):
    payload = {"name": "Carol", "email": "carol@example.com"}
    first = client.post("/api/v1/users", json=payload)
    assert first.status_code == 201

    second = client.post(
        "/api/v1/users",
        json={"name": "Carol Duplicate", "email": "carol@example.com"},
    )
    assert second.status_code == 409
    body = second.json()
    assert body["error_code"] == "duplicate_email"
    assert body["details"]["email"] == "carol@example.com"


def test_put_config_fails_404_if_user_does_not_exist(client):
    response = client.put(
        "/api/v1/config",
        headers=user_headers(UNKNOWN),
        json={"quota_credits": 100, "credit_multiplier": 1.0},
    )
    assert response.status_code == 404
    assert response.json()["error_code"] == "user_not_found"


def test_generate_unknown_user_returns_404(client):
    response = client.post(
        "/api/v1/generate",
        headers=user_headers(UNKNOWN),
        json={"prompt": "hello"},
    )
    assert response.status_code == 404
    assert response.json()["error_code"] == "user_not_found"


def test_put_config_first_time_sets_quota(client, repo):
    seed_user(repo, USER1)
    response = client.put(
        "/api/v1/config",
        headers=user_headers(USER1),
        json={"quota_credits": 100, "credit_multiplier": 1.0},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["quota_credits"] == 100
    assert body["credits_added"] == 100

    usage = client.get("/api/v1/usage", headers=user_headers(USER1)).json()
    assert usage["quota"] == 100
    assert usage["credits_used"] == 0
    assert usage["credits_remaining"] == 100


def test_full_flow_create_user_config_generate(injectable_client, repo):
    client = injectable_client
    create_response = client.post(
        "/api/v1/users",
        json={"name": "Flow User", "email": "flow@example.com"},
    )
    assert create_response.status_code == 201
    user_id = create_response.json()["user_id"]

    config_response = client.put(
        "/api/v1/config",
        headers=user_headers(user_id),
        json={"quota_credits": 600, "credit_multiplier": 1.0},
    )
    assert config_response.status_code == 200

    generate_response = client.post(
        "/api/v1/generate",
        headers=user_headers(user_id),
        json={"prompt": "hello world"},
    )
    assert generate_response.status_code == 200
    assert generate_response.json()["response_text"].startswith("Echo:")


def test_successful_generation_and_recording(injectable_client, repo):
    client = injectable_client
    configure_user(client, USER1, quota_credits=1000, credit_multiplier=1.0, repo=repo)

    response = client.post(
        "/api/v1/generate",
        headers=user_headers(USER1),
        json={"prompt": "hello world"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["response_text"].startswith("Echo:")
    assert body["actual_credits"] <= body["estimated_credits"]

    usage = client.get("/api/v1/usage", headers=user_headers(USER1)).json()
    assert usage["credits_used"] == body["actual_credits"]
    assert usage["credits_remaining"] == 1000 - body["actual_credits"]

    history = client.get(
        "/api/v1/usage/history", headers=user_headers(USER1)
    ).json()
    assert len(history["records"]) == 1
    assert history["records"][0]["status"] == "succeeded"
    assert history["records"][0]["operation_type"] == "generate"


def test_credit_calculation_with_multiplier(injectable_client, repo):
    client = injectable_client
    configure_user(client, LOW_MULT, quota_credits=2000, credit_multiplier=0.5, repo=repo)
    configure_user(client, HIGH_MULT, quota_credits=2000, credit_multiplier=2.0, repo=repo)

    prompt = "alpha beta gamma delta"
    low = client.post(
        "/api/v1/generate",
        headers=user_headers(LOW_MULT),
        json={"prompt": prompt},
    ).json()
    high = client.post(
        "/api/v1/generate",
        headers=user_headers(HIGH_MULT),
        json={"prompt": prompt},
    ).json()

    assert low["actual_credits"] < high["actual_credits"]


def test_different_users_isolated_quotas(injectable_client, repo):
    client = injectable_client
    configure_user(client, BLOCKED, quota_credits=5, credit_multiplier=1.0, repo=repo)
    configure_user(client, ALLOWED, quota_credits=1000, credit_multiplier=1.0, repo=repo)

    blocked = client.post(
        "/api/v1/generate",
        headers=user_headers(BLOCKED),
        json={"prompt": "one two three four five"},
    )
    assert blocked.status_code == 402

    allowed = client.post(
        "/api/v1/generate",
        headers=user_headers(ALLOWED),
        json={"prompt": "one two three four five"},
    )
    assert allowed.status_code == 200


def test_quota_ok_when_enough_remaining(injectable_client, repo):
    client = injectable_client
    configure_user(client, OK_USER, quota_credits=600, credit_multiplier=1.0, repo=repo)
    set_used_credits(repo, OK_USER, credits_used=50)

    response = client.post(
        "/api/v1/generate",
        headers=user_headers(OK_USER),
        json={"prompt": "one two three four five"},
    )
    assert response.status_code == 200


def test_quota_exceeded_when_no_remaining(injectable_client, repo):
    client = injectable_client
    configure_user(client, EXHAUSTED, quota_credits=100, credit_multiplier=1.0, repo=repo)
    set_used_credits(repo, EXHAUSTED, credits_used=100)

    response = client.post(
        "/api/v1/generate",
        headers=user_headers(EXHAUSTED),
        json={"prompt": "hello"},
    )
    assert response.status_code == 402
    assert response.json()["error_code"] == "quota_exceeded"


def test_get_usage_returns_correct_fields(injectable_client, repo):
    client = injectable_client
    configure_user(client, USAGE_USER, quota_credits=200, credit_multiplier=1.5, repo=repo)
    set_used_credits(repo, USAGE_USER, credits_used=40)

    usage = client.get("/api/v1/usage", headers=user_headers(USAGE_USER)).json()
    assert usage["quota"] == 200
    assert usage["multiplier"] == 1.5
    assert usage["credits_used"] == 40
    assert usage["credits_reserved"] == 0
    assert usage["credits_remaining"] == 160


def test_unconfigured_user_returns_404(client, repo):
    seed_user(repo, UNKNOWN)
    response = client.get("/api/v1/usage", headers=user_headers(UNKNOWN))
    assert response.status_code == 404
    assert response.json()["error_code"] == "user_not_configured"

    gen = client.post(
        "/api/v1/generate",
        headers=user_headers(UNKNOWN),
        json={"prompt": "hello"},
    )
    assert gen.status_code == 404
    assert gen.json()["error_code"] == "user_not_configured"


def test_at_quota_boundary_exact_estimate_allowed(injectable_client, repo):
    client = injectable_client
    prompt = "one two three four five six seven eight nine ten"
    _, estimated = estimate_credits(prompt, DEFAULT_MAX_COMPLETION_TOKENS, 1.0)

    configure_user(client, BOUNDARY, quota_credits=600, credit_multiplier=1.0, repo=repo)
    set_used_credits(repo, BOUNDARY, credits_used=600 - estimated)

    response = client.post(
        "/api/v1/generate",
        headers=user_headers(BOUNDARY),
        json={"prompt": prompt},
    )
    assert response.status_code == 200


def test_at_quota_boundary_zero_remaining_rejects(injectable_client, repo):
    client = injectable_client
    configure_user(client, FULL, quota_credits=100, credit_multiplier=1.0, repo=repo)
    set_used_credits(repo, FULL, credits_used=100)

    response = client.post(
        "/api/v1/generate",
        headers=user_headers(FULL),
        json={"prompt": "hello"},
    )
    assert response.status_code == 402
    assert response.json()["error_code"] == "quota_exceeded"


def test_generate_with_prompt_only(injectable_client, repo):
    client = injectable_client
    configure_user(client, USER1, quota_credits=1000, credit_multiplier=1.0, repo=repo)

    prompt = "hello world"
    _, expected_estimate = estimate_credits(prompt, DEFAULT_MAX_COMPLETION_TOKENS, 1.0)

    response = client.post(
        "/api/v1/generate",
        headers=user_headers(USER1),
        json={"prompt": prompt},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["response_text"].startswith("Echo:")
    assert body["completion_tokens"] == len(body["response_text"].split())
    assert body["estimated_credits"] == expected_estimate


def test_completion_tokens_match_response_length(injectable_client, repo):
    client = injectable_client
    configure_user(client, USER1, quota_credits=1000, credit_multiplier=1.0, repo=repo)

    response = client.post(
        "/api/v1/generate",
        headers=user_headers(USER1),
        json={"prompt": "hello world"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["completion_tokens"] == len(body["response_text"].split())
    assert body["total_tokens"] == body["prompt_tokens"] + body["completion_tokens"]
    assert body["actual_credits"] <= body["estimated_credits"]


def test_missing_user_id_header_returns_422(client):
    response = client.get("/api/v1/usage")
    assert response.status_code == 422
    assert response.json()["error_code"] == "invalid_user_id"


def test_invalid_user_id_header_returns_422(client):
    response = client.get(
        "/api/v1/usage",
        headers={"X-User-Id": "not-a-uuid"},
    )
    assert response.status_code == 422
    body = response.json()
    assert body["error_code"] == "invalid_user_id"
    assert body["details"]["user_id"] == "not-a-uuid"
