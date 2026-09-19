"""
app/routes/connections.py:
Route for connection recommendations are set here
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Query

from au_connect_recommendation_service.core.recommendation_cursor import InvalidCursor

from au_connect_recommendation_service.core.security import verifyServiceKey
from au_connect_recommendation_service.services.connection_recommender import get_connection_recommendations

router = APIRouter(
    prefix="/recommendations/connections",
    tags=["Connection Recommendations"],
    dependencies=[Depends(verifyServiceKey)],
)


@router.get("/{user_id}")
async def recommend_connections(
    user_id: Annotated[str, Path(pattern=r"^[0-9a-fA-F]{24}$")],
    limit: Annotated[int, Query(ge=1, le=50)] = 10,
    cursor: Annotated[str | None, Query(max_length=1024)] = None,
):
    try:
        page = await get_connection_recommendations(
            user_id=user_id,
            limit=limit,
            cursor=cursor,
        )
    except InvalidCursor as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {"success": True, "data": page, "error": None}
