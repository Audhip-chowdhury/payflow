#!/usr/bin/env python3
"""Hit every Phase 3 expense endpoint with valid payloads; print status + JSON.

Run from the payflow project root (where pyproject.toml lives), with the package installed::

    pip install -e ".[dev]"
    python scripts/smoke_phase3.py

Uses DATABASE_PATH from .env. API keys are read from the users table for usernames
charlie and bob, unless SMOKE_CHARLIE_KEY / SMOKE_BOB_KEY are set.
"""

from __future__ import annotations

import asyncio
import json
import os
import sqlite3
import sys
from pathlib import Path
from typing import Any

# Ensure repo root is importable when run as `python scripts/smoke_phase3.py`
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT / "src"))

os.environ.setdefault("ENABLE_WORKER", "false")

import httpx
from httpx import ASGITransport

from payflow.config import get_settings
from payflow.main import create_app
from payflow.migrations_runner import run_alembic_upgrade


def _print_step(title: str, status: int, body: Any) -> None:
    print(f"\n{'=' * 72}\n{title}\n{'=' * 72}")
    print(f"HTTP {status}")
    print(json.dumps(body, indent=2, default=str))


def _load_keys_from_db(db_path: Path) -> tuple[str, str]:
    env_c = os.environ.get("SMOKE_CHARLIE_KEY")
    env_b = os.environ.get("SMOKE_BOB_KEY")
    if env_c and env_b:
        return env_c.strip(), env_b.strip()
    conn = sqlite3.connect(db_path)
    try:
        conn.row_factory = sqlite3.Row
        cur = conn.execute(
            "SELECT username, api_key FROM users WHERE username IN ('charlie', 'bob')"
        )
        rows = {r["username"]: r["api_key"] for r in cur.fetchall()}
    finally:
        conn.close()
    if "charlie" not in rows or "bob" not in rows:
        raise SystemExit(
            "Need users charlie and bob in the database (run seed), or set "
            "SMOKE_CHARLIE_KEY and SMOKE_BOB_KEY."
        )
    return rows["charlie"], rows["bob"]


