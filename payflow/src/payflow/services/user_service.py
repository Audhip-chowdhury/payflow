"""User lookups — API key auth."""

from __future__ import annotations

import aiosqlite

from payflow.database import fetch_one
from payflow.types.user import UserPublic


async def get_user_by_api_key(
    conn: aiosqlite.Connection,
    api_key: str,
) -> UserPublic | None:
    row = await fetch_one(
        conn,
        """
        SELECT id, username, email, role, is_active, created_at, updated_at
        FROM users
        WHERE api_key = ? AND is_active = 1
        """,
        (api_key,),
    )
    if row is None:
        return None
    u: UserPublic = {
        "id": row["id"],
        "username": row["username"],
        "email": row["email"],
        "role": row["role"],
        "is_active": bool(row["is_active"]),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }
    return u
