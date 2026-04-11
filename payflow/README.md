# PayFlow

Internal payment and wallet API: wallets, transfers, transaction history, scheduled/recurring payments, webhooks, expense reports (Phase 3), vendors/invoices/batches/settlements (Phase 4), and fraud rules / audit log / rate limits (Phase 5).

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

**Phase 2 worker:** when `ENABLE_WORKER=true` (default), the app runs a background job on `WORKER_INTERVAL_SECONDS` (default `60`) that executes due scheduled and recurring payments and delivers webhook notifications. Set `ENABLE_WORKER=false` if you only want HTTP-triggered behavior.

### Phase 2 HTTP (summary)

- Scheduled: `POST/GET/PATCH /api/v1/scheduled-payments` — one-shot future-dated transfers.
- Recurring: `POST/GET /api/v1/recurring-payments` — daily / weekly / monthly schedules.
- Webhooks: `POST /api/v1/webhooks` — subscribe URLs for payment events (HMAC-signed payloads).

### Phase 3 (expense reports)

- Categories: `GET /api/v1/expense-categories` — policy limits for line items (seeded with `python -m payflow.seed`).
- Reports: `POST /api/v1/expense-reports`, `POST .../{id}/submit`, `POST .../{id}/approve`, `POST .../{id}/reject`, `POST /api/v1/expense-reports/bulk-action`, `GET /api/v1/expense-reports`, `GET .../{id}`.
- Reimbursements debit **`REIMBURSEMENT_WALLET_ID`** (default matches the seeded company float wallet) and credit the submitter’s SIM wallet when a report is fully approved.

**Intentional spec-matching behaviors (QA):** PF-009 self-approval allowed for managers; PF-010 bulk action always HTTP 200 with per-id results; PF-011 multi-level threshold uses strict `>` (not `>=`); PF-012 `receipt_url` is not validated as a URL.

**Smoke (all Phase 3 routes, prints JSON to the console):** after seed, run `python scripts/smoke_phase3.py` from the `payflow` directory (requires `pip install -e ".[dev]"`). Optional env: `SMOKE_CHARLIE_KEY`, `SMOKE_BOB_KEY` to override DB lookups.

### Phase 4 (vendors & invoices)

- **Vendors:** `POST /api/v1/vendors` (admin), `DELETE /api/v1/vendors/{id}` (soft-delete), `GET /api/v1/vendors` — creates a vendor user + SIM wallet per vendor.
- **Invoices:** `POST /api/v1/invoices`, `POST /api/v1/invoices/{id}/approve`, `GET /api/v1/invoices` — approve before batch pay.
- **Batch:** `POST /api/v1/payment-batches/execute` — pays approved invoices whose `due_date` is on or before today.
- **Settlements:** `GET /api/v1/settlements` — query `date_from`, `date_to`, `vendor_id`, `format=json|csv`.
- **Workers:** `ENABLE_BATCH_WORKER` / `BATCH_WORKER_INTERVAL_SECONDS` run the invoice batch executor (in addition to `ENABLE_WORKER` for scheduled/recurring payments).

**Intentional spec-matching behaviors (QA):** PF-013 settlement aggregate uses current exchange rate vs per-invoice creation metadata; PF-014 due date from datetime + `timedelta` without date-only normalization; PF-015 soft-deleted vendor + due invoice can crash batch execution (`TypeError`); PF-016 CSV rows are unquoted (commas in vendor names break columns).

### Phase 5 (fraud & audit)

- **Rules (admin):** `POST /api/v1/fraud/rules` — velocity, amount threshold, geo/pattern (stubs), actions `flag` / `block` / `alert`.
- **Transfers:** evaluated against active rules after validation; `block` → HTTP 403 `FRAUD_BLOCKED`; `flag` → ledger move + transaction `held` + `flagged_transactions` row + optional `meta.warning`; completed transfers fire `payment.executed` webhooks (held does not).
- **Review (admin):** `GET /api/v1/fraud/flagged`, `POST /api/v1/fraud/flagged/{id}/release` — completes held transaction; **does not** send webhook on release (PF-019).
- **Audit (admin):** `GET /api/v1/audit-log` — append-only table with SQLite triggers preventing UPDATE/DELETE.
- **Rate limits (in-process):** per sender wallet for transfers; separate per-user cap on `POST /wallets` (see `.env.example`).

**Intentional spec-matching behaviors (QA):** PF-017 velocity counts `sender_wallet_id` only (multi-wallet bypass); PF-018 transfer audit row committed before the transfer transaction so failures still show `error_message: null`; PF-019 release does not call `notify_user_event`; PF-020 wallet creation uses its own hourly limit (not the per-wallet transfer window).

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

Prints generated `api_key` lines for each new user (skipped if username already exists). Also ensures a **company float** wallet and **expense categories** when missing.

## Migrations (Alembic)

Migrations run automatically on app startup. Manual:

```bash
alembic upgrade head
```
