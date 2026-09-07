"""
app/routes/connections.py:
Route for connection recommendations are set here
"""

from fastapi import APIRouter, Depends

from au_connect_recommendation_service.core.security import verifyServiceKey
from au_connect_recommendation_service.services.connection_recommender import get_connection_recommendations

router = APIRouter(
    prefix="/recommendations/connections",
    tags=["Connection Recommendations"],
    dependencies=[Depends(verifyServiceKey)],
)


@router.get("/{user_id}")
async def recommend_connections(
    user_id: str,
    limit: int = 10,
):
    recommendations = await get_connection_recommendations(
        user_id=user_id,
        limit=limit,
    )

    return {
        "success": True, 
        "data": {
            "recommendations": recommendations
        },
        "error": None,
    }
