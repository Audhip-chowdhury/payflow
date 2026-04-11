# PayFlow — Implementation Specification

> **Purpose**: This document is a complete, phase-wise implementation spec for PayFlow, an internal payment and wallet system. Feed each phase to Claude Code sequentially. Each phase is self-contained with schemas, endpoints, business rules, test expectations, and known bugs to inject.

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Runtime | Node.js 20+ with TypeScript |
| Framework | Express.js with `express-async-errors` |
| Database | PostgreSQL 16 with `pg` driver (raw SQL, no ORM) |
| Migrations | `node-pg-migrate` |
| Auth | API key-based (header: `X-API-Key`) |
| Validation | `zod` |
| Logging | `pino` |
| Testing | `vitest` + `supertest` |
| Containerization | Docker + docker-compose |

---

## Project Structure

```
payflow/
├── docker-compose.yml
├── Dockerfile
├── package.json
├── tsconfig.json
├── .env.example
├── migrations/
│   ├── 001_initial_schema.sql
│   ├── 002_scheduled_payments.sql
│   ├── 003_expense_reports.sql
│   ├── 004_vendors_invoices.sql
│   ├── 005_fraud_audit.sql
│   └── 006_analytics.sql
├── src/
│   ├── index.ts                    # App entry, middleware setup
│   ├── config.ts                   # Env loading
│   ├── db.ts                       # PG pool + query helper
│   ├── middleware/
│   │   ├── auth.ts                 # API key validation
│   │   ├── idempotency.ts          # Idempotency key middleware
│   │   ├── rate-limiter.ts         # Per-wallet rate limiting
│   │   ├── error-handler.ts        # Global error handler
│   │   └── request-logger.ts       # Pino request logging
│   ├── routes/
│   │   ├── wallets.ts
│   │   ├── transfers.ts
│   │   ├── transactions.ts
│   │   ├── scheduled-payments.ts
│   │   ├── recurring-payments.ts
│   │   ├── webhooks.ts
│   │   ├── expense-reports.ts
│   │   ├── vendors.ts
│   │   ├── invoices.ts
│   │   ├── payment-batches.ts
│   │   ├── settlements.ts
│   │   ├── fraud.ts
│   │   ├── audit-log.ts
│   │   ├── reports.ts
│   │   └── oauth.ts
│   ├── services/
│   │   ├── wallet.service.ts
│   │   ├── transfer.service.ts
│   │   ├── scheduler.service.ts
│   │   ├── webhook.service.ts
│   │   ├── expense.service.ts
│   │   ├── vendor.service.ts
│   │   ├── batch.service.ts
│   │   ├── fraud.service.ts
│   │   ├── audit.service.ts
│   │   └── report.service.ts
│   ├── workers/
│   │   ├── payment-executor.ts     # Processes scheduled/recurring
│   │   └── batch-executor.ts       # Processes vendor payment batches
│   ├── types/
│   │   └── index.ts                # All shared TypeScript types
│   └── utils/
│       ├── currency.ts             # Decimal math helpers
│       ├── pagination.ts           # Cursor/offset pagination
│       └── hmac.ts                 # Webhook signature generation
├── tests/
│   ├── setup.ts                    # Test DB setup/teardown
│   ├── wallets.test.ts
│   ├── transfers.test.ts
│   ├── scheduled-payments.test.ts
│   ├── expense-reports.test.ts
│   ├── vendors.test.ts
│   ├── fraud.test.ts
│   └── reports.test.ts
└── seed/
    └── seed.ts                     # Dev seed data
```

---

## Global Conventions

### API Response Format

All responses follow this envelope:

```json
// Success
{
  "success": true,
  "data": { ... },
  "meta": { "page": 1, "limit": 10, "total": 42 }  // only on list endpoints
}

// Error
{
  "success": false,
  "error": {
    "code": "INSUFFICIENT_BALANCE",
    "message": "Wallet has insufficient funds for this transfer",
    "details": {}  // optional
  }
}
```

### Error Codes

Use these consistently across all phases:

| Code | HTTP Status | Meaning |
|------|-------------|---------|
| `VALIDATION_ERROR` | 400 | Request body/params failed zod validation |
| `UNAUTHORIZED` | 401 | Missing or invalid API key |
| `FORBIDDEN` | 403 | Valid key but insufficient permissions |
| `NOT_FOUND` | 404 | Resource doesn't exist |
| `CONFLICT` | 409 | Duplicate idempotency key with different payload |
| `INSUFFICIENT_BALANCE` | 422 | Wallet balance too low |
| `INVALID_STATE` | 422 | Action not valid for current resource state |
| `RATE_LIMITED` | 429 | Too many requests |
| `INTERNAL_ERROR` | 500 | Unexpected server error |

### Idempotency

All `POST` and `PATCH` endpoints accept an `Idempotency-Key` header. Implementation:

1. On request, hash `(idempotency_key, endpoint, api_key)` and check the `idempotency_store` table.
2. If found and payload matches → return the cached response.
3. If found and payload differs → return 409 CONFLICT.
4. If not found → process the request, store the response, return it.
5. Keys expire after 24 hours.

### Decimal Handling

All monetary values are stored as `BIGINT` in the smallest unit (paise: 1 SimCash = 100 paise). API accepts/returns `string` representations with 2 decimal places (e.g., `"150.00"`). Never use floating point for money.

Internal storage: `15000` (paise) ↔ API representation: `"150.00"` (SimCash)

### Timestamps

All timestamps are stored as `TIMESTAMPTZ` in Postgres and returned as ISO 8601 strings in UTC.

---

## Phase 1: Core Wallet & Transfers

> **Goal**: Users can create wallets, transfer SimCash between wallets, and view transaction history.

### Migration 001

```sql
-- 001_initial_schema.sql

CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- Users table (simplified — external auth provides users, we just store wallet-relevant data)
CREATE TABLE users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    username VARCHAR(50) UNIQUE NOT NULL,
    email VARCHAR(255) UNIQUE NOT NULL,
    api_key VARCHAR(64) UNIQUE NOT NULL,
    role VARCHAR(20) NOT NULL DEFAULT 'employee' CHECK (role IN ('employee', 'manager', 'admin', 'vendor')),
    is_active BOOLEAN NOT NULL DEFAULT true,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Wallets
CREATE TABLE wallets (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id),
    currency VARCHAR(10) NOT NULL DEFAULT 'SIM',
    balance BIGINT NOT NULL DEFAULT 0 CHECK (balance >= 0),
    status VARCHAR(20) NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'frozen', 'closed')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_wallets_user_id ON wallets(user_id);

-- Transactions (immutable ledger)
CREATE TABLE transactions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    type VARCHAR(20) NOT NULL CHECK (type IN ('transfer', 'credit', 'debit', 'refund', 'settlement')),
    status VARCHAR(20) NOT NULL DEFAULT 'completed' CHECK (status IN ('pending', 'completed', 'failed', 'held')),
    sender_wallet_id UUID REFERENCES wallets(id),
    receiver_wallet_id UUID REFERENCES wallets(id),
    amount BIGINT NOT NULL CHECK (amount > 0),
    currency VARCHAR(10) NOT NULL DEFAULT 'SIM',
    reference_id UUID,         -- links to source (expense_report, invoice, etc.)
    reference_type VARCHAR(30), -- 'expense_report', 'invoice', 'transfer', etc.
    description TEXT,
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_transactions_sender ON transactions(sender_wallet_id, created_at DESC);
CREATE INDEX idx_transactions_receiver ON transactions(receiver_wallet_id, created_at DESC);

-- Idempotency store
CREATE TABLE idempotency_store (
    key_hash VARCHAR(128) PRIMARY KEY,
    endpoint VARCHAR(100) NOT NULL,
    api_key_id UUID NOT NULL,
    request_payload_hash VARCHAR(128) NOT NULL,
    response_status INT NOT NULL,
    response_body JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at TIMESTAMPTZ NOT NULL DEFAULT now() + INTERVAL '24 hours'
);

CREATE INDEX idx_idempotency_expires ON idempotency_store(expires_at);
```

