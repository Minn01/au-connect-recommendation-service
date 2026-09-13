import logging

from bson import ObjectId
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status

from au_connect_recommendation_service.core.security import verifyServiceKey
from au_connect_recommendation_service.db.mongodb import db
from au_connect_recommendation_service.services.profile_embeddings import (
    refresh_user_embedding,
)

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/internal/users",
    tags=["Internal Profile Embeddings"],
    dependencies=[Depends(verifyServiceKey)],
)


async def refresh_user_embedding_background(user_id: str) -> None:
    try:
        await refresh_user_embedding(user_id)
    except Exception:
        logger.exception("Profile embedding refresh failed for user %s", user_id)
        raise


@router.put("/{user_id}/embedding", status_code=status.HTTP_202_ACCEPTED)
async def schedule_user_embedding_refresh(
    user_id: str,
    background_tasks: BackgroundTasks,
):
    if not ObjectId.is_valid(user_id):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Invalid user ID",
        )

    object_id = ObjectId(user_id)
    user = await db["User"].find_one({"_id": object_id}, {"_id": 1})
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    background_tasks.add_task(refresh_user_embedding_background, user_id)
    return {"status": "accepted", "userId": user_id}
