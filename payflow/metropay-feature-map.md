# PayFlow — Product Feature Roadmap

> **Product**: PayFlow
> **Company**: MetroPay
> **Stack**: Node.js + TypeScript + Express.js + SQLite
> **Currency**: SimCash (SIM)

---

## What is PayFlow?

PayFlow is an internal payment and wallet platform. It handles SimCash transactions, expense management, vendor payments, fraud detection, and financial reporting for employees, managers, and vendors.

---

## Phase Overview

| Phase | Name | APIs | Worker | Bugs |
|-------|------|------|--------|------|
| 1 | Core Wallet & Transfers | 5 | — | PF-001 to PF-004 |
| 2 | Scheduled & Recurring Payments | 5 | payment-executor | PF-005 to PF-008 |
| 3 | Expense Reports & Approvals | 6 | — | PF-009 to PF-012 |
| 4 | Merchant & Vendor Payments | 5 | batch-executor | PF-013 to PF-016 |
| 5 | Fraud Detection & Audit | 4 | — | PF-017 to PF-020 |
| 6 | Analytics & Reporting | 5 | — | PF-021 to PF-024 |
| **Total** | | **30 APIs + 2 workers** | | **24 bugs** |

---

## Phase 1 — Core Wallet & Transfers

> The foundation. Users get wallets, send SimCash to each other, and view their transaction history.

### Features
- Create wallets per user (one per currency)
- Wallet-to-wallet SimCash transfers (atomic, with row locking)
- Transaction history with pagination and filters
- Idempotency key support on all write endpoints
- API key authentication via `X-API-Key` header

### APIs

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/v1/wallets` | Create a wallet |
| GET | `/api/v1/wallets/:id` | Get wallet + balance |
| GET | `/api/v1/wallets` | List wallets for current user |
| POST | `/api/v1/transfers` | Transfer SimCash between wallets |
| GET | `/api/v1/transactions` | List transactions for a wallet |

### Data Created
`users` → `wallets` → `transactions` → `idempotency_store`

### Bugs

| ID | Severity | Where | Description |
|----|----------|-------|-------------|
| PF-001 | Critical | `middleware/idempotency.ts` | Idempotency check runs outside DB transaction — concurrent retries cause double-debit (sender charged twice, receiver credited once) |
| PF-002 | Medium | `utils/pagination.ts` | Query fetches `limit + 1` rows but returns all of them — 11 items returned when limit=10 |
| PF-003 | Low | `wallet.service.ts` | `GET /wallets/:id` returns balance as string `"150.00"` (correct), but `GET /wallets` returns it as number `150` (wrong, loses precision) |
| PF-004 | Medium | Transfer zod schema | Amount validated by regex only — `"0.00"` passes, creates a transaction record but changes nothing |

---

## Phase 2 — Scheduled & Recurring Payments

> Users schedule one-time future payments or set up recurring schedules. A background worker executes them automatically.

### Features
- Schedule a one-time future transfer by date
- Set up recurring payments (daily / weekly / monthly)
- Pause or cancel scheduled/recurring payments
- Background worker runs every 60 seconds to execute due payments
- Webhook subscriptions with HMAC-SHA256 signatures
- Webhook delivery with retry logic

### APIs

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/v1/scheduled-payments` | Schedule a one-time payment |
| GET | `/api/v1/scheduled-payments` | List scheduled payments |
| PATCH | `/api/v1/scheduled-payments/:id` | Cancel a scheduled payment |
| POST | `/api/v1/recurring-payments` | Set up a recurring payment |
| POST | `/api/v1/webhooks` | Register a webhook subscription |

### Workers
- **payment-executor** — runs every 60s, processes due scheduled and recurring payments

### Data Created
`scheduled_payments` → `recurring_payments` → `webhook_subscriptions` → `webhook_deliveries`

### Bugs

| ID | Severity | Where | Description |
|----|----------|-------|-------------|
| PF-005 | Critical | `scheduler.service.ts` | Monthly payments set for the 31st use naive `setDate(31)` — rolls over to the 1st of the next month in 30-day months, causing double-fire |
| PF-006 | High | `workers/payment-executor.ts` | Worker pre-fetches all due payments at start of cycle — cancelling a recurring payment mid-cycle doesn't stop it from executing that cycle |
| PF-007 | Medium | `webhook.service.ts` | On retry, `X-Delivery-Timestamp` header is regenerated but the body timestamp isn't — HMAC signature mismatch for consumers who verify headers |
| PF-008 | Low | Scheduled payments list | No default `status=pending` filter — executed and cancelled payments appear in the default listing |

---

## Phase 3 — Expense Reports & Approvals

> Employees submit expense reports. Managers approve or reject them. Approved reports trigger automatic reimbursement to the employee's wallet.

### Features
- Create expense reports with line items and receipt URLs
- Expense categories with per-category policy limits
- Submit reports for approval
- Single-level and multi-level approval workflows (threshold-based)
- Approve / reject with notes
- Bulk approve/reject multiple reports at once
- Approved reports auto-reimburse to submitter's wallet

