# AI Usage Metering and Quota Service

## Requirements

- Python 3.11+
- pip

## Quick Start

Copy and paste these steps to run the service locally with the mock AI provider (no model download).

1. **Clone and enter the repo**
  ```bash
   git clone <your-repo-url>
   cd terrabase-assignment
  ```
2. **Create a virtual environment and install dependencies**
  ```bash
   python -m venv .venv
   source .venv/bin/activate   # Windows: .venv\Scripts\activate
   export AI_PROVIDER=mock
   pip install -e ".[dev]"
  ```
3. **Start the API server**
  ```bash
   uvicorn app.main:app --reload
  ```
4. **Create a user, configure quota, generate text, and check usage** (run in a second terminal while the server is up)
  ```bash
   USER_ID=$(curl -s -X POST http://127.0.0.1:8000/api/v1/users \
     -H "Content-Type: application/json" \
     -d '{"name": "Alice", "email": "alice@example.com"}' \
     | python -c "import sys, json; print(json.load(sys.stdin)['user_id'])")

   curl -X PUT http://127.0.0.1:8000/api/v1/config \
     -H "Content-Type: application/json" \
     -H "X-User-Id: $USER_ID" \
     -d '{"quota_credits": 100, "credit_multiplier": 0.5}'

   curl -X POST http://127.0.0.1:8000/api/v1/generate \
     -H "Content-Type: application/json" \
     -H "X-User-Id: $USER_ID" \
     -d '{"prompt": "hello world"}'

   curl http://127.0.0.1:8000/api/v1/usage \
     -H "X-User-Id: $USER_ID"
  ```
5. **Open interactive API docs:** [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)

## Project layout

`app/` (FastAPI service), `tests/` (pytest suite), `DESIGN.md` (architecture and consistency challenges). See [DESIGN.md](DESIGN.md) for layered structure, quota logic, and concurrency design.

## API endpoints

All routes use the prefix `/api/v1` (override with `AI_QUOTA_API_PREFIX`).


| Method | Path                    | Auth header |
| ------ | ----------------------- | ----------- |
| POST   | `/api/v1/users`         | None        |
| PUT    | `/api/v1/config`        | `X-User-Id` |
| POST   | `/api/v1/generate`      | `X-User-Id` |
| GET    | `/api/v1/usage`         | `X-User-Id` |
| GET    | `/api/v1/usage/history` | `X-User-Id` |


## Setup (detailed)

### Mock provider (recommended for first run)

No HuggingFace model download (~1GB). Fast startup, deterministic responses, same API behavior.

```bash
cd terrabase-assignment
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
export AI_PROVIDER=mock
pip install -e ".[dev]"
```

### Real LLM (optional)

