#!/usr/bin/env python3
"""Exercise every Phase 4 endpoint; print HTTP status + body (JSON or CSV text).

Run from the payflow project root::

    pip install -e ".[dev]"
    python -m payflow.seed
    python scripts/smoke_phase4.py

Uses DATABASE_PATH from .env. Loads admin key + SIM wallet from user ``alice`` unless
``SMOKE_ADMIN_KEY`` and ``SMOKE_PAYER_WALLET_ID`` are set.
"""

from __future__ import annotations

import asyncio
import json
import os
import sqlite3
import sys
import time
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT / "src"))

os.environ.setdefault("ENABLE_WORKER", "false")
os.environ.setdefault("ENABLE_BATCH_WORKER", "false")

import httpx
from httpx import ASGITransport

from payflow.config import get_settings
from payflow.main import create_app
from payflow.migrations_runner import run_alembic_upgrade


def _print_step(title: str, status: int, body: Any, *, raw_text: str | None = None) -> None:
    print(f"\n{'=' * 72}\n{title}\n{'=' * 72}")
    print(f"HTTP {status}")
    if raw_text is not None:
        print(raw_text[:8000] + ("..." if len(raw_text) > 8000 else ""))
    else:
        print(json.dumps(body, indent=2, default=str))


def _load_admin(db_path: Path) -> tuple[str, str]:
    env_k = os.environ.get("SMOKE_ADMIN_KEY")
    env_w = os.environ.get("SMOKE_PAYER_WALLET_ID")
    if env_k and env_w:
        return env_k.strip(), env_w.strip()
    conn = sqlite3.connect(db_path)
    try:
        conn.row_factory = sqlite3.Row
        cur = conn.execute(
            """
            SELECT u.api_key, w.id AS wallet_id
            FROM users u
            JOIN wallets w ON w.user_id = u.id AND w.currency = 'SIM'
            WHERE u.username = 'alice' AND u.is_active = 1
            LIMIT 1
            """
        )
        row = cur.fetchone()
    finally:
        conn.close()
    if row is None:
        raise SystemExit(
            "Need user alice with a SIM wallet (run: python -m payflow.seed), or set "
            "SMOKE_ADMIN_KEY and SMOKE_PAYER_WALLET_ID."
        )
    return row["api_key"], row["wallet_id"]