async def run() -> None:
    get_settings.cache_clear()
    settings = get_settings()
    db_abs = settings.database_path.resolve()
    print(f"DATABASE_PATH: {db_abs}")
    settings.database_path.parent.mkdir(parents=True, exist_ok=True)
    run_alembic_upgrade()

    charlie_key, bob_key = _load_keys_from_db(Path(settings.database_path))

    app = create_app()
    transport = ASGITransport(app=app)
    base = "http://smoke"

    async with httpx.AsyncClient(transport=transport, base_url=base, timeout=60.0) as client:
        h_charlie = {"X-API-Key": charlie_key}
        h_bob = {"X-API-Key": bob_key}

        # 1. GET /expense-categories
        r = await client.get("/api/v1/expense-categories", headers=h_charlie)
        data = r.json()
        _print_step("GET /api/v1/expense-categories", r.status_code, data)
        if r.status_code != 200 or not data.get("success"):
            raise SystemExit("Categories request failed — run seed to create categories.")
        cats = data.get("data") or []
        if not cats:
            raise SystemExit("No expense categories in DB.")
        cat_id = cats[0]["id"]

        line_date = "2026-01-15"

        # 2. POST /expense-reports (Report A)
        body_a = {
            "title": "Smoke A — approve path",
            "line_items": [
                {
                    "category_id": cat_id,
                    "description": "Smoke line A",
                    "amount": "25.00",
                    "date": line_date,
                }
            ],
        }
        r = await client.post("/api/v1/expense-reports", json=body_a, headers=h_charlie)
        _print_step("POST /api/v1/expense-reports (draft A)", r.status_code, r.json())
        r.raise_for_status()
        report_a = r.json()["data"]["id"]

        # 3. GET /expense-reports/{id}
        r = await client.get(f"/api/v1/expense-reports/{report_a}", headers=h_charlie)
        _print_step(f"GET /api/v1/expense-reports/{report_a}", r.status_code, r.json())

        # 4. GET /expense-reports (charlie — own reports)
        r = await client.get(
            "/api/v1/expense-reports", headers=h_charlie, params={"page": 1, "limit": 10}
        )
        _print_step("GET /api/v1/expense-reports (charlie, page=1)", r.status_code, r.json())

        # 5. POST submit A
        r = await client.post(
            f"/api/v1/expense-reports/{report_a}/submit", headers=h_charlie
        )
        _print_step(f"POST /api/v1/expense-reports/{report_a}/submit", r.status_code, r.json())
        r.raise_for_status()

        # 6. POST approve A (bob)
        r = await client.post(
            f"/api/v1/expense-reports/{report_a}/approve",
            json={"notes": "Approved via smoke"},
            headers=h_bob,
        )
        _print_step(f"POST /api/v1/expense-reports/{report_a}/approve", r.status_code, r.json())
        r.raise_for_status()

        # 7–9. Report B: create, submit, reject
        body_b = {
            "title": "Smoke B — reject path",
            "line_items": [
                {
                    "category_id": cat_id,
                    "description": "Smoke line B",
                    "amount": "15.00",
                    "date": line_date,
                }
            ],
        }
        r = await client.post("/api/v1/expense-reports", json=body_b, headers=h_charlie)
        _print_step("POST /api/v1/expense-reports (draft B)", r.status_code, r.json())
        r.raise_for_status()
        report_b = r.json()["data"]["id"]

        r = await client.post(
            f"/api/v1/expense-reports/{report_b}/submit", headers=h_charlie
        )
        _print_step(f"POST /api/v1/expense-reports/{report_b}/submit", r.status_code, r.json())
        r.raise_for_status()

        r = await client.post(
            f"/api/v1/expense-reports/{report_b}/reject",
            json={"reason": "Rejected via smoke script"},
            headers=h_bob,
        )
        _print_step(f"POST /api/v1/expense-reports/{report_b}/reject", r.status_code, r.json())
        r.raise_for_status()

        # 10–13. Reports C & D: create + submit each
        async def create_submit(title: str, amount: str) -> str:
            rr = await client.post(
                "/api/v1/expense-reports",
                json={
                    "title": title,
                    "line_items": [
                        {
                            "category_id": cat_id,
                            "description": "bulk batch line",
                            "amount": amount,
                            "date": line_date,
                        }
                    ],
                },
                headers=h_charlie,
            )
            rr.raise_for_status()
            rid = rr.json()["data"]["id"]
            sr = await client.post(
                f"/api/v1/expense-reports/{rid}/submit", headers=h_charlie
            )
            sr.raise_for_status()
            return rid

        report_c = await create_submit("Smoke C — bulk", "12.00")
        report_d = await create_submit("Smoke D — bulk", "13.00")
        _print_step(
            "POST create+submit C and D (ids for bulk)",
            200,
            {"report_c": report_c, "report_d": report_d},
        )

        # 14. POST bulk-action approve
        r = await client.post(
            "/api/v1/expense-reports/bulk-action",
            json={
                "action": "approve",
                "report_ids": [report_c, report_d],
                "notes": "Bulk approved via smoke",
            },
            headers=h_bob,
        )
        _print_step(
            "POST /api/v1/expense-reports/bulk-action (approve C,D)",
            r.status_code,
            r.json(),
        )

        # Optional: PF-010 mixed (one bad id), still 200
        r = await client.post(
            "/api/v1/expense-reports/bulk-action",
            json={
                "action": "approve",
                "report_ids": [report_c, "00000000-0000-4000-8000-00000000dead"],
                "notes": "expect one failed",
            },
            headers=h_bob,
        )
        _print_step(
            "POST /api/v1/expense-reports/bulk-action (mixed success/fail, PF-010)",
            r.status_code,
            r.json(),
        )

        # 15. GET /expense-reports with status filter (manager)
        r = await client.get(
            "/api/v1/expense-reports",
            headers=h_bob,
            params={"page": 1, "limit": 20, "status": "reimbursed"},
        )
        _print_step(
            "GET /api/v1/expense-reports?status=reimbursed (bob)",
            r.status_code,
            r.json(),
        )

    print("\nDone. All Phase 3 routes exercised.\n")


def main() -> None:
    if not Path("pyproject.toml").exists() and (_ROOT / "pyproject.toml").exists():
        os.chdir(_ROOT)
    asyncio.run(run())


if __name__ == "__main__":
    main()
