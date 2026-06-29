import uuid

from app.services.metering import DEFAULT_MAX_COMPLETION_TOKENS, estimate_credits
from tests.conftest import (
    CONFIG_USER,
    GEN_USER,
    HISTORY_USER,
    RESERVE_USER,
    UNKNOWN,
    USER1,
    configure_user,
    seed_user,
    set_used_credits,
    user_headers,
)


def test_put_config_first_time_response_shape(client, repo):
    seed_user(repo, CONFIG_USER)
    response = client.put(
        "/api/v1/config",
        headers=user_headers(CONFIG_USER),
        json={"quota_credits": 250, "credit_multiplier": 1.5},
    )
    assert response.status_code == 200
    body = response.json()
    assert set(body.keys()) == {
        "user_id",
        "quota_credits",
        "credits_added",
        "credit_multiplier",
        "updated_at",
    }
    assert body["user_id"] == CONFIG_USER
    assert body["quota_credits"] == 250
    assert body["credits_added"] == 250
    assert body["credit_multiplier"] == 1.5


def test_put_config_multiplier_only_replaces_without_adding_quota(client, repo):
    seed_user(repo, CONFIG_USER)
    client.put(
        "/api/v1/config",
        headers=user_headers(CONFIG_USER),
        json={"quota_credits": 100, "credit_multiplier": 0.5},
    )

    response = client.put(
        "/api/v1/config",
        headers=user_headers(CONFIG_USER),
        json={"quota_credits": 0, "credit_multiplier": 2.0},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["quota_credits"] == 100
    assert body["credits_added"] == 0
    assert body["credit_multiplier"] == 2.0

    usage = client.get("/api/v1/usage", headers=user_headers(CONFIG_USER)).json()
    assert usage["quota"] == 100
    assert usage["multiplier"] == 2.0


def test_put_config_adds_credits_without_changing_used(injectable_client, repo):
    client = injectable_client
    configure_user(client, USER1, quota_credits=100, credit_multiplier=1.0, repo=repo)
    set_used_credits(repo, USER1, credits_used=30)

    response = client.put(
        "/api/v1/config",
        headers=user_headers(USER1),
        json={"quota_credits": 50, "credit_multiplier": 1.0},
    )
    assert response.status_code == 200
    assert response.json()["credits_added"] == 50

    usage = client.get("/api/v1/usage", headers=user_headers(USER1)).json()
    assert usage["quota"] == 150
    assert usage["credits_used"] == 30
    assert usage["credits_remaining"] == 120


def test_put_config_user_not_found_returns_404(client):
    missing = str(uuid.uuid4())
    response = client.put(
        "/api/v1/config",
        headers=user_headers(missing),
        json={"quota_credits": 100, "credit_multiplier": 1.0},
    )
    assert response.status_code == 404
    body = response.json()
    assert body["error_code"] == "user_not_found"
    assert body["details"]["user_id"] == missing


def test_put_config_missing_user_id_header_returns_422(client):
    response = client.put(
        "/api/v1/config",
        json={"quota_credits": 100, "credit_multiplier": 1.0},
    )
    assert response.status_code == 422
    assert response.json()["error_code"] == "invalid_user_id"


def test_put_config_invalid_user_id_header_returns_422(client):
    response = client.put(
        "/api/v1/config",
        headers={"X-User-Id": "bad-id"},
        json={"quota_credits": 100, "credit_multiplier": 1.0},
    )
    assert response.status_code == 422
    body = response.json()
    assert body["error_code"] == "invalid_user_id"
    assert body["details"]["user_id"] == "bad-id"


def test_put_config_invalid_multiplier_returns_422(client, repo):
    seed_user(repo, CONFIG_USER)
    response = client.put(
        "/api/v1/config",
        headers=user_headers(CONFIG_USER),
        json={"quota_credits": 100, "credit_multiplier": 0},
    )
    assert response.status_code == 422


def test_put_config_negative_quota_credits_returns_422(client, repo):
    seed_user(repo, CONFIG_USER)
    response = client.put(
        "/api/v1/config",
        headers=user_headers(CONFIG_USER),
        json={"quota_credits": -1, "credit_multiplier": 1.0},
    )
    assert response.status_code == 422


def test_get_usage_user_not_found_returns_404(client):
    missing = str(uuid.uuid4())
    response = client.get("/api/v1/usage", headers=user_headers(missing))
    assert response.status_code == 404
    assert response.json()["error_code"] == "user_not_found"


def test_get_usage_unconfigured_user_returns_404(client, repo):
    seed_user(repo, UNKNOWN)
    response = client.get("/api/v1/usage", headers=user_headers(UNKNOWN))
    assert response.status_code == 404
    assert response.json()["error_code"] == "user_not_configured"


def test_get_usage_after_generate_updates_correctly(injectable_client, repo):
    client = injectable_client
    configure_user(client, GEN_USER, quota_credits=2000, credit_multiplier=1.0, repo=repo)

    before = client.get("/api/v1/usage", headers=user_headers(GEN_USER)).json()
    assert before["credits_used"] == 0
    assert before["credits_remaining"] == 2000

    gen = client.post(
        "/api/v1/generate",
        headers=user_headers(GEN_USER),
        json={"prompt": "hello world"},
    )
    assert gen.status_code == 200
    actual = gen.json()["actual_credits"]

    after = client.get("/api/v1/usage", headers=user_headers(GEN_USER)).json()
    assert after["credits_used"] == actual
    assert after["credits_reserved"] == 0
    assert after["credits_remaining"] == 2000 - actual


def test_get_usage_shows_credits_reserved_during_in_flight(client, repo):
    configure_user(client, RESERVE_USER, quota_credits=2000, credit_multiplier=1.0, repo=repo)
    prompt = "one two three"
    _, estimated = estimate_credits(prompt, DEFAULT_MAX_COMPLETION_TOKENS, 1.0)

    repo.reserve_credits(
        user_id=RESERVE_USER,
        estimated_credits=estimated,
        prompt=prompt,
    )

    usage = client.get("/api/v1/usage", headers=user_headers(RESERVE_USER)).json()
    assert usage["credits_reserved"] == estimated
    assert usage["credits_remaining"] == 2000 - estimated


def test_get_usage_history_empty_returns_empty_list(client, repo):
    configure_user(client, HISTORY_USER, quota_credits=100, credit_multiplier=1.0, repo=repo)

    response = client.get(
        "/api/v1/usage/history", headers=user_headers(HISTORY_USER)
    )
    assert response.status_code == 200
    body = response.json()
    assert body["records"] == []
    assert body["limit"] == 50
    assert body["offset"] == 0


def test_get_usage_history_newest_first(injectable_client, repo):
    client = injectable_client
    configure_user(client, HISTORY_USER, quota_credits=2000, credit_multiplier=1.0, repo=repo)

    for prompt in ("first prompt", "second prompt", "third prompt"):
        response = client.post(
            "/api/v1/generate",
            headers=user_headers(HISTORY_USER),
            json={"prompt": prompt},
        )
        assert response.status_code == 200

    history = client.get(
        "/api/v1/usage/history", headers=user_headers(HISTORY_USER)
    ).json()
    assert len(history["records"]) == 3
    assert history["records"][0]["prompt"] == "third prompt"
    assert history["records"][1]["prompt"] == "second prompt"
    assert history["records"][2]["prompt"] == "first prompt"


def test_get_usage_history_pagination_limit_offset(injectable_client, repo):
    client = injectable_client
    configure_user(client, HISTORY_USER, quota_credits=5000, credit_multiplier=1.0, repo=repo)

    for i in range(5):
        client.post(
            "/api/v1/generate",
            headers=user_headers(HISTORY_USER),
            json={"prompt": f"prompt number {i}"},
        )

    page = client.get(
        "/api/v1/usage/history",
        headers=user_headers(HISTORY_USER),
        params={"limit": 2, "offset": 1},
    ).json()
    assert page["limit"] == 2
    assert page["offset"] == 1
    assert len(page["records"]) == 2
    assert page["records"][0]["prompt"] == "prompt number 3"
    assert page["records"][1]["prompt"] == "prompt number 2"


def test_get_usage_history_record_fields(injectable_client, repo):
    client = injectable_client
    configure_user(client, HISTORY_USER, quota_credits=1000, credit_multiplier=1.5, repo=repo)

    gen = client.post(
        "/api/v1/generate",
        headers=user_headers(HISTORY_USER),
        json={"prompt": "field check prompt"},
    )
    assert gen.status_code == 200
    gen_body = gen.json()

    record = client.get(
        "/api/v1/usage/history", headers=user_headers(HISTORY_USER)
    ).json()["records"][0]

    assert record["id"] == gen_body["usage_record_id"]
    assert record["user_id"] == HISTORY_USER
    assert record["prompt"] == "field check prompt"
    assert record["response"] == gen_body["response_text"]
    assert record["prompt_tokens"] == gen_body["prompt_tokens"]
    assert record["completion_tokens"] == gen_body["completion_tokens"]
    assert record["total_tokens"] == gen_body["total_tokens"]
    assert record["estimated_credits"] == gen_body["estimated_credits"]
    assert record["actual_credits"] == gen_body["actual_credits"]
    assert record["multiplier_at_time"] == 1.5
    assert record["quota_at_time"] == 1000
    assert record["operation_type"] == "generate"
    assert record["status"] == "succeeded"
    assert record["created_at"]


def test_get_usage_history_user_not_found_returns_404(client):
    missing = str(uuid.uuid4())
    response = client.get(
        "/api/v1/usage/history", headers=user_headers(missing)
    )
    assert response.status_code == 404
    assert response.json()["error_code"] == "user_not_found"


def test_get_usage_history_unconfigured_user_returns_404(client, repo):
    seed_user(repo, UNKNOWN)
    response = client.get(
        "/api/v1/usage/history", headers=user_headers(UNKNOWN)
    )
    assert response.status_code == 404
    assert response.json()["error_code"] == "user_not_configured"
