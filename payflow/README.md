# PayFlow

Internal payment and wallet API (Phase 1: wallets, transfers, transaction history).

## Layout (where to add code)

| Path | Purpose |
|------|---------|
| `src/payflow/routers/` | HTTP routes only — validate input, call services, return responses |
| `src/payflow/services/` | Business logic and raw SQL |
| `src/payflow/schemas/` | Pydantic request/response models |
| `src/payflow/middleware/` | Cross-cutting HTTP (errors, future idempotency, rate limits) |
| `src/payflow/utils/` | Pure helpers (money, pagination, HMAC) |
| `alembic/versions/` | Schema changes (Alembic revisions) |
| `tests/` | `pytest` + `httpx` async client |

## Setup

```bash
cd payflow
python -m venv .venv
.venv\Scripts\activate
pip install -e ".[dev]"
copy .env.example .env
```

## Run API

```bash
python -m payflow.main
```

Uses **hot reload** by default (`RELOAD=true` in `.env`). Disable with `RELOAD=false`.

Or run uvicorn directly:

```bash
uvicorn payflow.main:app --host 127.0.0.1 --port 3000 --reload
```

(`--port` should match `PORT` in `.env` if you use the same DB and URLs.)

## Tests

```bash
pytest tests -v
```

## Seed (dev users + 10_000.00 SIM per user)

```bash
python -m payflow.seed
```

Prints generated `api_key` lines for each new user (skipped if username already exists).

## Migrations (Alembic)

Migrations run automatically on app startup. Manual:

```bash
alembic upgrade head
```