Uses [Qwen/Qwen2.5-0.5B-Instruct](https://huggingface.co/Qwen/Qwen2.5-0.5B-Instruct) via HuggingFace `transformers`. The model downloads automatically on the first `/generate` request. CPU inference works but can be slow (several seconds per request).

```bash
pip install -e ".[dev,local]"
# AI_PROVIDER defaults to local; omit export AI_PROVIDER=mock
uvicorn app.main:app --reload
```

## Run the API

```bash
uvicorn app.main:app --reload
```

Interactive API docs: [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)

## Example requests

Create a user (no `X-User-Id` header required). Save the returned `user_id` for all other endpoints:

```bash
USER_ID=$(curl -s -X POST http://127.0.0.1:8000/api/v1/users \
  -H "Content-Type: application/json" \
  -d '{"name": "Alice", "email": "alice@example.com"}' \
  | python -c "import sys, json; print(json.load(sys.stdin)['user_id'])")
```

Configure a user (sets initial quota; subsequent calls **add** credits):

```bash
curl -X PUT http://127.0.0.1:8000/api/v1/config \
  -H "Content-Type: application/json" \
  -H "X-User-Id: $USER_ID" \
  -d '{"quota_credits": 100, "credit_multiplier": 0.5}'
```

Add more credits later (e.g. +10 on top of existing allowance):

```bash
curl -X PUT http://127.0.0.1:8000/api/v1/config \
  -H "Content-Type: application/json" \
  -H "X-User-Id: $USER_ID" \
  -d '{"quota_credits": 10, "credit_multiplier": 0.5}'
```

All endpoints below require an `X-User-Id` header with a valid UUID for an existing user.

Generate text (billing uses actual generated tokens; pre-request estimates assume an internal completion cap of 512):

```bash
curl -X POST http://127.0.0.1:8000/api/v1/generate \
  -H "Content-Type: application/json" \
  -H "X-User-Id: $USER_ID" \
  -d '{"prompt": "hello world"}'
```

Check usage:

```bash
curl http://127.0.0.1:8000/api/v1/usage \
  -H "X-User-Id: $USER_ID"
```

View usage history:

```bash
curl http://127.0.0.1:8000/api/v1/usage/history \
  -H "X-User-Id: $USER_ID"
```

Trigger quota rejection (create user, exhaust credits, then request again):

```bash
USER_ID=$(curl -s -X POST http://127.0.0.1:8000/api/v1/users \
  -H "Content-Type: application/json" \
  -d '{"name": "Quota User", "email": "quota@example.com"}' \
  | python -c "import sys, json; print(json.load(sys.stdin)['user_id'])")

curl -X PUT http://127.0.0.1:8000/api/v1/config \
  -H "Content-Type: application/json" \
  -H "X-User-Id: $USER_ID" \
  -d '{"quota_credits": 10, "credit_multiplier": 1.0}'

curl -X POST http://127.0.0.1:8000/api/v1/generate \
  -H "Content-Type: application/json" \
  -H "X-User-Id: $USER_ID" \
  -d '{"prompt": "one two three four five six seven eight nine ten"}'
```

Simulate AI failure (dev headers; works with `AI_PROVIDER=mock`, or with `AI_PROVIDER=local` when a mock header is present):

```bash
curl -X POST http://127.0.0.1:8000/api/v1/generate \
  -H "Content-Type: application/json" \
  -H "X-User-Id: $USER_ID" \
  -H "X-Mock-Fail-Before-Usage: true" \
  -d '{"prompt": "hello"}'
```

## Tests

```bash
AI_PROVIDER=mock pytest
```

Expect ~96 tests to pass. Tests always force `AI_PROVIDER=mock` so no model download or GPU is required.

## Environment variables


| Variable                | Default                      | Description                                                            |
| ----------------------- | ---------------------------- | ---------------------------------------------------------------------- |
| `AI_QUOTA_DATABASE_URL` | `sqlite:///./ai_quota.db`    | SQLAlchemy database URL                                                |
| `AI_QUOTA_API_PREFIX`   | `/api/v1`                    | API route prefix                                                       |
| `AI_PROVIDER`           | `local`                      | AI backend: `local` (HuggingFace) or `mock` (deterministic, for tests) |
| `AI_MODEL_NAME`         | `Qwen/Qwen2.5-0.5B-Instruct` | HuggingFace model id when `AI_PROVIDER=local`                          |


## Database notes

On startup the app runs `create_all()` and a lightweight SQLite schema sync that adds missing columns (for example `users.name` and `users.email`) to older local database files.

If you still see schema errors after restarting, delete the local SQLite file (default: `ai_quota.db` in the project root) and start the server again. Tests use an in-memory database and are unaffected.

## Troubleshooting


| Symptom                                       | Fix                                                                       |
| --------------------------------------------- | ------------------------------------------------------------------------- |
| Schema or migration errors on startup         | Delete `ai_quota.db` in the project root and restart the server           |
| `409` duplicate email when creating a user    | Use a different email address                                             |
| `404` user not found on config/generate/usage | Create a user first; copy `user_id` from the response into `X-User-Id`    |
| Port 8000 already in use                      | Stop the other process or run `uvicorn app.main:app --reload --port 8001` |