### APIs

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/v1/expense-reports` | Create expense report with line items |
| GET | `/api/v1/expense-reports` | List expense reports |
| POST | `/api/v1/expense-reports/:id/submit` | Submit draft for approval |
| POST | `/api/v1/expense-reports/:id/approve` | Approve a report |
| POST | `/api/v1/expense-reports/:id/reject` | Reject a report with reason |
| POST | `/api/v1/expense-reports/bulk-action` | Bulk approve or reject |

### Data Created
`expense_categories` → `expense_reports` → `expense_line_items` → `transactions` (on reimbursement)

### Bugs

| ID | Severity | Where | Description |
|----|----------|-------|-------------|
| PF-009 | Critical | `expense.service.ts` | Approval only checks `role=manager`, not `submitter_id !== approver_id` — a manager can approve their own expense report |
| PF-010 | High | Bulk action endpoint | Always returns HTTP 200 even when some reports fail — no 207 Multi-Status for partial failures |
| PF-011 | Medium | Submit endpoint | Multi-level approval triggered with `>` instead of `>=` — a report totalling exactly the threshold (50,000 SIM) skips multi-level review |
| PF-012 | Low | Expense report zod schema | `receipt_url` accepts any string — `javascript:alert(1)` or `file:///etc/passwd` pass validation |

---

## Phase 4 — Merchant & Vendor Payments

> PayFlow onboards external vendors, manages invoices, and pays them in scheduled batches. Supports multi-currency with exchange rates.

### Features
- Vendor onboarding (auto-creates a wallet for the vendor)
- Invoice creation with auto-computed due dates based on payment terms
- Invoice approval workflow
- Payment batching (group approved invoices and execute together)
- Multi-currency support with exchange rates
- Settlement reports with JSON and CSV export

### APIs

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/v1/vendors` | Onboard a vendor |
| DELETE | `/api/v1/vendors/:id` | Soft-delete a vendor |
| POST | `/api/v1/invoices` | Create an invoice |
| POST | `/api/v1/invoices/:id/approve` | Approve an invoice |
| POST | `/api/v1/payment-batches/execute` | Execute batch payment of due invoices |
| GET | `/api/v1/settlements` | Get settlement reports (JSON or CSV) |

### Workers
- **batch-executor** — processes all approved, due invoices into payment batches and settlements

### Data Created
`vendors` → `invoices` → `payment_batches` → `exchange_rates` → `settlements`

### Bugs

| ID | Severity | Where | Description |
|----|----------|-------|-------------|
| PF-013 | Critical | `batch-executor` worker | Invoices were created with exchange rate at time of creation — batch settlement re-converts everything at the current rate, causing reconciliation mismatches |
| PF-014 | High | `vendor.service.ts` | Due date computed from full timestamp instead of date-only — `net_30` invoice created at 23:50 has wrong due date by hours, causing early/late payment depending on timezone |
| PF-015 | Medium | `DELETE /vendors/:id` | Soft-deletes vendor without checking for pending invoices — batch executor tries to access deleted vendor's wallet and crashes with null reference |
| PF-016 | Low | Settlement CSV export | Vendor names with commas (e.g., "Acme, Inc.") break the CSV structure — fields are not quoted |

---

## Phase 5 — Fraud Detection & Audit

> A real-time fraud rules engine runs on every transfer. Suspicious transactions are held for review. Every financial operation is written to an immutable audit log.

### Features
- Configurable fraud rules (velocity, amount threshold, geo anomaly, pattern)
- Real-time fraud check runs after every transfer
- Transactions can be flagged (held) or blocked based on rule action
- Admin review queue for flagged transactions
- Release held transactions (triggers suppressed webhook)
- Immutable audit log with DB-level trigger preventing updates/deletes
- Per-wallet rate limiting middleware

### APIs

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/v1/fraud/rules` | Create a fraud rule |
| GET | `/api/v1/fraud/flagged` | List flagged (held) transactions |
| POST | `/api/v1/fraud/flagged/:id/release` | Release a held transaction |
| GET | `/api/v1/audit-log` | Query the audit log |

### Middleware Added
- **rate-limiter** — per-wallet request rate limiting applied to all transfer endpoints

### Data Created
`fraud_rules` → `flagged_transactions` → `audit_log`

### Bugs

| ID | Severity | Where | Description |
|----|----------|-------|-------------|
| PF-017 | Critical | `fraud.service.ts` | Velocity rule checks per `wallet_id` not per `user_id` — a user with 5 wallets distributes transfers across them, each stays under the threshold individually |
| PF-018 | High | `audit.service.ts` | Audit entry is written before the operation result is known — failed operations log `error_message: null`, losing the reason |
| PF-019 | High | `POST /fraud/flagged/:id/release` | Releasing a held transaction updates status to completed but never fires the webhook that was suppressed during the hold |
| PF-020 | Medium | Rate limiter middleware | `POST /wallets` is not rate-limited — unlimited wallets can be created per user, trivially bypassing per-wallet transfer limits |

