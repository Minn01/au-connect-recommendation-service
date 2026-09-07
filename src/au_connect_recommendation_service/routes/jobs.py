"""
app/routes/jobs.py: 
Route for (job post / job) recommendations are set here
"""

from fastapi import Depends
from fastapi.routing import APIRouter

from au_connect_recommendation_service.core.security import verifyServiceKey
from au_connect_recommendation_service.services.job_recommender import get_job_recommendations


router = APIRouter(
    prefix="/recommendations/jobs",
    tags=["Job Recommendations"],
    dependencies=[Depends(verifyServiceKey)]
)

@router.get("/{user_id}")
async def recommend_jobs(
    user_id: str,
    limit: int = 10,
):
    recommendations = await get_job_recommendations(
        user_id=user_id,
        limit=limit,
    )

    return {"recommendations": recommendations}
