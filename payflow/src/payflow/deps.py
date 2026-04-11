"""FastAPI dependencies — DB session and auth."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Annotated

import aiosqlite
from fastapi import Depends, Header

from payflow.database import get_connection
from payflow.exceptions import AppError
from payflow.services.user_service import get_user_by_api_key
from payflow.types.user import UserPublic


async def get_db() -> AsyncGenerator[aiosqlite.Connection, None]:
    async with get_connection() as conn:
        yield conn


async def require_user(
    conn: Annotated[aiosqlite.Connection, Depends(get_db)],
    x_api_key: Annotated[str | None, Header(alias="X-API-Key")] = None,
) -> UserPublic:
    if not x_api_key:
        raise AppError(
            "UNAUTHORIZED",
            "Missing X-API-Key header",
            status_code=401,
        )
    user = await get_user_by_api_key(conn, x_api_key)
    if user is None:
        raise AppError(
            "UNAUTHORIZED",
            "Invalid or inactive API key",
            status_code=401,
        )
    return user


DbDep = Annotated[aiosqlite.Connection, Depends(get_db)]
UserDep = Annotated[UserPublic, Depends(require_user)]