---

## Phase 6 — Analytics & Reporting

> Dashboard APIs, budget tracking, scheduled report generation, and OAuth2 for third-party access.

### Features
- Live dashboard: daily volume, top senders, category breakdown, pending approvals
- Weekly summary report
- Department budget tracking vs actual spend
- Scheduled report generation (daily/weekly/monthly, JSON or CSV)
- OAuth2 authorization code flow + refresh token grant for third-party integrations

### APIs

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/v1/reports/dashboard` | Daily summary dashboard |
| GET | `/api/v1/reports/weekly` | Weekly transaction summary |
| GET | `/api/v1/reports/budget` | Department budget vs spend |
| POST | `/api/v1/oauth/token` | OAuth2 token exchange + refresh |
| POST | `/api/v1/scheduled-reports` | Create a scheduled report |

### Data Created
`department_budgets` → `oauth_clients` → `oauth_tokens` → `scheduled_reports`

### Bugs

| ID | Severity | Where | Description |
|----|----------|-------|-------------|
| PF-021 | High | `report.service.ts` | Dashboard defaults to UTC date boundaries — users in IST (UTC+5:30) are missing 5.5 hours of "today" — timezone param is accepted but ignored |
| PF-022 | Medium | `report.service.ts` | Weekly report subtracts 7 days from now instead of computing last Monday-to-Sunday — partial current week data bleeds in |
| PF-023 | High | OAuth token refresh | Refreshing a token issues new tokens but doesn't revoke the old ones — both old and new access tokens remain valid until natural expiry |
| PF-024 | Low | Budget report query | Spent amount counts ALL expense reports regardless of status — draft and rejected reports inflate the spent total |

---

## Complete Bug Manifest

| ID | Phase | Severity | Discovery | One-liner |
|----|-------|----------|-----------|-----------|
| PF-001 | 1 | 🔴 Critical | Hard | Double-debit on concurrent retry |
| PF-002 | 1 | 🟡 Medium | Easy | Pagination returns limit+1 items |
| PF-003 | 1 | 🟢 Low | Easy | Balance type mismatch: string vs number |
| PF-004 | 1 | 🟡 Medium | Easy | Zero-amount transfer allowed |
| PF-005 | 2 | 🔴 Critical | Hard | Monthly 31st payments double-fire |
| PF-006 | 2 | 🟠 High | Medium | Cancelled recurring payment fires once more |
| PF-007 | 2 | 🟡 Medium | Medium | Webhook retry HMAC mismatch |
| PF-008 | 2 | 🟢 Low | Easy | Scheduled payments list includes all statuses |
| PF-009 | 3 | 🔴 Critical | Medium | Self-approval of expense reports |
| PF-010 | 3 | 🟠 High | Medium | Bulk action always returns 200 OK |
| PF-011 | 3 | 🟡 Medium | Easy | Exact threshold skips multi-level approval |
| PF-012 | 3 | 🟢 Low | Easy | Receipt URL accepts any string |
| PF-013 | 4 | 🔴 Critical | Hard | Settlement exchange rate mismatch |
| PF-014 | 4 | 🟠 High | Medium | Invoice due date off-by-hours |
| PF-015 | 4 | 🟡 Medium | Medium | Deleted vendor crashes batch executor |
| PF-016 | 4 | 🟢 Low | Easy | CSV breaks on vendor names with commas |
| PF-017 | 5 | 🔴 Critical | Hard | Fraud velocity bypass via multiple wallets |
| PF-018 | 5 | 🟠 High | Medium | Audit log loses error reason on failures |
| PF-019 | 5 | 🟠 High | Medium | Released transaction never fires webhook |
| PF-020 | 5 | 🟡 Medium | Hard | Unlimited wallets bypass rate limits |
| PF-021 | 6 | 🟠 High | Medium | Dashboard ignores timezone, uses UTC |
| PF-022 | 6 | 🟡 Medium | Easy | Weekly report uses rolling 7 days not Mon-Sun |
| PF-023 | 6 | 🟠 High | Hard | OAuth refresh doesn't revoke old token |
| PF-024 | 6 | 🟢 Low | Easy | Budget counts draft/rejected expenses |

### Bug Distribution

| Severity | Count |
|----------|-------|
| 🔴 Critical | 4 |
| 🟠 High | 7 |
| 🟡 Medium | 8 |
| 🟢 Low | 5 |

| Discovery | Count |
|-----------|-------|
| Hard | 6 |
| Medium | 12 |
| Easy | 6 |

---

## Data Flow Summary

```
Users
  ├── own → Wallets
  │           ├── send/receive → Transactions
  │           │                     └── scanned by → Fraud Engine
  │           │                                           └── logs to → Audit Log
  ├── submit → Expense Reports
  │               └── reimburse via → Transactions
  └── manage → Vendors
                  └── bill via → Invoices
                                    └── batch into → Settlements
                                                         └── feed → Reports & Dashboard
```