### Endpoints

#### POST /api/v1/wallets

Create a wallet for the authenticated user.

**Request:**
```json
{
  "currency": "SIM"  // optional, defaults to "SIM"
}
```

**Response (201):**
```json
{
  "success": true,
  "data": {
    "id": "uuid",
    "user_id": "uuid",
    "currency": "SIM",
    "balance": "0.00",
    "status": "active",
    "created_at": "2025-01-01T00:00:00.000Z"
  }
}
```

**Business Rules:**
- A user can have multiple wallets (one per currency).
- A user cannot have two wallets with the same currency → return 409.
- Only active users can create wallets.

---

#### GET /api/v1/wallets/:id

Get wallet details including balance.

**Response (200):**
```json
{
  "success": true,
  "data": {
    "id": "uuid",
    "user_id": "uuid",
    "currency": "SIM",
    "balance": "150.00",
    "status": "active",
    "created_at": "...",
    "updated_at": "..."
  }
}
```

**Business Rules:**
- Users can only view their own wallets unless they have `admin` role.

**🐛 BUG PF-003 — INJECT THIS:**
In `wallet.service.ts`, when serializing the balance from BIGINT to the API response, return the balance as a **string** (`"150.00"`) — this is correct. BUT also add a secondary field `balance_numeric` that returns it as a JavaScript `number` (`150.00`). The primary `balance` field should be correct, but in the list wallets endpoint (`GET /api/v1/wallets`), accidentally use the numeric version for the `balance` field. This means:
- `GET /wallets/:id` returns `"balance": "150.00"` (string — correct)
- `GET /wallets` returns `"balance": 150` (number — bug, also loses precision for large amounts)

---

#### POST /api/v1/transfers

Transfer SimCash between two wallets.

**Request:**
```json
{
  "sender_wallet_id": "uuid",
  "receiver_wallet_id": "uuid",
  "amount": "250.00",
  "description": "Lunch reimbursement"
}
```

**Headers:**
```
Idempotency-Key: unique-client-generated-key
```

**Response (201):**
```json
{
  "success": true,
  "data": {
    "transaction_id": "uuid",
    "sender_wallet_id": "uuid",
    "receiver_wallet_id": "uuid",
    "amount": "250.00",
    "status": "completed",
    "created_at": "..."
  }
}
```

**Business Rules:**
- Sender must own the wallet and it must be `active`.
- Receiver wallet must exist and be `active`.
- Sender must have sufficient balance.
- Cannot transfer to self (same wallet_id).
- Amount must be > 0.
- Transfer must be atomic: debit sender and credit receiver in a single DB transaction.

**Implementation:**
```sql
-- Inside a single transaction:
BEGIN;
  -- Lock sender wallet row
  SELECT balance FROM wallets WHERE id = $sender_id FOR UPDATE;
  -- Check balance >= amount
  UPDATE wallets SET balance = balance - $amount, updated_at = now() WHERE id = $sender_id;
  UPDATE wallets SET balance = balance + $amount, updated_at = now() WHERE id = $receiver_id;
  INSERT INTO transactions (...) VALUES (...);
COMMIT;
```

**🐛 BUG PF-001 — INJECT THIS (Critical):**
In the idempotency middleware (`middleware/idempotency.ts`), implement the check **outside** the database transaction. Specifically:
1. Check idempotency key exists → not found → proceed.
2. Begin the DB transaction for the transfer.
3. Inside the transaction, insert the idempotency record.

