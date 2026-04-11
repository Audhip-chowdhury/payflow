"""Webhook subscriptions."""

from __future__ import annotations

from payflow.database import get_connection
from payflow.deps import UserDep
from payflow.schemas.common import SuccessResponse
from payflow.schemas.webhook import WebhookCreate
from payflow.services import webhook_service

router = APIRouter(prefix="/api/v1", tags=["webhooks"])


@router.post("/webhooks", status_code=201)
async def create_webhook(
    body: WebhookCreate,
    user: UserDep,
) -> SuccessResponse[dict]:
    async with get_connection() as conn:
        data = await webhook_service.create_subscription(
            conn,
            user_id=user["id"],
            url=body.url,
            events=body.events,
            secret=body.secret,
        )
        await conn.commit()
    return SuccessResponse(success=True, data=data)
