"""Authenticated identity (Phase 0 smoke test for API keys)."""

from __future__ import annotations

from fastapi import APIRouter

from payflow.deps import UserDep
from payflow.schemas.common import SuccessResponse
from payflow.schemas.user import UserResponse

router = APIRouter(prefix="/api/v1", tags=["identity"])


@router.get("/me", response_model=SuccessResponse[UserResponse])
async def read_me(user: UserDep) -> SuccessResponse[UserResponse]:
    return SuccessResponse(
        success=True,
        data=UserResponse.model_validate(dict(user)),
    )