The bug: between step 1 and step 3, a concurrent retry with the same idempotency key also passes step 1 (the record hasn't been inserted yet). Both proceed to execute the transfer. The result: the sender is debited twice, but due to a `ON CONFLICT DO NOTHING` on the idempotency insert, the second transaction's idempotency record is silently dropped — and the cached response from the first is never returned.

**How it should work (correct, but don't implement this):** The idempotency check and the transfer should be in the same serializable transaction, or use `SELECT ... FOR UPDATE` on the idempotency key.

**🐛 BUG PF-004 — INJECT THIS:**
In the zod validation schema for the transfer request, validate amount as:
```typescript
amount: z.string().regex(/^\d+\.\d{2}$/)  // validates format but not value
```
This accepts `"0.00"` as a valid amount. The correct validation should also check that the parsed value is > 0. The result: transferring `"0.00"` succeeds, creates a transaction record, but doesn't change any balances.

---

#### GET /api/v1/transactions

List transactions for a wallet with pagination.

**Query params:**
| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `wallet_id` | UUID | required | Filter by wallet |
| `type` | string | all | Filter: transfer, credit, debit, refund |
| `page` | int | 1 | Page number |
| `limit` | int | 10 | Items per page (max 100) |
| `sort` | string | `created_at:desc` | Sort field and direction |

**Response (200):**
```json
{
  "success": true,
  "data": [
    {
      "id": "uuid",
      "type": "transfer",
      "status": "completed",
      "sender_wallet_id": "uuid",
      "receiver_wallet_id": "uuid",
      "amount": "250.00",
      "description": "Lunch reimbursement",
      "created_at": "..."
    }
  ],
  "meta": {
    "page": 1,
    "limit": 10,
    "total": 42,
    "total_pages": 5
  }
}
```

**🐛 BUG PF-002 — INJECT THIS:**
In `utils/pagination.ts`, implement the offset calculation as:
```typescript
const offset = (page - 1) * limit;
// SQL: SELECT ... LIMIT $limit + 1 OFFSET $offset
```
The bug: the query fetches `limit + 1` rows (a common pattern to detect "has next page"), but the response returns ALL fetched rows instead of slicing to `limit`. So when there are more results, the response contains `limit + 1` items (e.g., 11 when limit=10). On the last page (fewer results than limit+1), it returns correctly.

---

### Phase 1 Seed Data

```typescript
// seed/seed.ts — create these for development
const users = [
  { username: "alice", email: "alice@simcorp.io", role: "admin" },
  { username: "bob", email: "bob@simcorp.io", role: "manager" },
  { username: "charlie", email: "charlie@simcorp.io", role: "employee" },
  { username: "diana", email: "diana@simcorp.io", role: "employee" },
  { username: "eve", email: "eve@simcorp.io", role: "employee" },
];
// Each user gets a SIM wallet with 10000.00 starting balance.
// Generate API keys as: `pfk_${crypto.randomBytes(24).toString('hex')}`
```

### Phase 1 Tests to Write

1. **Wallet creation**: success, duplicate currency rejection, inactive user rejection.
2. **Transfer**: success, insufficient balance, self-transfer, frozen wallet, zero amount (should fail but BUG PF-004 makes it pass — write the test expecting success, and add a `// TODO: should this be allowed?` comment).
3. **Pagination**: verify correct page sizes, verify last page size (BUG PF-002 will cause 11-item pages — write tests that pass with the bug).
4. **Idempotency**: same key + same payload = same response, same key + different payload = 409.

---

## Phase 2: Scheduled & Recurring Payments

> **Goal**: Users can schedule one-time future payments and set up recurring payment schedules. A background worker executes due payments.

### Migration 002

```sql
-- 002_scheduled_payments.sql

CREATE TABLE scheduled_payments (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    sender_wallet_id UUID NOT NULL REFERENCES wallets(id),
    receiver_wallet_id UUID NOT NULL REFERENCES wallets(id),
    amount BIGINT NOT NULL CHECK (amount > 0),
    currency VARCHAR(10) NOT NULL DEFAULT 'SIM',
    description TEXT,
    scheduled_date DATE NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'executed', 'failed', 'cancelled')),
    executed_at TIMESTAMPTZ,
    error_message TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_scheduled_pending ON scheduled_payments(scheduled_date, status) WHERE status = 'pending';

CREATE TABLE recurring_payments (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    sender_wallet_id UUID NOT NULL REFERENCES wallets(id),
    receiver_wallet_id UUID NOT NULL REFERENCES wallets(id),
    amount BIGINT NOT NULL CHECK (amount > 0),
    currency VARCHAR(10) NOT NULL DEFAULT 'SIM',
    description TEXT,
    frequency VARCHAR(20) NOT NULL CHECK (frequency IN ('daily', 'weekly', 'monthly')),
    day_of_month INT CHECK (day_of_month BETWEEN 1 AND 31), -- for monthly
    day_of_week INT CHECK (day_of_week BETWEEN 0 AND 6),    -- for weekly (0=Sunday)
    next_execution_date DATE NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'paused', 'cancelled')),
    start_date DATE NOT NULL,
    end_date DATE,           -- null = indefinite
    total_executions INT NOT NULL DEFAULT 0,
    last_executed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_recurring_active ON recurring_payments(next_execution_date, status) WHERE status = 'active';

CREATE TABLE webhook_subscriptions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id),
    url TEXT NOT NULL,
    events TEXT[] NOT NULL,    -- e.g., {'payment.executed', 'payment.failed'}
    secret VARCHAR(64) NOT NULL,  -- for HMAC signing
    is_active BOOLEAN NOT NULL DEFAULT true,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE webhook_deliveries (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    subscription_id UUID NOT NULL REFERENCES webhook_subscriptions(id),
    event_type VARCHAR(50) NOT NULL,
    payload JSONB NOT NULL,
    response_status INT,
    response_body TEXT,
    attempt INT NOT NULL DEFAULT 1,
    delivered_at TIMESTAMPTZ,
    next_retry_at TIMESTAMPTZ,
    status VARCHAR(20) NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'delivered', 'failed', 'retrying')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

### Endpoints

#### POST /api/v1/scheduled-payments

**Request:**
```json
{
  "sender_wallet_id": "uuid",
  "receiver_wallet_id": "uuid",
  "amount": "500.00",
  "scheduled_date": "2025-03-15",
  "description": "Quarterly bonus"
}
```

**Business Rules:**
- `scheduled_date` must be in the future (today or later).
- Sender must own the wallet.
- No balance check at scheduling time (checked at execution).

---

#### GET /api/v1/scheduled-payments

**Query params:** `status`, `wallet_id`, `page`, `limit`

**🐛 BUG PF-008 — INJECT THIS:**
The default query does NOT filter by status. This means executed and cancelled payments appear alongside pending ones. The endpoint should default to `status=pending` when no status filter is provided, but it returns ALL.

---

#### PATCH /api/v1/scheduled-payments/:id

**Request:**
```json
{
  "status": "cancelled"  // only allowed transition: pending → cancelled
}
```

**Business Rules:**
- Only `pending` payments can be cancelled.
- Only wallet owner or admin can cancel.

---

#### POST /api/v1/recurring-payments

**Request:**
```json
{
  "sender_wallet_id": "uuid",
  "receiver_wallet_id": "uuid",
  "amount": "1000.00",
  "frequency": "monthly",
  "day_of_month": 15,
  "start_date": "2025-02-01",
  "end_date": "2025-12-31",
  "description": "Monthly rent"
}
```

**Business Rules:**
- `start_date` must be today or future.
- `end_date` must be after `start_date` (or null for indefinite).
- For `monthly`: `day_of_month` required.
- For `weekly`: `day_of_week` required.
- `next_execution_date` is computed from start_date and frequency.

**🐛 BUG PF-005 — INJECT THIS (Critical):**
In `scheduler.service.ts`, when computing `next_execution_date` for monthly payments, use this naive logic:
```typescript
function getNextMonthlyDate(current: Date, dayOfMonth: number): Date {
  const next = new Date(current);
  next.setMonth(next.getMonth() + 1);
  next.setDate(dayOfMonth);
  return next;
}
```
The bug: when `dayOfMonth` is 31 and the next month has only 30 days (e.g., April), `setDate(31)` rolls over to May 1st. The scheduler then executes on May 1st. When it next computes the following execution, it calculates from May 1st + 1 month = June 1st. But the REAL next execution from the June schedule also fires June 1st (since June has 30 days, day 31 → July 1st... but wait, the next_execution_date was already set to June 1st from the May rollover). Net effect: payments pile up or skip depending on the month. This is a real-world date handling bug.

---

#### POST /api/v1/webhooks

**Request:**
```json
{
  "url": "https://example.com/webhook",
  "events": ["payment.executed", "payment.failed"],
  "secret": "whsec_abcdef123456"
}
```

**Webhook Payload Format:**
```json
{
  "event": "payment.executed",
  "timestamp": "2025-01-15T10:00:00Z",
  "data": {
    "transaction_id": "uuid",
    "amount": "1000.00",
    "sender_wallet_id": "uuid",
    "receiver_wallet_id": "uuid"
  }
}
```

**Signature:** HMAC-SHA256 of the JSON body using the subscription secret, sent in `X-PayFlow-Signature` header.

**🐛 BUG PF-007 — INJECT THIS:**
In `webhook.service.ts`, when retrying a failed delivery:
```typescript
async function deliverWebhook(subscription, event, payload) {
  const body = JSON.stringify(payload);
  const timestamp = new Date().toISOString();  // ← regenerated on each attempt
  const signature = hmac(subscription.secret, body);
  
  // Send with headers:
  // X-PayFlow-Signature: <signature computed from body>
  // X-Delivery-Timestamp: <timestamp>  ← this changes per retry
}
```
The bug: the `body` contains the original `payload.timestamp` from the first attempt, but the header `X-Delivery-Timestamp` is regenerated each retry. If a consumer uses the header timestamp to verify the signature (a common pattern to prevent replay attacks), the signature won't match because the signature was computed against the body (which has the old timestamp), not the header. The fix would be to either: (a) include the header timestamp in the signature input, or (b) not regenerate it on retries.

---

### Payment Executor Worker

**File:** `src/workers/payment-executor.ts`

This worker runs on a configurable interval (default: every 60 seconds) via `setInterval` or a cron-like scheduler.

**Logic:**
1. Query all `scheduled_payments` where `scheduled_date <= today AND status = 'pending'`.
2. Query all `recurring_payments` where `next_execution_date <= today AND status = 'active'`.
3. For each, attempt the transfer (same logic as `POST /transfers`).
4. On success: update status to `executed`, create transaction record, fire webhook.
5. On failure (insufficient balance etc.): update status to `failed`, store error, fire webhook.
6. For recurring: compute and set `next_execution_date`, increment `total_executions`.

**🐛 BUG PF-006 — INJECT THIS:**
The worker fetches the batch of due payments at the START of the cycle:
```typescript
async function executeDuePayments() {
  // Fetch all due payments in one query
  const duePayments = await db.query(`
    SELECT * FROM recurring_payments 
    WHERE next_execution_date <= CURRENT_DATE AND status = 'active'
  `);
  
  // Process each one (this takes time)
  for (const payment of duePayments) {
    await executePayment(payment);  // ~200ms per payment
  }
}
```
The bug: if a user cancels a recurring payment (sets status to `cancelled`) WHILE the worker is processing the batch, their payment still executes because the worker already fetched it. There is no re-check of `status` at execution time. The fix would be to `SELECT ... FOR UPDATE SKIP LOCKED` and re-verify status within the execution transaction.

---

### Phase 2 Tests

1. **Scheduled payment**: creation, future date validation, cancellation, execution by worker.
2. **Recurring payment**: monthly/weekly/daily creation, next_execution_date computation.
3. **Worker**: processes due payments, skips already-executed, handles insufficient balance.
4. **Webhooks**: delivery, signature verification, retry behavior.

---

## Phase 3: Expense Reports & Approvals

> **Goal**: Employees submit expense reports, managers approve/reject, approved reports trigger reimbursement to the submitter's wallet.

### Migration 003

```sql
-- 003_expense_reports.sql

CREATE TABLE expense_categories (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(100) NOT NULL UNIQUE,
    policy_limit BIGINT,  -- max amount per line item in paise (null = no limit)
    is_active BOOLEAN NOT NULL DEFAULT true
);

CREATE TABLE expense_reports (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    submitter_id UUID NOT NULL REFERENCES users(id),
    title VARCHAR(200) NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'submitted', 'under_review', 'approved', 'rejected', 'reimbursed', 'cancelled')),
    total_amount BIGINT NOT NULL DEFAULT 0,
    currency VARCHAR(10) NOT NULL DEFAULT 'SIM',
    submitted_at TIMESTAMPTZ,
    reviewed_by UUID REFERENCES users(id),
    reviewed_at TIMESTAMPTZ,
    rejection_reason TEXT,
    requires_multi_level BOOLEAN NOT NULL DEFAULT false,
    multi_level_threshold BIGINT NOT NULL DEFAULT 5000000,  -- 50000.00 SIM
    second_reviewer_id UUID REFERENCES users(id),
    second_reviewed_at TIMESTAMPTZ,
    reimbursement_transaction_id UUID REFERENCES transactions(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_expense_submitter ON expense_reports(submitter_id, status);

CREATE TABLE expense_line_items (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    expense_report_id UUID NOT NULL REFERENCES expense_reports(id) ON DELETE CASCADE,
    category_id UUID NOT NULL REFERENCES expense_categories(id),
    description TEXT NOT NULL,
    amount BIGINT NOT NULL CHECK (amount > 0),
    receipt_url TEXT,
    date DATE NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

### Endpoints

#### POST /api/v1/expense-reports

**Request:**
```json
{
  "title": "Q1 Client Entertainment",
  "line_items": [
    {
      "category_id": "uuid",
      "description": "Client dinner at Taj",
      "amount": "4500.00",
      "receipt_url": "https://storage.example.com/receipt-001.pdf",
      "date": "2025-01-10"
    },
    {
      "category_id": "uuid",
      "description": "Cab to airport",
      "amount": "1200.00",
      "receipt_url": "https://storage.example.com/receipt-002.pdf",
      "date": "2025-01-11"
    }
  ]
}
```

**Business Rules:**
- Total amount is auto-computed from line items.
- Each line item's amount is validated against its category's `policy_limit`.
- Report starts in `draft` status.
- `receipt_url` is required for amounts > 500.00 SIM.

**🐛 BUG PF-012 — INJECT THIS:**
The `receipt_url` field uses this zod validation:
```typescript
receipt_url: z.string().optional()
```
There is NO URL format validation. Accepts any string including `javascript:alert(1)`, `file:///etc/passwd`, or empty string. Should use `z.string().url()` or a regex that validates http/https URLs.

---

#### POST /api/v1/expense-reports/:id/submit

Transitions from `draft` → `submitted`.

**Business Rules:**
- Must have at least one line item.
- Sets `submitted_at` timestamp.
- If `total_amount >= multi_level_threshold`, sets `requires_multi_level = true`.

**🐛 BUG PF-011 — INJECT THIS:**
The multi-level check uses strict greater-than:
```typescript
if (report.total_amount > report.multi_level_threshold) {
  report.requires_multi_level = true;
}
```
An expense totaling exactly 50000.00 SIM (the threshold) does NOT trigger multi-level approval. It should use `>=`.

---

#### POST /api/v1/expense-reports/:id/approve

**Request:**
```json
{
  "notes": "Approved, looks good"
}
```

**Business Rules:**
- Only users with role `manager` or `admin` can approve.
- Status must be `submitted` or `under_review`.
- On approval: if `requires_multi_level` and this is the first approval, move to `under_review` and set `reviewed_by`. A second manager/admin must also approve (sets `second_reviewer_id`).
- On final approval: status → `approved`, trigger reimbursement to submitter's primary wallet.
- **The approver cannot be the submitter.**

**🐛 BUG PF-009 — INJECT THIS (Critical):**
The authorization check in `expense.service.ts`:
```typescript
async function approveExpenseReport(reportId: string, approverId: string) {
  const approver = await getUser(approverId);
  
  // BUG: Only checks role, doesn't check if approver === submitter
  if (approver.role !== 'manager' && approver.role !== 'admin') {
    throw new ForbiddenError('Only managers can approve expense reports');
  }
  
  // Missing: if (report.submitter_id === approverId) throw new ForbiddenError(...)
  
  // ... proceed with approval
}
```
A user who is both an employee AND has manager role (e.g., a team lead) can submit an expense report and then approve it themselves.

---

#### POST /api/v1/expense-reports/:id/reject

**Request:**
```json
{
  "reason": "Missing receipt for cab expense"
}
```

**Business Rules:**
- Same role requirements as approve.
- `reason` is required.
- Status → `rejected`.

---

#### POST /api/v1/expense-reports/bulk-action

**Request:**
```json
{
  "action": "approve",
  "report_ids": ["uuid1", "uuid2", "uuid3"],
  "notes": "Batch approved for Q1"
}
```

**🐛 BUG PF-010 — INJECT THIS:**
The bulk endpoint processes each report in a loop and collects results, but always returns 200 OK with the full list:
```typescript
async function bulkAction(reportIds: string[], action: string, actorId: string) {
  const results = [];
  for (const id of reportIds) {
    try {
      const result = await processAction(id, action, actorId);
      results.push({ id, status: 'success', data: result });
    } catch (err) {
      results.push({ id, status: 'failed', error: err.message });
    }
  }
  // BUG: Always returns 200, even if some/all failed
  return { success: true, data: results };
}
```
The correct behavior: return 207 Multi-Status when there are mixed results, or 200 only when all succeed.

---

### Seed Data for Phase 3

```typescript
const categories = [
  { name: "Travel", policy_limit: 1000000 },         // 10000.00 SIM
  { name: "Meals & Entertainment", policy_limit: 500000 }, // 5000.00 SIM
  { name: "Office Supplies", policy_limit: 200000 },  // 2000.00 SIM
  { name: "Software & Tools", policy_limit: null },    // No limit
  { name: "Training", policy_limit: 2500000 },        // 25000.00 SIM
];
```

---

## Phase 4: Merchant & Vendor Payments

> **Goal**: Onboard vendors, create invoices, process payments in batches, support multi-currency, and generate settlement reports.

### Migration 004

```sql
-- 004_vendors_invoices.sql

CREATE TABLE vendors (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(200) NOT NULL,
    email VARCHAR(255) NOT NULL,
    tax_id VARCHAR(50),
    payment_terms VARCHAR(20) NOT NULL DEFAULT 'net_30' CHECK (payment_terms IN ('immediate', 'net_15', 'net_30', 'net_60')),
    wallet_id UUID REFERENCES wallets(id),
    bank_details JSONB,          -- { bank_name, account_number, ifsc_code }
    status VARCHAR(20) NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'inactive', 'deleted')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE invoices (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    vendor_id UUID NOT NULL REFERENCES vendors(id),
    invoice_number VARCHAR(50) UNIQUE NOT NULL,
    amount BIGINT NOT NULL CHECK (amount > 0),
    currency VARCHAR(10) NOT NULL DEFAULT 'SIM',
    description TEXT,
    due_date DATE NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'approved', 'scheduled', 'paid', 'cancelled', 'overdue')),
    payer_wallet_id UUID NOT NULL REFERENCES wallets(id),
    transaction_id UUID REFERENCES transactions(id),
    batch_id UUID,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_invoices_vendor ON invoices(vendor_id, status);
CREATE INDEX idx_invoices_due ON invoices(due_date, status) WHERE status IN ('pending', 'approved');

CREATE TABLE payment_batches (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    status VARCHAR(20) NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'processing', 'completed', 'failed')),
    total_amount BIGINT NOT NULL DEFAULT 0,
    total_invoices INT NOT NULL DEFAULT 0,
    processed_count INT NOT NULL DEFAULT 0,
    failed_count INT NOT NULL DEFAULT 0,
    executed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE exchange_rates (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    from_currency VARCHAR(10) NOT NULL,
    to_currency VARCHAR(10) NOT NULL,
    rate NUMERIC(18, 8) NOT NULL,   -- using NUMERIC here for rates (not money)
    effective_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(from_currency, to_currency, effective_at)
);

CREATE INDEX idx_exchange_rates_lookup ON exchange_rates(from_currency, to_currency, effective_at DESC);

CREATE TABLE settlements (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    batch_id UUID REFERENCES payment_batches(id),
    vendor_id UUID NOT NULL REFERENCES vendors(id),
    total_amount BIGINT NOT NULL,
    currency VARCHAR(10) NOT NULL,
    exchange_rate_used NUMERIC(18, 8),
    settled_amount BIGINT NOT NULL,  -- in target currency
    settled_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

### Endpoints

#### POST /api/v1/vendors

**Request:**
```json
{
  "name": "Acme Cloud Services",
  "email": "billing@acme.io",
  "tax_id": "GSTIN1234567890",
  "payment_terms": "net_30",
  "bank_details": {
    "bank_name": "SimBank",
    "account_number": "1234567890",
    "ifsc_code": "SIMB0001234"
  }
}
```

**Business Rules:**
- Only `admin` role can create vendors.
- A wallet is auto-created for the vendor upon onboarding.

---

#### DELETE /api/v1/vendors/:id

**🐛 BUG PF-015 — INJECT THIS:**
Soft-deletes the vendor (sets `status = 'deleted'`), returns 200 OK. BUT: does NOT check if the vendor has pending invoices. The `batch-executor` worker queries invoices with `status IN ('approved', 'scheduled')` but does NOT join on vendor status. When it tries to execute a payment for a deleted vendor's invoice, it fails with an unhandled null reference when trying to access `vendor.wallet_id` (because the service layer tries to fetch the vendor and either gets null or a deleted record).

---

#### POST /api/v1/invoices

**Request:**
```json
{
  "vendor_id": "uuid",
  "invoice_number": "INV-2025-001",
  "amount": "75000.00",
  "currency": "SIM",
  "description": "Cloud hosting - January 2025",
  "payer_wallet_id": "uuid"
}
```

**Business Rules:**
- `due_date` auto-computed from vendor's `payment_terms` and current date.
- `invoice_number` must be unique.

**🐛 BUG PF-014 — INJECT THIS:**
The due date calculation:
```typescript
function computeDueDate(paymentTerms: string, createdAt: Date): Date {
  const days = { immediate: 0, net_15: 15, net_30: 30, net_60: 60 };
  const due = new Date(createdAt);  // BUG: uses full timestamp, not date-only
  due.setDate(due.getDate() + days[paymentTerms]);
  return due;
}
```
The bug: if an invoice is created at `2025-01-31T23:50:00Z` with `net_30`, the due date is computed as `2025-03-02T23:50:00Z`. But the payment executor checks `due_date <= CURRENT_DATE` using date comparison. Since `2025-03-02T23:50:00Z` truncates to `2025-03-02` in date comparison, a payment that should be due on March 2nd might fire on March 1st in some timezone scenarios. The fix: normalize `createdAt` to date-only before adding days.

---

#### POST /api/v1/payment-batches/execute

Triggers batch processing of all approved invoices that are due.

**Logic:**
1. Find all invoices where `status = 'approved' AND due_date <= CURRENT_DATE`.
2. Group by vendor for settlement.
3. Execute each payment, create transaction records.
4. Generate settlement records.

**🐛 BUG PF-013 — INJECT THIS (Critical):**
For multi-currency settlements:
```typescript
// Individual payment (at payment creation time):
const rate = await getLatestExchangeRate(invoice.currency, vendor.currency);
invoice.metadata.exchange_rate_at_creation = rate;

// Batch settlement (at execution time):
const currentRate = await getLatestExchangeRate(from, to);  // fetches current cached rate
let batchTotal = 0;
for (const invoice of vendorInvoices) {
  batchTotal += invoice.amount * currentRate;  // Uses current rate for all
}

// Settlement record:
settlement.total_amount = sumOfOriginalAmounts;
settlement.exchange_rate_used = currentRate;
settlement.settled_amount = batchTotal;
```
The bug: individual invoices were created days/weeks apart, each with a different exchange rate at creation time. The batch settlement re-converts everything at the current rate. The reconciliation report compares `sum(invoice.amount * invoice.metadata.exchange_rate_at_creation)` vs `settlement.settled_amount` and they don't match because different rates were used.

---

#### GET /api/v1/settlements

**Query params:** `date_from`, `date_to`, `vendor_id`, `format` (json/csv)

**🐛 BUG PF-016 — INJECT THIS:**
The CSV export:
```typescript
function toCSV(settlements: Settlement[]): string {
  const header = 'vendor_name,amount,currency,settled_amount,settled_at\n';
  const rows = settlements.map(s => 
    `${s.vendor_name},${s.amount},${s.currency},${s.settled_amount},${s.settled_at}`
  ).join('\n');
  return header + rows;
}
```
Vendor names containing commas (e.g., "Acme Solutions, Inc.") break the CSV structure. Fields should be quoted: `"Acme Solutions, Inc."`.

---

## Phase 5: Fraud Detection & Audit

> **Goal**: Real-time fraud rules engine, transaction flagging, admin review queue, immutable audit log, and per-wallet rate limiting.

### Migration 005

```sql
-- 005_fraud_audit.sql

CREATE TABLE fraud_rules (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(200) NOT NULL,
    description TEXT,
    rule_type VARCHAR(30) NOT NULL CHECK (rule_type IN ('velocity', 'amount_threshold', 'geo_anomaly', 'pattern')),
    config JSONB NOT NULL,
    -- velocity example: { "max_transactions": 10, "window_minutes": 60, "scope": "sender" }
    -- amount_threshold example: { "max_amount": 10000000, "per_transaction": true }
    is_active BOOLEAN NOT NULL DEFAULT true,
    action VARCHAR(20) NOT NULL DEFAULT 'flag' CHECK (action IN ('flag', 'block', 'alert')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE flagged_transactions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    transaction_id UUID NOT NULL REFERENCES transactions(id),
    rule_id UUID NOT NULL REFERENCES fraud_rules(id),
    reason TEXT NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'released', 'blocked', 'escalated')),
    reviewed_by UUID REFERENCES users(id),
    reviewed_at TIMESTAMPTZ,
    review_notes TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_flagged_pending ON flagged_transactions(status) WHERE status = 'pending';

CREATE TABLE audit_log (
    id BIGSERIAL PRIMARY KEY,     -- sequential for ordering guarantee
    entity_type VARCHAR(50) NOT NULL,  -- 'wallet', 'transaction', 'expense_report', etc.
    entity_id UUID NOT NULL,
    action VARCHAR(50) NOT NULL,       -- 'create', 'update', 'delete', 'transfer', 'approve', etc.
    actor_id UUID NOT NULL REFERENCES users(id),
    changes JSONB,                     -- { field: { old: x, new: y } }
    metadata JSONB DEFAULT '{}',
    error_message TEXT,                -- populated on failures
    ip_address INET,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- This table is append-only. No UPDATE or DELETE allowed (enforced by app layer and DB trigger).
CREATE INDEX idx_audit_entity ON audit_log(entity_type, entity_id, created_at DESC);
CREATE INDEX idx_audit_actor ON audit_log(actor_id, created_at DESC);

-- Trigger to prevent updates/deletes on audit_log
CREATE OR REPLACE FUNCTION prevent_audit_modification() RETURNS TRIGGER AS $$
BEGIN
    RAISE EXCEPTION 'audit_log is immutable: % operations are not allowed', TG_OP;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER audit_log_immutable
    BEFORE UPDATE OR DELETE ON audit_log
    FOR EACH ROW EXECUTE FUNCTION prevent_audit_modification();
```

### Fraud Engine Design

The fraud engine is a middleware that runs AFTER a transfer is created but BEFORE the response is returned. Flow:

```
Transfer Request
  → Validate & Execute Transfer (status='pending' initially)
  → Run Fraud Rules Engine
    → If no rules triggered → set status='completed', return success
    → If rule triggered with action='flag' → set status='held', create flagged_transaction, return success with warning
    → If rule triggered with action='block' → rollback transfer, return error
```

### Endpoints

#### POST /api/v1/fraud/rules

**Request (velocity rule example):**
```json
{
  "name": "High-frequency sender",
  "description": "Flag when sender makes more than 10 transfers in 60 minutes",
  "rule_type": "velocity",
  "config": {
    "max_transactions": 10,
    "window_minutes": 60,
    "scope": "sender"
  },
  "action": "flag"
}
```

**🐛 BUG PF-017 — INJECT THIS (Critical):**
The velocity rule evaluates EACH transaction independently:
```typescript
async function checkVelocityRule(rule, transaction) {
  const count = await db.query(`
    SELECT COUNT(*) FROM transactions
    WHERE sender_wallet_id = $1
      AND created_at > now() - interval '${rule.config.window_minutes} minutes'
      AND status = 'completed'
  `, [transaction.sender_wallet_id]);
  
  return count >= rule.config.max_transactions;
}
```
The bug: a user can create 5 wallets and distribute transfers across them. Each wallet stays under the velocity threshold individually. The rule should aggregate by `sender.user_id` (via wallet → user join), not by individual `sender_wallet_id`. This allows trivial circumvention of fraud detection.

**🐛 BUG PF-020 — INJECT THIS:**
Rate limiting is applied per `wallet_id` in the rate limiter middleware. But the `POST /wallets` endpoint is NOT rate-limited (it's considered an account setup endpoint). A user can create unlimited wallets (one per new currency variant), then use each wallet for transfers, effectively bypassing the per-wallet rate limit. The wallets endpoint should have its own separate rate limit (e.g., max 5 wallet creations per hour per user).

---

#### GET /api/v1/fraud/flagged

**Query params:** `status`, `page`, `limit`

Returns flagged transactions with their associated rule and transaction details.

---

#### POST /api/v1/fraud/flagged/:id/release

**Request:**
```json
{
  "notes": "Verified with sender, legitimate transfer"
}
```

**Business Rules:**
- Only `admin` role can release.
- Sets transaction status from `held` to `completed`.
- Fires the webhook that was suppressed during the hold.

**🐛 BUG PF-019 — INJECT THIS:**
```typescript
async function releaseTransaction(flaggedId: string, reviewerId: string, notes: string) {
  const flagged = await getFlaggedTransaction(flaggedId);
  
  // Update flagged record
  await db.query(`UPDATE flagged_transactions SET status='released', reviewed_by=$1, review_notes=$2, reviewed_at=now() WHERE id=$3`,
    [reviewerId, notes, flaggedId]);
  
  // Update transaction status
  await db.query(`UPDATE transactions SET status='completed' WHERE id=$1`, [flagged.transaction_id]);
  
  // BUG: Webhook is NOT fired here
  // The original transfer flow skipped the webhook because status was 'held'
  // This release flow doesn't call webhookService.deliver()
  // So the receiver never gets notified that the payment landed
}
```

---

#### GET /api/v1/audit-log

**Query params:** `entity_type`, `entity_id`, `actor_id`, `action`, `date_from`, `date_to`, `page`, `limit`

**🐛 BUG PF-018 — INJECT THIS:**
In the audit logging utility:
```typescript
async function logAudit(params: AuditParams) {
  try {
    const result = await someOperation();
    await db.query(`INSERT INTO audit_log (...) VALUES (...)`, [
      params.entity_type, params.entity_id, params.action,
      params.actor_id, params.changes, params.metadata, null, params.ip
    ]);
    return result;
  } catch (error) {
    // BUG: audit entry is written BEFORE the catch, so on failure
    // the entry was already inserted (in the try block) with error_message=null
    // This catch block writes a SECOND audit entry with the error
    await db.query(`INSERT INTO audit_log (...) VALUES (...)`, [
      params.entity_type, params.entity_id, params.action,
      params.actor_id, null, params.metadata, error.message, params.ip
    ]);
    throw error;
  }
}
```
Actually, the simpler bug: the audit entry is written with `error_message = null` at the START of the operation (optimistically). If the operation fails, a second entry IS written with the error... but wait, the original code doesn't work that way. Let me simplify:

The REAL bug: the audit log write happens in a `finally` block but the `error` variable is captured in the `catch` block which runs AFTER the audit log write in the try block. Net result: failed operations have an audit entry with `error_message: null` because the error wasn't captured yet at write time. Refactor as:

```typescript
// What's actually implemented:
async function withAudit(params, operation) {
  let error_msg = null;
  try {
    return await operation();
  } catch (err) {
    error_msg = err.message;
    throw err;
  } finally {
    // This runs, but on failure the audit entry records the request but NOT the error
    // because error_msg is set in catch, but the audit write in try already happened
  }
}
```
**Simplest injection:** Failed transfer attempts log to audit with `error_message: null`. The error reason is lost.

---

## Phase 6: Analytics & Reporting

> **Goal**: Dashboard APIs, scheduled report generation, budget tracking, anomaly detection, and OAuth2 for third-party access.

### Migration 006

```sql
-- 006_analytics.sql

CREATE TABLE department_budgets (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    department VARCHAR(100) NOT NULL,
    fiscal_year INT NOT NULL,
    fiscal_quarter INT NOT NULL CHECK (fiscal_quarter BETWEEN 1 AND 4),
    allocated_amount BIGINT NOT NULL,
    spent_amount BIGINT NOT NULL DEFAULT 0,
    currency VARCHAR(10) NOT NULL DEFAULT 'SIM',
    UNIQUE(department, fiscal_year, fiscal_quarter)
);

CREATE TABLE oauth_clients (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    client_id VARCHAR(64) UNIQUE NOT NULL,
    client_secret_hash VARCHAR(128) NOT NULL,
    name VARCHAR(200) NOT NULL,
    redirect_uris TEXT[] NOT NULL,
    scopes TEXT[] NOT NULL,            -- e.g., {'read:transactions', 'read:wallets'}
    is_active BOOLEAN NOT NULL DEFAULT true,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE oauth_tokens (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    client_id UUID NOT NULL REFERENCES oauth_clients(id),
    user_id UUID NOT NULL REFERENCES users(id),
    access_token_hash VARCHAR(128) UNIQUE NOT NULL,
    refresh_token_hash VARCHAR(128) UNIQUE NOT NULL,
    scopes TEXT[] NOT NULL,
    access_token_expires_at TIMESTAMPTZ NOT NULL,
    refresh_token_expires_at TIMESTAMPTZ NOT NULL,
    revoked_at TIMESTAMPTZ,          -- null = active
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE scheduled_reports (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id),
    report_type VARCHAR(50) NOT NULL CHECK (report_type IN ('daily_summary', 'weekly_summary', 'monthly_summary', 'budget_status')),
    config JSONB NOT NULL DEFAULT '{}',  -- filters, format preferences
    frequency VARCHAR(20) NOT NULL CHECK (frequency IN ('daily', 'weekly', 'monthly')),
    format VARCHAR(10) NOT NULL DEFAULT 'json' CHECK (format IN ('json', 'csv')),
    last_generated_at TIMESTAMPTZ,
    next_generation_at TIMESTAMPTZ NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT true,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

### Endpoints

#### GET /api/v1/reports/dashboard

**Query params:** `date` (optional, defaults to today), `timezone` (optional)

**Response:**
```json
{
  "success": true,
  "data": {
    "date": "2025-03-15",
    "total_volume": "1250000.00",
    "transaction_count": 347,
    "top_senders": [
      { "wallet_id": "uuid", "username": "alice", "total_sent": "450000.00" }
    ],
    "category_breakdown": [
      { "category": "Travel", "amount": "320000.00", "count": 45 },
      { "category": "Meals & Entertainment", "amount": "180000.00", "count": 89 }
    ],
    "pending_approvals": 12,
    "flagged_transactions": 3
  }
}
```

**🐛 BUG PF-021 — INJECT THIS:**
The dashboard query:
```typescript
async function getDashboard(date?: string) {
  const targetDate = date || new Date().toISOString().split('T')[0];
  
  const volume = await db.query(`
    SELECT COALESCE(SUM(amount), 0) as total, COUNT(*) as count
    FROM transactions
    WHERE created_at >= $1::date
      AND created_at < ($1::date + interval '1 day')
  `, [targetDate]);
  // ...
}
```
The bug: when no `date` param is provided, it defaults to today in UTC. But if the user is in IST (UTC+5:30), "today" for them started 5.5 hours before UTC midnight. Transactions from 00:00 IST to 05:30 IST (which are 18:30-00:00 UTC the previous day) are missing from "today's" dashboard. The endpoint should accept a `timezone` parameter and adjust the date range accordingly. The current implementation ignores the timezone param even if provided.

---

#### GET /api/v1/reports/weekly

**Query params:** `week_of` (ISO date, optional)

**🐛 BUG PF-022 — INJECT THIS:**
```typescript
async function getWeeklyReport(weekOf?: string) {
  const now = weekOf ? new Date(weekOf) : new Date();
  const start = new Date(now);
  start.setDate(start.getDate() - 7);  // BUG: just subtracts 7 days
  
  // Should compute "last Monday to last Sunday" boundaries
  // Instead computes "7 days ago to now" which:
  // - If run on Monday: includes today's partial data
  // - If run on Wednesday: covers Wed-Tue instead of Mon-Sun
}
```

---

#### POST /api/v1/oauth/token

**Request (authorization code grant):**
```json
{
  "grant_type": "authorization_code",
  "code": "auth-code-here",
  "redirect_uri": "https://app.example.com/callback",
  "client_id": "client-id",
  "client_secret": "client-secret"
}
```

**Request (refresh grant):**
```json
{
  "grant_type": "refresh_token",
  "refresh_token": "refresh-token-here",
  "client_id": "client-id",
  "client_secret": "client-secret"
}
```

**🐛 BUG PF-023 — INJECT THIS:**
On refresh token grant:
```typescript
async function refreshAccessToken(refreshToken: string, clientId: string) {
  const tokenRecord = await db.query(`
    SELECT * FROM oauth_tokens 
    WHERE refresh_token_hash = $1 AND revoked_at IS NULL
  `, [hash(refreshToken)]);
  
  // Generate new tokens
  const newAccessToken = generateToken();
  const newRefreshToken = generateToken();
  
  // Insert new token record
  await db.query(`INSERT INTO oauth_tokens (...) VALUES (...)`, [
    clientId, tokenRecord.user_id, hash(newAccessToken), hash(newRefreshToken), ...
  ]);
  
  // BUG: Old token record is NOT revoked
  // Missing: UPDATE oauth_tokens SET revoked_at = now() WHERE id = $1
  // Both old and new access tokens work until natural expiry
  
  return { access_token: newAccessToken, refresh_token: newRefreshToken };
}
```

---

#### GET /api/v1/reports/budget

**Query params:** `department`, `fiscal_year`, `fiscal_quarter`

**🐛 BUG PF-024 — INJECT THIS:**
The spent amount calculation:
```typescript
const spent = await db.query(`
  SELECT COALESCE(SUM(total_amount), 0) as spent
  FROM expense_reports
  WHERE department = $1
    AND fiscal_year = $2
    AND fiscal_quarter = $3
    -- BUG: No status filter! Counts draft, submitted, rejected, AND approved
    -- Should be: AND status IN ('approved', 'reimbursed')
`, [department, year, quarter]);
```
Pending and even rejected expense reports count toward the spent budget, making it look like the team is over-spending.

---

## Docker Setup

### docker-compose.yml

```yaml
version: "3.8"
services:
  api:
    build: .
    ports:
      - "3000:3000"
    environment:
      DATABASE_URL: postgres://payflow:payflow@db:5432/payflow
      NODE_ENV: development
      PORT: 3000
      LOG_LEVEL: debug
    depends_on:
      db:
        condition: service_healthy
    volumes:
      - ./src:/app/src

  worker:
    build: .
    command: npx tsx src/workers/payment-executor.ts
    environment:
      DATABASE_URL: postgres://payflow:payflow@db:5432/payflow
      WORKER_INTERVAL_MS: 60000
    depends_on:
      db:
        condition: service_healthy

  db:
    image: postgres:16-alpine
    environment:
      POSTGRES_USER: payflow
      POSTGRES_PASSWORD: payflow
      POSTGRES_DB: payflow
    ports:
      - "5432:5432"
    volumes:
      - pgdata:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U payflow"]
      interval: 5s
      timeout: 3s
      retries: 5

volumes:
  pgdata:
```

### Dockerfile

```dockerfile
FROM node:20-alpine
WORKDIR /app
COPY package*.json ./
RUN npm ci
COPY . .
EXPOSE 3000
CMD ["npx", "tsx", "src/index.ts"]
```

---

## Implementation Order (for Claude Code)

Feed these instructions one phase at a time:

### Prompt 1 — Project Setup + Phase 1
```
Set up the PayFlow project: init npm with TypeScript, install dependencies
(express, pg, zod, pino, vitest, supertest, dotenv, node-pg-migrate),
create the project structure, docker-compose, migration 001, and implement
all Phase 1 endpoints (wallets CRUD, transfers, transaction history).
Include all bugs as documented. Write tests. Make it runnable with
docker-compose up.
```

### Prompt 2 — Phase 2
```
Add Phase 2 to PayFlow: scheduled payments, recurring payments, webhook
subscriptions, webhook delivery with retries, and the payment executor
worker. Migration 002. All bugs as documented. Tests.
```

### Prompt 3 — Phase 3
```
Add Phase 3 to PayFlow: expense reports with line items, approval workflow
(submit → review → approve/reject → reimburse), multi-level approval,
bulk actions, expense categories with policy limits. Migration 003.
All bugs as documented. Tests.
```

### Prompt 4 — Phase 4
```
Add Phase 4 to PayFlow: vendor onboarding, invoices, payment batching,
multi-currency with exchange rates, settlement reports with CSV export.
Migration 004. Batch executor worker. All bugs as documented. Tests.
```

### Prompt 5 — Phase 5
```
Add Phase 5 to PayFlow: fraud rules engine (velocity, amount threshold),
transaction flagging and hold, admin review queue, immutable audit log
with DB trigger, per-wallet rate limiting. Migration 005. All bugs as
documented. Tests.
```

### Prompt 6 — Phase 6
```
Add Phase 6 to PayFlow: dashboard endpoints, weekly/monthly reports,
department budget tracking, OAuth2 (authorization code + refresh grants),
scheduled report generation. Migration 006. All bugs as documented. Tests.
```

---

## Bug Manifest (Quick Reference)

| ID | Phase | Severity | One-liner |
|----|-------|----------|-----------|
| PF-001 | 1 | Critical | Double-debit on concurrent retry (idempotency race) |
| PF-002 | 1 | Medium | Pagination returns limit+1 items |
| PF-003 | 1 | Low | Balance as number in list endpoint, string in detail |
| PF-004 | 1 | Medium | Zero-amount transfer allowed |
| PF-005 | 2 | Critical | Monthly payments on 31st double-fire in 30-day months |
| PF-006 | 2 | High | Cancelled recurring payment executes one more time |
| PF-007 | 2 | Medium | Webhook retry signature mismatch |
| PF-008 | 2 | Low | Scheduled payments list includes executed/cancelled |
| PF-009 | 3 | Critical | Self-approval of expense reports |
| PF-010 | 3 | High | Bulk approve returns 200 even on partial failure |
| PF-011 | 3 | Medium | Threshold amount skips multi-level approval (> vs >=) |
| PF-012 | 3 | Low | Receipt URL accepts any string (no validation) |
| PF-013 | 4 | Critical | Settlement reconciliation mismatch (mixed exchange rates) |
| PF-014 | 4 | High | Due date off-by-one from timestamp vs date |
| PF-015 | 4 | Medium | Deleted vendor's invoices crash batch executor |
| PF-016 | 4 | Low | CSV export breaks on vendor names with commas |
| PF-017 | 5 | Critical | Fraud velocity bypass via multiple wallets |
| PF-018 | 5 | High | Audit log missing error reason on failures |
| PF-019 | 5 | High | Released held transaction doesn't fire webhook |
| PF-020 | 5 | Medium | Unlimited wallet creation bypasses rate limits |
| PF-021 | 6 | High | Dashboard timezone mismatch (UTC vs user TZ) |
| PF-022 | 6 | Medium | Weekly report uses rolling 7 days, not Mon-Sun |
| PF-023 | 6 | High | OAuth refresh doesn't revoke old token |
| PF-024 | 6 | Low | Budget counts pending/rejected expenses as spent |
