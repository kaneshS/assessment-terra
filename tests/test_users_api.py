import uuid
from datetime import datetime

import pytest


def test_post_users_success_returns_uuid_and_fields(client):
    response = client.post(
        "/api/v1/users",
        json={"name": "Test User", "email": "test.user@example.com"},
    )
    assert response.status_code == 201
    body = response.json()
    assert set(body.keys()) == {"user_id", "name", "email", "created_at"}
    parsed_id = uuid.UUID(body["user_id"])
    assert str(parsed_id) == body["user_id"]
    assert body["name"] == "Test User"
    assert body["email"] == "test.user@example.com"
    datetime.fromisoformat(body["created_at"].replace("Z", "+00:00"))


def test_post_users_missing_name_returns_422(client):
    response = client.post("/api/v1/users", json={"email": "noname@example.com"})
    assert response.status_code == 422


def test_post_users_missing_email_returns_422(client):
    response = client.post("/api/v1/users", json={"name": "No Email"})
    assert response.status_code == 422


def test_post_users_empty_name_returns_422(client):
    response = client.post(
        "/api/v1/users",
        json={"name": "", "email": "empty@example.com"},
    )
    assert response.status_code == 422


def test_post_users_invalid_email_returns_422(client):
    response = client.post(
        "/api/v1/users",
        json={"name": "Bad Email", "email": "not-an-email"},
    )
    assert response.status_code == 422


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"name": "Only Name"},
        {"email": "only@example.com"},
    ],
)
def test_post_users_incomplete_payload_returns_422(client, payload):
    response = client.post("/api/v1/users", json=payload)
    assert response.status_code == 422


def test_post_users_duplicate_email_returns_409_with_error_shape(client):
    email = "dup@example.com"
    first = client.post(
        "/api/v1/users",
        json={"name": "First", "email": email},
    )
    assert first.status_code == 201

    second = client.post(
        "/api/v1/users",
        json={"name": "Second", "email": email},
    )
    assert second.status_code == 409
    body = second.json()
    assert body["error_code"] == "duplicate_email"
    assert body["message"]
    assert body["details"]["email"] == email
