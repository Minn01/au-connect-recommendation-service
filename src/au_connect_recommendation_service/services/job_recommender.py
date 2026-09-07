from bson import ObjectId

from au_connect_recommendation_service.db.mongodb import db


async def get_job_recommendations(
    user_id: str,
    limit: int = 10,
):

    users = db["User"]
    current_user = await users.find_one(
        {"_id": ObjectId(user_id)}
    )

    if current_user is None:
        return []

    return []