async def run() -> None:
    get_settings.cache_clear()
    settings = get_settings()
    db_abs = settings.database_path.resolve()
    print(f"DATABASE_PATH: {db_abs}")
    settings.database_path.parent.mkdir(parents=True, exist_ok=True)
    run_alembic_upgrade()

    admin_key, payer_wid = _load_admin(Path(settings.database_path))
    h = {"X-API-Key": admin_key}

    app = create_app()
    transport = ASGITransport(app=app)

    uniq = str(int(time.time()))
    vendor_a_name = f"Smoke Vendor Alpha {uniq}"
    inv_no_a = f"INV-SMOKE-A-{uniq}"

    async with httpx.AsyncClient(transport=transport, base_url="http://smoke", timeout=120.0) as client:
        # 1. GET /vendors (list, may be empty)
        r = await client.get("/api/v1/vendors", headers=h, params={"page": 1, "limit": 10})
        _print_step("GET /api/v1/vendors?page=1&limit=10", r.status_code, r.json())

        # 2. POST /vendors
        r = await client.post(
            "/api/v1/vendors",
            json={
                "name": vendor_a_name,
                "email": f"alpha-{uniq}@smoke.example",
                "tax_id": "TAX-SMOKE",
                "payment_terms": "immediate",
                "bank_details": {
                    "bank_name": "SimBank",
                    "account_number": "111",
                    "ifsc_code": "SIMB0001",
                },
            },
            headers=h,
        )
        _print_step("POST /api/v1/vendors", r.status_code, r.json())
        r.raise_for_status()
        vendor_a_id = r.json()["data"]["id"]

        # 3. GET /vendors again
        r = await client.get("/api/v1/vendors", headers=h, params={"page": 1, "limit": 10})
        _print_step("GET /api/v1/vendors (after create)", r.status_code, r.json())

        # 4. POST /invoices
        r = await client.post(
            "/api/v1/invoices",
            json={
                "vendor_id": vendor_a_id,
                "invoice_number": inv_no_a,
                "amount": "42.00",
                "currency": "SIM",
                "description": "Smoke invoice A",
                "payer_wallet_id": payer_wid,
            },
            headers=h,
        )
        _print_step("POST /api/v1/invoices", r.status_code, r.json())
        r.raise_for_status()
        invoice_a_id = r.json()["data"]["id"]

        # 5. GET /invoices
        r = await client.get(
            "/api/v1/invoices", headers=h, params={"page": 1, "limit": 10}
        )
        _print_step("GET /api/v1/invoices", r.status_code, r.json())

        # 6. POST /invoices/{id}/approve
        r = await client.post(
            f"/api/v1/invoices/{invoice_a_id}/approve",
            headers=h,
        )
        _print_step(
            f"POST /api/v1/invoices/{invoice_a_id}/approve",
            r.status_code,
            r.json(),
        )
        r.raise_for_status()

        # 7. POST /payment-batches/execute
        r = await client.post("/api/v1/payment-batches/execute", headers=h)
        _print_step("POST /api/v1/payment-batches/execute", r.status_code, r.json())

        # 8. GET /settlements JSON
        r = await client.get(
            "/api/v1/settlements",
            headers=h,
            params={"format": "json", "page": 1, "limit": 20},
        )
        _print_step(
            "GET /api/v1/settlements?format=json&page=1&limit=20",
            r.status_code,
            r.json(),
        )

        # 9. GET /settlements CSV (PF-016 style: unquoted)
        r = await client.get(
            "/api/v1/settlements",
            headers=h,
            params={"format": "csv", "page": 1, "limit": 10},
        )
        _print_step(
            "GET /api/v1/settlements?format=csv",
            r.status_code,
            {},
            raw_text=r.text,
        )

        # 10. Second vendor + invoice, soft-delete vendor, execute (PF-015 may raise)
        r = await client.post(
            "/api/v1/vendors",
            json={
                "name": f"Beta, Smoke Ltd {uniq}",
                "email": f"beta-{uniq}@smoke.example",
                "payment_terms": "immediate",
            },
            headers=h,
        )
        r.raise_for_status()
        vendor_b_id = r.json()["data"]["id"]

        r = await client.post(
            "/api/v1/invoices",
            json={
                "vendor_id": vendor_b_id,
                "invoice_number": f"INV-SMOKE-B-{uniq}",
                "amount": "5.00",
                "currency": "SIM",
                "payer_wallet_id": payer_wid,
            },
            headers=h,
        )
        r.raise_for_status()
        invoice_b_id = r.json()["data"]["id"]
        await client.post(
            f"/api/v1/invoices/{invoice_b_id}/approve",
            headers=h,
        )

        r = await client.delete(f"/api/v1/vendors/{vendor_b_id}", headers=h)
        _print_step(f"DELETE /api/v1/vendors/{vendor_b_id}", r.status_code, r.json())

        # 11. Execute with deleted vendor still in invoice queue (expect TypeError in ASGI)
        try:
            r = await client.post("/api/v1/payment-batches/execute", headers=h)
            _print_step(
                "POST /api/v1/payment-batches/execute (after PF-015 delete)",
                r.status_code,
                r.json() if r.headers.get("content-type", "").startswith("application/json") else {},
                raw_text=None if r.headers.get("content-type", "").startswith("application/json") else r.text,
            )
        except TypeError as e:
            print(f"\n{'=' * 72}\nPOST /api/v1/payment-batches/execute (PF-015 expected failure)\n{'=' * 72}")
            print("ASGI raised TypeError (expected when vendor row is missing):")
            print(json.dumps({"exception": type(e).__name__, "message": str(e)}, indent=2))

    print("\nDone. All Phase 4 HTTP routes exercised.\n")


def main() -> None:
    if not Path("pyproject.toml").exists() and (_ROOT / "pyproject.toml").exists():
        os.chdir(_ROOT)
    asyncio.run(run())


if __name__ == "__main__":
    main()
